"""Minimal super-admin surface.

This is NOT a full admin console — just enough REST to create a new tenant
+ first shopkeeper and to mint an agent provisioning token.

Protected by a simple shared `X-Admin-Token` header comparing against the
`JWT_SECRET` env var (rotate = redeploy). A proper admin UI/role system is
deferred per the plan's "out of scope" section.
"""
from __future__ import annotations

import secrets
from typing import Annotated

import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_api_key, hash_password
from app.db import models
from app.db.session import get_db
from app.schemas.auth import (
    RegisterShopkeeperRequest,
    RegisterShopkeeperResponse,
)
from app.services.storage import storage

router = APIRouter()


def _require_admin(x_admin_token: Annotated[str | None, Header()] = None) -> None:
    # constant-time compare
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.jwt_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin auth required")


@router.post(
    "/tenants",
    response_model=RegisterShopkeeperResponse,
    dependencies=[Depends(_require_admin)],
)
def register_tenant(payload: RegisterShopkeeperRequest, db: Session = Depends(get_db)) -> RegisterShopkeeperResponse:
    existing = db.scalars(
        select(models.Tenant).where(models.Tenant.slug == payload.slug)
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Slug already in use")

    tenant = models.Tenant(slug=payload.slug, name=payload.shop_name, status="active")
    db.add(tenant)
    db.flush()

    shopkeeper = models.Shopkeeper(
        tenant_id=tenant.id,
        username=payload.username,
        email=payload.email,
        password_hash=hash_password(payload.password),
        shop_name=payload.shop_name,
        shopkeeper_name=payload.shopkeeper_name,
    )
    db.add(shopkeeper)

    pricing = models.ShopPricing(tenant_id=tenant.id)
    db.add(pricing)

    raw_token = generate_api_key()
    token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    agent_token = models.AgentToken(
        tenant_id=tenant.id, token_hash=token_hash, label="initial"
    )
    db.add(agent_token)

    db.commit()
    db.refresh(tenant)
    db.refresh(shopkeeper)

    try:
        storage.ensure_tenant_prefix(tenant.id)
    except Exception:
        # Non-fatal — the first upload will create the prefix implicitly.
        pass

    return RegisterShopkeeperResponse(
        tenant_id=tenant.id,
        shop_id=shopkeeper.shop_id,
        slug=tenant.slug,
        shop_name=shopkeeper.shop_name,
        username=shopkeeper.username,
        agent_provisioning_token=raw_token,
    )


@router.post(
    "/tenants/{tenant_id}/agent-tokens",
    response_model=RegisterShopkeeperResponse,
    dependencies=[Depends(_require_admin)],
)
def rotate_agent_token(tenant_id: str, db: Session = Depends(get_db)) -> RegisterShopkeeperResponse:
    tenant = db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    raw_token = generate_api_key()
    token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
    db.add(models.AgentToken(tenant_id=tenant.id, token_hash=token_hash, label="rotated"))
    db.commit()

    shopkeeper = db.scalars(
        select(models.Shopkeeper).where(models.Shopkeeper.tenant_id == tenant.id)
    ).first()
    return RegisterShopkeeperResponse(
        tenant_id=tenant.id,
        shop_id=shopkeeper.shop_id if shopkeeper else "",
        slug=tenant.slug,
        shop_name=tenant.name,
        username=shopkeeper.username if shopkeeper else "",
        agent_provisioning_token=raw_token,
    )
