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


class EncryptionError(Exception):
    """Raised when token encryption or decryption fails."""
    pass


def _derive_key(key: Optional[Union[str, bytes]] = None) -> bytes:
    """Derive a 256-bit (32-byte) key deterministically using SHA-256."""
    if key is None:
        settings = get_settings()
        env_key = settings.TOKEN_ENCRYPTION_KEY
        if env_key and env_key.strip():
            raw = env_key.strip().encode("utf-8")
        else:
            raw = _DEV_FALLBACK_KEY
    elif isinstance(key, str):
        raw = key.encode("utf-8")
    else:
        raw = key

    return hashlib.sha256(raw).digest()


def encrypt_secret(plaintext: str, key: Optional[Union[str, bytes]] = None) -> str:
    """Encrypt a secret string using AES-256-GCM authenticated encryption.
    
    Returns URL-safe base64 string encoding: nonce (12 bytes) + tag (16 bytes) + ciphertext.
    """
    if not plaintext:
        raise EncryptionError("Cannot encrypt empty plaintext.")

    try:
        key_bytes = _derive_key(key)
        nonce = secrets.token_bytes(12)
        cipher = AES.new(key_bytes, AES.MODE_GCM, nonce=nonce)
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
        payload = nonce + tag + ciphertext
        return base64.urlsafe_b64encode(payload).decode("utf-8")
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
        payload = base64.urlsafe_b64decode(encrypted_text.encode("utf-8"))
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
        raise EncryptionError("Token decryption failed.") from None
