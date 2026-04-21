"""Authentication endpoints for shopkeepers, agents, and customer upload tokens."""
from __future__ import annotations

from datetime import datetime

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_agent_session_token,
    create_refresh_token,
    create_upload_token,
    decode_token,
    verify_password,
)
from app.db import models
from app.db.session import get_db
from app.schemas.auth import (
    AgentSessionResponse,
    AgentTokenExchangeRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    TokenResponse,
    UploadTokenResponse,
)
from app.tenancy.deps import Principal, require_shopkeeper

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    # Username OR email login for convenience.
    stmt = select(models.Shopkeeper).where(
        (models.Shopkeeper.username == payload.username)
        | (models.Shopkeeper.email == payload.username)
    )
    user = db.scalars(stmt).first()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )
    access = create_access_token(user.tenant_id, user.shop_id, role="shopkeeper")
    refresh = create_refresh_token(user.tenant_id, user.shop_id)
    return LoginResponse(
        access_token=access,
        refresh_token=refresh,
        tenant_id=user.tenant_id,
        shop_id=user.shop_id,
        shop_name=user.shop_name,
        username=user.username,
        email=user.email,
        shopkeeper_name=user.shopkeeper_name,
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_access(payload: RefreshRequest) -> TokenResponse:
    try:
        claims = decode_token(payload.refresh_token, expected_types={"refresh"})
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=f"Invalid refresh token: {exc}"
        )
    access = create_access_token(claims["tid"], claims["sub"], role="shopkeeper")
    return TokenResponse(access_token=access)


@router.post("/logout")
def logout(principal: Principal = Depends(require_shopkeeper)) -> dict:
    # Stateless JWTs; clients simply drop tokens. Kept for API symmetry and
    # so we can add a revocation list later without a breaking change.
    return {"success": True, "tenant_id": principal.tenant_id}


@router.post("/agent/session", response_model=AgentSessionResponse)
def agent_session(
    payload: AgentTokenExchangeRequest, db: Session = Depends(get_db)
) -> AgentSessionResponse:
    """Trade a long-lived provisioning token for a short-lived agent JWT."""
    # We never query by the raw token; compare via bcrypt.
    raw = payload.provisioning_token.encode("utf-8")
    tokens = db.scalars(
        select(models.AgentToken).where(models.AgentToken.revoked_at.is_(None))
    ).all()
    match: models.AgentToken | None = None
    for t in tokens:
        try:
            if bcrypt.checkpw(raw, t.token_hash.encode("utf-8")):
                match = t
                break
        except ValueError:
            continue
    if not match:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid provisioning token"
        )
    match.last_used_at = datetime.utcnow()
    db.add(match)
    db.commit()

    token = create_agent_session_token(match.tenant_id, match.id)
    return AgentSessionResponse(
        access_token=token,
        tenant_id=match.tenant_id,
        expires_in=settings.agent_session_ttl_hours * 3600,
    )


@router.post("/agent/from-session", response_model=AgentSessionResponse)
def agent_from_session(
    principal: Principal = Depends(require_shopkeeper),
) -> AgentSessionResponse:
    """Mint an agent JWT for an already-logged-in shopkeeper.

    Used by the desktop .exe: the shopkeeper signs in with username/password
    (access+refresh), and the client then calls this endpoint to obtain the
    separate `typ=agent` token it needs for `/ws/agent` and presigned file
    downloads. Avoids pushing every shopkeeper through the provisioning-token
    flow (which is reserved for headless/bulk deployments).
    """
    token = create_agent_session_token(principal.tenant_id, principal.subject_id)
    return AgentSessionResponse(
        access_token=token,
        tenant_id=principal.tenant_id,
        expires_in=settings.agent_session_ttl_hours * 3600,
    )


@router.get("/upload/{shop_slug}", response_model=UploadTokenResponse)
def upload_token_for_shop(shop_slug: str, db: Session = Depends(get_db)) -> UploadTokenResponse:
    """Anonymous endpoint used by the customer web uploader / QR code landing.

    A customer scans the shop QR code, which points at a URL embedding the
    slug; the frontend calls here to mint a short-lived upload token
    scoped to that tenant only.
    """
    tenant = db.scalars(
        select(models.Tenant).where(
            models.Tenant.slug == shop_slug, models.Tenant.status == "active"
        )
    ).first()
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shop not found")
    shopkeeper = db.scalars(
        select(models.Shopkeeper).where(models.Shopkeeper.tenant_id == tenant.id)
    ).first()
    token = create_upload_token(tenant.id, tenant.slug)
    return UploadTokenResponse(
        upload_token=token,
        tenant_id=tenant.id,
        shop_slug=tenant.slug,
        shop_name=shopkeeper.shop_name if shopkeeper else tenant.name,
        expires_in=settings.upload_token_ttl_minutes * 60,
    )
