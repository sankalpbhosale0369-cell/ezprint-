"""Password hashing + JWT issuance/verification.

Tokens are tagged by `typ`:
    - "access"   : short-lived shopkeeper session
    - "refresh"  : longer-lived shopkeeper refresh
    - "agent"    : Windows agent session (REST + WS)
    - "upload"   : per-shop anonymous customer upload scope
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

import bcrypt
import jwt

from app.core.config import settings

TokenType = Literal["access", "refresh", "agent", "upload"]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def generate_api_key(prefix: str = "ezp") -> str:
    """Long-lived agent provisioning token printed once to the shopkeeper."""
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def _encode(payload: Dict[str, Any]) -> str:
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_alg)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(
    tenant_id: str,
    user_id: str,
    role: str = "shopkeeper",
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    payload: Dict[str, Any] = {
        "typ": "access",
        "tid": tenant_id,
        "sub": user_id,
        "role": role,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=settings.jwt_access_ttl_minutes)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return _encode(payload)


def create_refresh_token(tenant_id: str, user_id: str) -> str:
    return _encode({
        "typ": "refresh",
        "tid": tenant_id,
        "sub": user_id,
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(days=settings.jwt_refresh_ttl_days)).timestamp()),
    })


def create_agent_session_token(tenant_id: str, agent_token_id: str) -> str:
    return _encode({
        "typ": "agent",
        "tid": tenant_id,
        "sub": agent_token_id,
        "role": "agent",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(hours=settings.agent_session_ttl_hours)).timestamp()),
    })


def create_upload_token(tenant_id: str, shop_slug: str) -> str:
    return _encode({
        "typ": "upload",
        "tid": tenant_id,
        "slug": shop_slug,
        "role": "customer",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + timedelta(minutes=settings.upload_token_ttl_minutes)).timestamp()),
    })


def decode_token(token: str, expected_types: Optional[set[TokenType]] = None) -> Dict[str, Any]:
    """Decode and validate a JWT. Raises jwt.PyJWTError on any problem."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_alg])
    if expected_types and payload.get("typ") not in expected_types:
        raise jwt.InvalidTokenError(f"Unexpected token type: {payload.get('typ')}")
    return payload
