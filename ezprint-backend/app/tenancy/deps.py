"""Tenancy and auth FastAPI dependencies.

The core invariant of the SaaS: every authenticated request resolves to a
single `tenant_id` and all downstream queries are filtered by it.

Four subject types are recognized, keyed on the JWT `typ` claim issued by
`app.core.security`:

    - "access"  -> shopkeeper (human) logged into the dashboard
    - "refresh" -> used only by /auth/refresh
    - "agent"   -> a Windows agent session, for REST + WS
    - "upload"  -> an anonymous customer inside a shop's upload flow

Handlers declare what they accept by picking the right dependency:

    any_tenant = Depends(require_tenant)           # any of the above
    shopkeeper = Depends(require_shopkeeper)       # access only
    agent      = Depends(require_agent)            # agent only
    customer   = Depends(require_customer_upload)  # upload token only
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import jwt
from fastapi import Depends, Header, HTTPException, Query, status

from app.core.security import decode_token


@dataclass
class Principal:
    """Resolved auth subject for the current request."""
    tenant_id: str
    subject_id: str            # user_id / agent_token_id / shop_slug
    role: str                  # shopkeeper | agent | customer
    token_type: str            # access | agent | upload
    raw_payload: dict


def _parse_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


def _principal_from_payload(payload: dict) -> Principal:
    tenant_id = payload.get("tid")
    subject = payload.get("sub") or payload.get("slug")
    if not tenant_id or not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing tenant or subject",
        )
    return Principal(
        tenant_id=str(tenant_id),
        subject_id=str(subject),
        role=str(payload.get("role", "")),
        token_type=str(payload.get("typ", "")),
        raw_payload=payload,
    )


def require_tenant(
    authorization: Optional[str] = Header(default=None),
    upload_token: Optional[str] = Query(default=None, alias="t"),
) -> Principal:
    """Accept ANY tenant-scoped token (access / agent / upload)."""
    token = _parse_bearer(authorization) or upload_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication"
        )
    try:
        payload = decode_token(token, expected_types={"access", "agent", "upload"})
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        )
    return _principal_from_payload(payload)


def require_shopkeeper(
    authorization: Optional[str] = Header(default=None),
) -> Principal:
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    try:
        payload = decode_token(token, expected_types={"access"})
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid token: {exc}"
        )
    return _principal_from_payload(payload)


def require_agent(
    authorization: Optional[str] = Header(default=None),
) -> Principal:
    token = _parse_bearer(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing agent bearer token"
        )
    try:
        payload = decode_token(token, expected_types={"agent"})
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid agent token: {exc}"
        )
    return _principal_from_payload(payload)


def require_customer_upload(
    upload_token: Optional[str] = Query(default=None, alias="t"),
    x_upload_token: Optional[str] = Header(default=None, alias="X-Upload-Token"),
) -> Principal:
    token = upload_token or x_upload_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing upload token"
        )
    try:
        payload = decode_token(token, expected_types={"upload"})
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid upload token: {exc}"
        )
    return _principal_from_payload(payload)


def require_shopkeeper_or_agent(
    principal: Principal = Depends(require_tenant),
) -> Principal:
    if principal.token_type not in {"access", "agent"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Operation requires shopkeeper or agent auth"
        )
    return principal
