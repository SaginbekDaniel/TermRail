"""Encryption at rest for Telegram message bodies (Fernet = AES-128-CBC + HMAC-SHA256).

TELEGRAM_DATA_KEY may hold several comma-separated keys: the first encrypts, all decrypt, so keys can be
rotated without downtime. Plaintext never leaves this module except to the analysis pipeline and to an
authorized reader of the evidence.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings
from app.core.errors import ServiceUnavailable


@lru_cache(maxsize=4)
def _fernet(keys: str) -> MultiFernet:
    parts = [k.strip() for k in keys.split(",") if k.strip()]
    if not parts:
        raise ServiceUnavailable("Telegram data key is not configured", code="TELEGRAM_NOT_CONFIGURED")
    return MultiFernet([Fernet(k.encode()) for k in parts])


def encrypt(text: str) -> bytes:
    return _fernet(get_settings().telegram_data_key).encrypt(text.encode("utf-8"))


def decrypt(token: bytes) -> str | None:
    """None when the ciphertext cannot be read (wrong/rotated-out key); callers treat it as unavailable."""
    try:
        return _fernet(get_settings().telegram_data_key).decrypt(bytes(token)).decode("utf-8")
    except InvalidToken:
        return None


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
