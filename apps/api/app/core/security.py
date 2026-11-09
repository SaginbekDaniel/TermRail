"""Password hashing and access-token verification for local and Supabase auth modes."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import Settings, get_settings
from app.core.errors import Unauthorized

_hasher = PasswordHasher()

LOCAL_ISSUER = "termrail"
LOCAL_AUDIENCE = "termrail-api"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, settings: Settings | None = None) -> tuple[str, int]:
    settings = settings or get_settings()
    now = int(time.time())
    exp = now + settings.jwt_ttl_minutes * 60
    token = jwt.encode(
        {"sub": str(user_id), "iss": LOCAL_ISSUER, "aud": LOCAL_AUDIENCE, "iat": now, "exp": exp},
        settings.effective_jwt_secret,
        algorithm="HS256",
    )
    return token, exp


@dataclass(frozen=True)
class VerifiedIdentity:
    provider: str  # "local" | "supabase"
    subject: str
    email: str | None


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, cache_keys=True, lifespan=3600)


def verify_access_token(token: str, settings: Settings | None = None) -> VerifiedIdentity:
    settings = settings or get_settings()
    try:
        if settings.auth_provider == "local":
            claims = jwt.decode(
                token,
                settings.effective_jwt_secret,
                algorithms=["HS256"],
                audience=LOCAL_AUDIENCE,
                issuer=LOCAL_ISSUER,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
            return VerifiedIdentity("local", str(claims["sub"]), None)
        signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1" if settings.supabase_url else None
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=settings.supabase_jwt_audience,
            issuer=issuer,
            options={"require": ["exp", "sub", "aud"], "verify_iss": issuer is not None},
        )
        return VerifiedIdentity("supabase", str(claims["sub"]), claims.get("email"))
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Session expired", code="TOKEN_EXPIRED") from exc
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise Unauthorized("Invalid access token", code="INVALID_TOKEN") from exc
