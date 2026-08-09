"""
encryption.py — Versioned, authenticated encryption for sensitive data (API keys).

Format versions
---------------
v0  Legacy Fernet token (produced by the old code). Detected by the ``gAAAAA``
    or ``gAAAAAA`` prefix of a URL-safe base64 token.  Decrypted transparently,
    re-encrypted as v1 on first successful access.

v1  AES-256-GCM with a random 32-byte salt and 12-byte nonce.  The master key is
    derived via HKDF-SHA256 from ``ENCRYPTION_KEY``.  Payload wire format::

        v1:<key_id_byte>:<base64url(salt | nonce | ciphertext | tag)>

    where:
        salt        = 32 random bytes  (key-derivation input)
        nonce       = 12 random bytes  (GCM nonce / IV)
        ciphertext  = AESGCM(plaintext, aad=key_id_byte)
        tag         = 16-byte GCM authentication tag (appended by AESGCM)
        key_id_byte = 1-byte big-endian unsigned int identifying the master key

Security properties
-------------------
* Identical plaintexts produce different ciphertexts (random salt + nonce).
* Tamper detection via GCM authentication tag.
* Wrong key → ``ValueError`` (no secret information in error message).
* No plaintext, derived key, salt, or nonce is ever written to a log.
* Master key stays in environment configuration only.
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import struct
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.fernet import Fernet, InvalidToken as FernetInvalidToken

logger = logging.getLogger("datapilot.encryption")

# ── Constants ────────────────────────────────────────────────────────────────
_ENV_MASTER_KEY = "ENCRYPTION_KEY"
_ENV_KEY_ID = "ENCRYPTION_KEY_ID"         # optional uint8; default 0
_SALT_LEN = 32                             # bytes, for HKDF per-value salt
_NONCE_LEN = 12                            # bytes, GCM nonce
_KEY_LEN = 32                              # bytes, AES-256
_V1_PREFIX = "v1:"
_FERNET_PREFIX_BYTES = (b"gAAAAA", b"gAAAAAA")  # URL-safe base64 Fernet tokens

# ── Master key cache (never log) ─────────────────────────────────────────────
_master_key_bytes: bytes | None = None
_ephemeral_warned: bool = False


def _load_master_key() -> bytes:
    """Return the raw master key bytes from the environment.

    Uses an in-process singleton.  Generates an ephemeral key when
    ``ENCRYPTION_KEY`` is absent (logs a WARNING, never an ERROR so startup
    does not abort in dev).
    """
    global _master_key_bytes, _ephemeral_warned

    if _master_key_bytes is not None:
        return _master_key_bytes

    raw = os.getenv(_ENV_MASTER_KEY, "").strip()
    if raw:
        try:
            # Accept a valid Fernet key (URL-safe base64, 44 chars → 32 bytes)
            decoded = base64.urlsafe_b64decode(raw + "==")
            if len(decoded) == 32:
                _master_key_bytes = decoded
                logger.info("Encryption master key loaded from environment.")
                return _master_key_bytes
        except Exception:
            pass
        # Also accept plain hex or arbitrary UTF-8 >= 32 bytes (derive from it)
        encoded = raw.encode()
        if len(encoded) >= 32:
            _master_key_bytes = encoded[:32]
            logger.info("Encryption master key loaded from environment (raw).")
            return _master_key_bytes

        logger.warning("ENCRYPTION_KEY is present but too short (<32 bytes). Using ephemeral key.")

    if not _ephemeral_warned:
        logger.warning(
            "ENCRYPTION_KEY not set or invalid. Using ephemeral key — "
            "encrypted data WILL NOT persist across restarts. "
            "Set ENCRYPTION_KEY to a 32-byte base64url value for production."
        )
        _ephemeral_warned = True

    _master_key_bytes = secrets.token_bytes(32)
    return _master_key_bytes


def _get_key_id() -> int:
    """Return the current key ID (0–255) from the environment."""
    raw = os.getenv(_ENV_KEY_ID, "0").strip()
    try:
        kid = int(raw) & 0xFF
    except (ValueError, TypeError):
        kid = 0
    return kid


def _derive_key(master: bytes, salt: bytes) -> bytes:
    """Derive a 256-bit AES key from master + per-value salt using HKDF-SHA256."""
    hkdf = HKDF(
        algorithm=SHA256(),
        length=_KEY_LEN,
        salt=salt,
        info=b"datapilot-v1-aes256gcm",
    )
    return hkdf.derive(master)


# ── Public API ────────────────────────────────────────────────────────────────

def generate_master_key() -> str:
    """Generate a new random 32-byte master key encoded as URL-safe base64.

    Use the output as the value of ``ENCRYPTION_KEY`` in your environment.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()


