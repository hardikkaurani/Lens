import base64
import hashlib
import logging
import secrets
from typing import Optional, Union

from Crypto.Cipher import AES

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Fallback development key if TOKEN_ENCRYPTION_KEY is not set in environment
_DEV_FALLBACK_KEY = b"lens-dev-token-encryption-key-stage13-v1"


CIPHERTEXT_VERSION_PREFIX = "v1:"
APPLICATION_SALT = b"lens-token-encryption-salt-v1"
PBKDF2_ITERATIONS = 100_000


class EncryptionError(Exception):
    """Raised when token encryption or decryption fails."""
    pass


def _derive_key(key: Optional[Union[str, bytes]] = None) -> bytes:
    """Derive a 256-bit (32-byte) key for AES-256-GCM.

    Supports:
    1. 64-hex string representing a 32-byte raw cryptographic key.
    2. 32-byte raw bytes directly.
    3. Passphrase/string derived deterministically via PBKDF2-HMAC-SHA256 (100,000 iterations).

    In production (APP_ENV == 'production'), TOKEN_ENCRYPTION_KEY must be configured
    and cannot be empty or the dev fallback.
    """
    settings = get_settings()
    is_production = settings.APP_ENV == "production"

    if key is None:
        env_key = settings.TOKEN_ENCRYPTION_KEY
        if env_key and env_key.strip():
            raw_key: Union[str, bytes] = env_key.strip()
        else:
            if is_production:
                raise EncryptionError("TOKEN_ENCRYPTION_KEY must be configured in production environment.")
            raw_key = _DEV_FALLBACK_KEY
    else:
        raw_key = key

    # 1. Raw 32 bytes
    if isinstance(raw_key, bytes):
        if len(raw_key) == 32:
            return raw_key
        return hashlib.pbkdf2_hmac("sha256", raw_key, APPLICATION_SALT, PBKDF2_ITERATIONS)

    # 2. String input
    stripped = raw_key.strip()
    if len(stripped) == 64:
        try:
            raw_bytes = bytes.fromhex(stripped)
            if len(raw_bytes) == 32:
                return raw_bytes
        except ValueError:
            pass

    if is_production and len(stripped) < 32:
        raise EncryptionError("In production, TOKEN_ENCRYPTION_KEY must be at least 32 characters or a 64-char hex string.")

    # 3. Derive via PBKDF2-HMAC-SHA256
    return hashlib.pbkdf2_hmac("sha256", stripped.encode("utf-8"), APPLICATION_SALT, PBKDF2_ITERATIONS)


def encrypt_secret(plaintext: str, key: Optional[Union[str, bytes]] = None) -> str:
    """Encrypt a secret string using AES-256-GCM authenticated encryption.
    
    Returns versioned, URL-safe base64 string: 'v1:' + base64(nonce [12B] + tag [16B] + ciphertext).
    """
    if not plaintext:
        raise EncryptionError("Cannot encrypt empty plaintext.")

    try:
        key_bytes = _derive_key(key)
        nonce = secrets.token_bytes(12)
        cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
        payload = nonce + tag + ciphertext
        encoded = base64.urlsafe_b64encode(payload).decode("utf-8")
        return f"{CIPHERTEXT_VERSION_PREFIX}{encoded}"
    except Exception as e:
        if isinstance(e, EncryptionError):
            raise
        logger.error("Failed to encrypt token: %s", type(e).__name__)
        raise EncryptionError("Token encryption failed.") from None


def decrypt_secret(encrypted_text: str, key: Optional[Union[str, bytes]] = None) -> str:
    """Decrypt an AES-256-GCM encrypted secret.
    
    Verifies ciphertext integrity via authentication tag.
    Raises EncryptionError if decryption or MAC verification fails.
    """
    if not encrypted_text:
        raise EncryptionError("Cannot decrypt empty ciphertext.")

    try:
        raw = encrypted_text.strip()
        if raw.startswith(CIPHERTEXT_VERSION_PREFIX):
            raw = raw[len(CIPHERTEXT_VERSION_PREFIX):]

        payload = base64.urlsafe_b64decode(raw.encode("utf-8"))
        if len(payload) < 28:
            raise EncryptionError("Invalid ciphertext length.")

        nonce = payload[:12]
        tag = payload[12:28]
        ciphertext = payload[28:]

        key_bytes = _derive_key(key)
        cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
        plaintext_bytes = cipher.decrypt_and_verify(ciphertext, tag)
        return plaintext_bytes.decode("utf-8")
    except Exception as e:
        if isinstance(e, EncryptionError):
            raise
        logger.error("Failed to decrypt token: %s", type(e).__name__)
        raise EncryptionError("Token decryption failed: invalid ciphertext or MAC check failed.") from None
