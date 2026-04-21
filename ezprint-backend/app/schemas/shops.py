from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ShopInfoOut(BaseModel):
    tenant_id: str
    shop_id: str
    slug: str
    shop_name: str
    shop_address: Optional[str] = None
    contact_number: Optional[str] = None
    shopkeeper_name: Optional[str] = None
    email: EmailStr
    qr_code_path: Optional[str] = None
    is_active: bool
    created_at: datetime


class ShopInfoUpdate(BaseModel):
    shop_name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    shop_address: Optional[str] = Field(default=None, max_length=255)
    contact_number: Optional[str] = Field(default=None, max_length=40)
    shopkeeper_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[EmailStr] = None


class PricingOut(BaseModel):
    tenant_id: str
    bw_single: float
    bw_double: float
    color_single: float
    color_double: float
    updated_at: datetime


class PricingUpdate(BaseModel):
    bw_single: float = Field(ge=0)
    bw_double: float = Field(ge=0)
    color_single: float = Field(ge=0)
    color_double: float = Field(ge=0)
