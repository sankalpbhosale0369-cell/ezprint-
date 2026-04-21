"""Shop info + pricing endpoints.

All operations are scoped to the caller's tenant via `Principal.tenant_id`.
The `{tenant_id}` path segment is accepted for URL clarity but MUST match
the authenticated tenant or we return 404.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import models
from app.db.session import get_db
from app.schemas.shops import (
    PricingOut,
    PricingUpdate,
    ShopInfoOut,
    ShopInfoUpdate,
)
from app.tenancy.deps import Principal, require_shopkeeper, require_shopkeeper_or_agent

router = APIRouter()


def _assert_same_tenant(principal: Principal, tenant_id: str) -> None:
    if principal.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")


@router.get("/{tenant_id}/info", response_model=ShopInfoOut)
def get_shop_info(
    tenant_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> ShopInfoOut:
    _assert_same_tenant(principal, tenant_id)
    tenant = db.get(models.Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")
    shopkeeper = db.scalars(
        select(models.Shopkeeper).where(models.Shopkeeper.tenant_id == tenant.id)
    ).first()
    if not shopkeeper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shopkeeper not found")
    return ShopInfoOut(
        tenant_id=tenant.id,
        shop_id=shopkeeper.shop_id,
        slug=tenant.slug,
        shop_name=shopkeeper.shop_name,
        shop_address=shopkeeper.shop_address,
        contact_number=shopkeeper.contact_number,
        shopkeeper_name=shopkeeper.shopkeeper_name,
        email=shopkeeper.email,
        qr_code_path=shopkeeper.qr_code_path,
        is_active=shopkeeper.is_active,
        created_at=shopkeeper.created_at,
    )


@router.put("/{tenant_id}/info", response_model=ShopInfoOut)
def update_shop_info(
    tenant_id: str,
    payload: ShopInfoUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper),
) -> ShopInfoOut:
    _assert_same_tenant(principal, tenant_id)
    shopkeeper = db.scalars(
        select(models.Shopkeeper).where(models.Shopkeeper.tenant_id == tenant_id)
    ).first()
    if not shopkeeper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shopkeeper not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(shopkeeper, field, value)
    db.commit()
    db.refresh(shopkeeper)

    tenant = db.get(models.Tenant, tenant_id)
    return ShopInfoOut(
        tenant_id=tenant.id,
        shop_id=shopkeeper.shop_id,
        slug=tenant.slug,
        shop_name=shopkeeper.shop_name,
        shop_address=shopkeeper.shop_address,
        contact_number=shopkeeper.contact_number,
        shopkeeper_name=shopkeeper.shopkeeper_name,
        email=shopkeeper.email,
        qr_code_path=shopkeeper.qr_code_path,
        is_active=shopkeeper.is_active,
        created_at=shopkeeper.created_at,
    )


def _get_or_create_pricing(db: Session, tenant_id: str) -> models.ShopPricing:
    pricing = db.scalars(
        select(models.ShopPricing).where(models.ShopPricing.tenant_id == tenant_id)
    ).first()
    if pricing:
        return pricing
    pricing = models.ShopPricing(tenant_id=tenant_id)
    db.add(pricing)
    db.commit()
    db.refresh(pricing)
    return pricing


@router.get("/{tenant_id}/pricing", response_model=PricingOut)
def get_pricing(
    tenant_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper_or_agent),
) -> PricingOut:
    _assert_same_tenant(principal, tenant_id)
    pricing = _get_or_create_pricing(db, tenant_id)
    return PricingOut(
        tenant_id=pricing.tenant_id,
        bw_single=pricing.bw_single,
        bw_double=pricing.bw_double,
        color_single=pricing.color_single,
        color_double=pricing.color_double,
        updated_at=pricing.updated_at,
    )


@router.put("/{tenant_id}/pricing", response_model=PricingOut)
def update_pricing(
    tenant_id: str,
    payload: PricingUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_shopkeeper),
) -> PricingOut:
    _assert_same_tenant(principal, tenant_id)
    pricing = _get_or_create_pricing(db, tenant_id)
    pricing.bw_single = payload.bw_single
    pricing.bw_double = payload.bw_double
    pricing.color_single = payload.color_single
    pricing.color_double = payload.color_double
    db.commit()
    db.refresh(pricing)
    return PricingOut(
        tenant_id=pricing.tenant_id,
        bw_single=pricing.bw_single,
        bw_double=pricing.bw_double,
        color_single=pricing.color_single,
        color_double=pricing.color_double,
        updated_at=pricing.updated_at,
    )