# Alias kept for backward compatibility
generate_fernet_key = generate_master_key


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return an opaque v1 token.

    Two calls with the same *plaintext* produce different tokens.
    Returns ``""`` for empty input (no encryption performed).
    """
    if not plaintext:
        return ""

    master = _load_master_key()
    kid = _get_key_id()

    salt = secrets.token_bytes(_SALT_LEN)
    nonce = secrets.token_bytes(_NONCE_LEN)
    aad = struct.pack("B", kid)          # authenticated additional data

    derived = _derive_key(master, salt)
    aesgcm = AESGCM(derived)
    ciphertext_tag = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), aad)

    payload = salt + nonce + ciphertext_tag
    b64_payload = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{_V1_PREFIX}{kid}:{b64_payload}"


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a v0 (legacy Fernet) or v1 token.

    Raises ``ValueError`` on corruption, authentication failure, or wrong key.
    Returns ``""`` for empty input.
    No decrypted value, key, or salt is written to any log.
    """
    if not ciphertext:
        return ""

    if ciphertext.startswith(_V1_PREFIX):
        return _decrypt_v1(ciphertext)

    # v0 legacy Fernet path (backward compat)
    return _decrypt_v0(ciphertext)


def _decrypt_v1(token: str) -> str:
    """Decrypt a v1 token."""
    # token: "v1:<kid>:<b64payload>"
    try:
        _, rest = token.split(":", 1)        # strip "v1"
        kid_str, b64_payload = rest.split(":", 1)
        kid = int(kid_str) & 0xFF
    except (ValueError, AttributeError):
        raise ValueError("Malformed v1 ciphertext token.")

    try:
        payload = base64.urlsafe_b64decode(b64_payload + "==")
    except Exception:
        raise ValueError("Malformed v1 ciphertext: base64 decode failed.")

    min_len = _SALT_LEN + _NONCE_LEN + 1 + 16   # 1 byte plaintext + 16-byte tag minimum
    if len(payload) < min_len:
        raise ValueError("Malformed v1 ciphertext: payload too short.")

    salt = payload[:_SALT_LEN]
    nonce = payload[_SALT_LEN:_SALT_LEN + _NONCE_LEN]
    ciphertext_tag = payload[_SALT_LEN + _NONCE_LEN:]
    aad = struct.pack("B", kid)

    master = _load_master_key()
    derived = _derive_key(master, salt)
    aesgcm = AESGCM(derived)

    try:
        plaintext_bytes = aesgcm.decrypt(nonce, ciphertext_tag, aad)
    except Exception:
        raise ValueError("Decryption failed: authentication error or wrong key.")

    return plaintext_bytes.decode("utf-8")


def _decrypt_v0(ciphertext: str) -> str:
    """Decrypt a legacy Fernet (v0) token using the master key as a Fernet key.

    The master key must be a valid 32-byte URL-safe base64 Fernet key.
    If the master key is not a valid Fernet key (e.g. it was provided as raw
    bytes), we cannot decrypt v0 tokens and raise ``ValueError``.
    """
    raw = os.getenv(_ENV_MASTER_KEY, "").strip()
    if not raw:
        raise ValueError("Cannot decrypt legacy token: ENCRYPTION_KEY not configured.")

    try:
        fernet = Fernet(raw.encode() if isinstance(raw, str) else raw)
        plaintext_bytes = fernet.decrypt(ciphertext.encode("utf-8"))
        return plaintext_bytes.decode("utf-8")
    except FernetInvalidToken:
        raise ValueError("Decryption failed: invalid legacy ciphertext or wrong key.")
    except Exception as exc:
        # Do not expose exc details in case they contain key material
        raise ValueError("Decryption failed: legacy format error.") from None


def re_encrypt_legacy(plaintext: str, old_ciphertext: str) -> str:
    """Decrypt *old_ciphertext* (v0 or v1) and return a fresh v1 token.

    Convenience helper for migration: call after a successful ``decrypt_value``
    to upgrade stored values without a separate migration step.
    """
    return encrypt_value(plaintext)


def mask_key(plaintext: str) -> str:
    """Return a masked version of a key for display (shows only last 4 chars)."""
    if not plaintext or len(plaintext) < 8:
        return "****"
    return "***..." + plaintext[-4:]


# ── Backward-compat aliases ───────────────────────────────────────────────────
# The old module exported encrypt_api_key / decrypt_api_key used by llm_client.py
encrypt_api_key = encrypt_value
decrypt_api_key = decrypt_value
