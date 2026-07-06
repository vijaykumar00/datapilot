"""
encryption.py — Application-level AES encryption for sensitive data (API keys).
Uses Fernet symmetric encryption from the cryptography library.
"""
import os
import base64
import logging
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("datapilot.encryption")

# Load or generate encryption key
_ENCRYPTION_KEY_ENV = "ENCRYPTION_KEY"
_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Get or initialize the Fernet cipher, loading key from environment."""
    global _fernet
    if _fernet is not None:
        return _fernet

    raw_key = os.getenv(_ENCRYPTION_KEY_ENV)
    if raw_key:
        # Accept both raw base64url and plain base64 keys
        try:
            key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
            # Validate it's a valid Fernet key (32 url-safe base64 bytes = 44 chars)
            _fernet = Fernet(key_bytes)
            logger.info("Fernet encryption key loaded from environment.")
            return _fernet
        except Exception as e:
            logger.warning(f"Invalid ENCRYPTION_KEY in environment: {e}. Generating ephemeral key.")

    # No key configured: generate ephemeral key (data won't survive restarts)
    ephemeral_key = Fernet.generate_key()
    _fernet = Fernet(ephemeral_key)
    logger.warning(
        "No ENCRYPTION_KEY set. Using ephemeral key — encrypted data WILL NOT persist across restarts. "
        "Set ENCRYPTION_KEY env var for production."
    )
    return _fernet


def generate_fernet_key() -> str:
    """Generate a new Fernet key suitable for the ENCRYPTION_KEY env var."""
    return Fernet.generate_key().decode()


def encrypt_value(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    fernet = _get_fernet()
    ciphertext = fernet.encrypt(plaintext.encode("utf-8"))
    return ciphertext.decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext. Raises ValueError on failure."""
    if not ciphertext:
        return ""
    fernet = _get_fernet()
    try:
        plaintext = fernet.decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except InvalidToken:
        raise ValueError("Decryption failed: invalid ciphertext or wrong key.")
    except Exception as e:
        raise ValueError(f"Decryption error: {e}")


def mask_key(plaintext: str) -> str:
    """Return a masked version of a key for display (show last 4 chars only)."""
    if not plaintext or len(plaintext) < 8:
        return "****"
    return "sk-..." + plaintext[-4:]
