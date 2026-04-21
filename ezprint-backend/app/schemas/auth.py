from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    tenant_id: str
    shop_id: str
    shop_name: str
    username: str
    email: str
    shopkeeper_name: Optional[str] = None


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AgentTokenExchangeRequest(BaseModel):
    provisioning_token: str = Field(min_length=8, max_length=255)


class AgentSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    tenant_id: str
    expires_in: int


class UploadTokenResponse(BaseModel):
    upload_token: str
    tenant_id: str
    shop_slug: str
    shop_name: str
    expires_in: int


class RegisterShopkeeperRequest(BaseModel):
    """Admin-only path to create a tenant + first shopkeeper user."""
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-_]+$")
    shop_name: str = Field(min_length=1, max_length=120)
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=255)
    shopkeeper_name: Optional[str] = None


class RegisterShopkeeperResponse(BaseModel):
    tenant_id: str
    shop_id: str
    slug: str
    shop_name: str
    username: str
    # Shown exactly once to the operator; the Windows agent uses it to
    # bootstrap a session at runtime.
    agent_provisioning_token: str
