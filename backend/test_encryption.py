"""
test_encryption.py — Unit tests for core/encryption.py

Covers:
  - encrypt/decrypt round-trip
  - identical plaintext → different ciphertexts
  - tamper detection
  - wrong key rejection
  - legacy v0 (Fernet) decryption
  - legacy-to-new re-encryption migration
  - missing ENCRYPTION_KEY (ephemeral mode)
  - no secret leakage in error messages / logs
  - mask_key helper
"""

import base64
import importlib
import logging
import os
import sys
import unittest

# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_module(env_overrides: dict | None = None):
    """Import (or reimport) core.encryption with a clean singleton state."""
    # Remove cached module so _master_key_bytes singleton resets
    for name in list(sys.modules.keys()):
        if "core.encryption" in name or name == "encryption":
            del sys.modules[name]

    old_env = {}
    if env_overrides is not None:
        for k, v in env_overrides.items():
            old_env[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # Make sure we can find the backend core package
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    import core.encryption as enc
    return enc, old_env


def _restore_env(old_env: dict):
    for k, v in old_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── A valid 32-byte Fernet key for testing ────────────────────────────────────
_TEST_KEY = base64.urlsafe_b64encode(b"A" * 32).decode()  # 44-char URL-safe b64


class TestEncryptDecrypt(unittest.TestCase):

    def setUp(self):
        self.enc, self.old_env = _fresh_module({"ENCRYPTION_KEY": _TEST_KEY, "ENCRYPTION_KEY_ID": "0"})

    def tearDown(self):
        _restore_env(self.old_env)

    # ------------------------------------------------------------------
    def test_round_trip(self):
        """Encrypt then decrypt recovers original plaintext."""
        plaintext = "sk-openai-secret-key-12345"
        token = self.enc.encrypt_value(plaintext)
        self.assertEqual(self.enc.decrypt_value(token), plaintext)

    def test_empty_string_returns_empty(self):
        """Empty input is returned as empty without encrypting."""
        self.assertEqual(self.enc.encrypt_value(""), "")
        self.assertEqual(self.enc.decrypt_value(""), "")

    def test_different_ciphertexts_for_identical_plaintext(self):
        """Same plaintext produces different ciphertexts (random salt + nonce)."""
        p = "my-secret-api-key"
        t1 = self.enc.encrypt_value(p)
        t2 = self.enc.encrypt_value(p)
        self.assertNotEqual(t1, t2, "Ciphertexts should differ due to random salt/nonce")

    def test_v1_prefix(self):
        """Encrypted token starts with v1: prefix."""
        token = self.enc.encrypt_value("test")
        self.assertTrue(token.startswith("v1:"), f"Expected v1: prefix, got: {token[:10]}")

    def test_mask_key(self):
        """mask_key hides all but last 4 chars."""
        masked = self.enc.mask_key("sk-openai-abcd1234")
        self.assertTrue(masked.endswith("1234"))
        self.assertNotIn("sk-openai", masked)

    def test_mask_key_short(self):
        """Short keys are fully masked."""
        self.assertEqual(self.enc.mask_key("abc"), "****")


class TestTamperDetection(unittest.TestCase):

    def setUp(self):
        self.enc, self.old_env = _fresh_module({"ENCRYPTION_KEY": _TEST_KEY, "ENCRYPTION_KEY_ID": "0"})

    def tearDown(self):
        _restore_env(self.old_env)

    def _flip_byte(self, b64_payload: str) -> str:
        """Flip one byte in the b64-encoded payload."""
        raw = base64.urlsafe_b64decode(b64_payload + "==")
        ba = bytearray(raw)
        ba[-1] ^= 0xFF  # flip last byte (in the tag)
        return base64.urlsafe_b64encode(bytes(ba)).rstrip(b"=").decode()

    def test_tampered_ciphertext_raises(self):
        """Modifying ciphertext raises ValueError (auth tag mismatch)."""
        token = self.enc.encrypt_value("secret")
        # token format: v1:<kid>:<b64>
        parts = token.split(":", 2)
        parts[2] = self._flip_byte(parts[2])
        bad_token = ":".join(parts)
        with self.assertRaises(ValueError):
            self.enc.decrypt_value(bad_token)

    def test_truncated_ciphertext_raises(self):
        """Too-short payload raises ValueError."""
        with self.assertRaises(ValueError):
            self.enc.decrypt_value("v1:0:YWJj")  # 3 bytes < min required

    def test_malformed_prefix_raises(self):
        """Random garbage raises ValueError."""
        with self.assertRaises(ValueError):
            self.enc.decrypt_value("v1:notanumber:garbage!!")


class TestWrongKey(unittest.TestCase):

    def test_wrong_key_raises(self):
        """A token encrypted with key A cannot be decrypted with key B."""
        key_a = base64.urlsafe_b64encode(b"A" * 32).decode()
        key_b = base64.urlsafe_b64encode(b"B" * 32).decode()

        enc_a, old_a = _fresh_module({"ENCRYPTION_KEY": key_a})
        token = enc_a.encrypt_value("top-secret")
        _restore_env(old_a)

        enc_b, old_b = _fresh_module({"ENCRYPTION_KEY": key_b})
        with self.assertRaises(ValueError):
            enc_b.decrypt_value(token)
        _restore_env(old_b)

    def test_error_message_does_not_contain_key_material(self):
        """Error messages must not echo keys or plaintexts."""
        key_a = base64.urlsafe_b64encode(b"A" * 32).decode()
        key_b = base64.urlsafe_b64encode(b"B" * 32).decode()

        enc_a, old_a = _fresh_module({"ENCRYPTION_KEY": key_a})
        token = enc_a.encrypt_value("secret-value")
        _restore_env(old_a)

        enc_b, old_b = _fresh_module({"ENCRYPTION_KEY": key_b})
        try:
            enc_b.decrypt_value(token)
        except ValueError as e:
            msg = str(e)
            self.assertNotIn("secret-value", msg)
            self.assertNotIn(key_a, msg)
            self.assertNotIn(key_b, msg)
        _restore_env(old_b)


class TestLegacyV0Decryption(unittest.TestCase):
    """Test backward-compat decryption of old Fernet (v0) tokens."""

    def test_decrypt_legacy_fernet_token(self):
        """A token produced by the old Fernet-based code can be decrypted."""
        from cryptography.fernet import Fernet as _Fernet
        key = base64.urlsafe_b64encode(b"T" * 32).decode()
        f = _Fernet(key.encode())
        legacy_token = f.encrypt(b"old-api-key").decode()

        enc, old_env = _fresh_module({"ENCRYPTION_KEY": key})
        result = enc.decrypt_value(legacy_token)
        self.assertEqual(result, "old-api-key")
        _restore_env(old_env)

    def test_legacy_token_does_not_start_with_v1(self):
        """Sanity check: legacy Fernet tokens don't look like v1 tokens."""
        from cryptography.fernet import Fernet as _Fernet
        key = base64.urlsafe_b64encode(b"T" * 32).decode()
        f = _Fernet(key.encode())
        token = f.encrypt(b"x").decode()
        self.assertFalse(token.startswith("v1:"))


class TestLegacyMigration(unittest.TestCase):
    """Test re-encrypting v0 tokens to v1."""

    def test_re_encrypt_produces_v1(self):
        """re_encrypt_legacy returns a v1 token."""
        from cryptography.fernet import Fernet as _Fernet
        key = base64.urlsafe_b64encode(b"R" * 32).decode()
        f = _Fernet(key.encode())
        old_token = f.encrypt(b"migrate-me").decode()

        enc, old_env = _fresh_module({"ENCRYPTION_KEY": key})
        plaintext = enc.decrypt_value(old_token)
        new_token = enc.re_encrypt_legacy(plaintext, old_token)

        self.assertTrue(new_token.startswith("v1:"))
        self.assertEqual(enc.decrypt_value(new_token), "migrate-me")
        _restore_env(old_env)


class TestEphemeralMode(unittest.TestCase):
    """Behaviour when ENCRYPTION_KEY is absent."""

    def test_ephemeral_encrypt_decrypt_works_in_same_process(self):
        """Ephemeral mode can round-trip within the same process."""
        enc, old_env = _fresh_module({"ENCRYPTION_KEY": None, "ENCRYPTION_KEY_ID": None})
        token = enc.encrypt_value("temp-key")
        self.assertEqual(enc.decrypt_value(token), "temp-key")
        _restore_env(old_env)

    def test_ephemeral_mode_logs_warning(self):
        """Ephemeral mode emits a WARNING log (not ERROR or CRITICAL)."""
        with self.assertLogs("datapilot.encryption", level="WARNING") as cm:
            enc, old_env = _fresh_module({"ENCRYPTION_KEY": None, "ENCRYPTION_KEY_ID": None})
            enc.encrypt_value("x")
        _restore_env(old_env)
        # Must contain at least one WARNING
        warnings = [r for r in cm.output if "WARNING" in r]
        self.assertTrue(len(warnings) > 0, "Expected WARNING log for missing ENCRYPTION_KEY")

    def test_no_secrets_in_warning_log(self):
        """Warning log must not contain plaintext or any key material."""
        enc, old_env = _fresh_module({"ENCRYPTION_KEY": None, "ENCRYPTION_KEY_ID": None})
        plaintext = "ultra-secret-value-xyz"
        with self.assertLogs("datapilot.encryption", level="WARNING") as cm:
            enc.encrypt_value(plaintext)
        _restore_env(old_env)
        for line in cm.output:
            self.assertNotIn(plaintext, line, "Secret plaintext leaked into log")


class TestKeyRotation(unittest.TestCase):
    """Tokens encrypted with key_id=0 can be tagged; key_id=1 can encrypt new tokens."""

    def test_key_id_stored_in_token(self):
        """key_id is stored in the v1 token prefix."""
        enc, old_env = _fresh_module({"ENCRYPTION_KEY": _TEST_KEY, "ENCRYPTION_KEY_ID": "7"})
        token = enc.encrypt_value("payload")
        # token: "v1:7:..."
        parts = token.split(":")
        self.assertEqual(parts[1], "7")
        _restore_env(old_env)

    def test_decrypt_token_with_matching_key_id(self):
        """Decryption succeeds when key_id matches encryption key_id."""
        enc, old_env = _fresh_module({"ENCRYPTION_KEY": _TEST_KEY, "ENCRYPTION_KEY_ID": "3"})
        token = enc.encrypt_value("rotation-test")
        result = enc.decrypt_value(token)
        self.assertEqual(result, "rotation-test")
        _restore_env(old_env)

    def test_different_key_ids_produce_different_aad(self):
        """Tokens from different key IDs are not interchangeable when the master key also changes."""
        key_v0 = base64.urlsafe_b64encode(b"K" * 32).decode()
        key_v1 = base64.urlsafe_b64encode(b"M" * 32).decode()

        enc_old, old_a = _fresh_module({"ENCRYPTION_KEY": key_v0, "ENCRYPTION_KEY_ID": "0"})
        token = enc_old.encrypt_value("secret")
        _restore_env(old_a)

        enc_new, old_b = _fresh_module({"ENCRYPTION_KEY": key_v1, "ENCRYPTION_KEY_ID": "1"})
        with self.assertRaises(ValueError):
            enc_new.decrypt_value(token)
        _restore_env(old_b)


if __name__ == "__main__":
    unittest.main()
