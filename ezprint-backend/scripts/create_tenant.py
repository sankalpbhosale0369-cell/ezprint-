"""CLI helper to create a tenant + first shopkeeper + agent token.

Usage (inside the api container):

    docker compose exec api python -m scripts.create_tenant \
        --slug demo-shop --name "Demo Print Shop" \
        --username demo --email demo@example.com --password 'change-me'

Outputs a JSON blob including the one-time agent provisioning token.
"""
from __future__ import annotations

import argparse
import json
import sys

import bcrypt

from app.core.security import generate_api_key, hash_password
from app.db import models
from app.db.session import SessionLocal
from app.services.storage import storage


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--slug", required=True)
    p.add_argument("--name", required=True, help="Shop display name")
    p.add_argument("--username", required=True)
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--shopkeeper-name", default=None)
    args = p.parse_args()

    db = SessionLocal()
    try:
        existing = db.query(models.Tenant).filter_by(slug=args.slug).first()
        if existing:
            print(f"ERROR: slug '{args.slug}' already exists (tenant_id={existing.id})", file=sys.stderr)
            return 2

        tenant = models.Tenant(slug=args.slug, name=args.name, status="active")
        db.add(tenant)
        db.flush()

        shopkeeper = models.Shopkeeper(
            tenant_id=tenant.id,
            username=args.username,
            email=args.email,
            password_hash=hash_password(args.password),
            shop_name=args.name,
            shopkeeper_name=args.shopkeeper_name,
        )
        db.add(shopkeeper)

        db.add(models.ShopPricing(tenant_id=tenant.id))

        raw_token = generate_api_key()
        token_hash = bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")
        db.add(models.AgentToken(tenant_id=tenant.id, token_hash=token_hash, label="cli-initial"))

        db.commit()
    finally:
        db.close()

    try:
        storage.ensure_tenant_prefix(tenant.id)
    except Exception as exc:  # noqa: BLE001
        print(f"WARNING: could not create tenant prefix in MinIO: {exc}", file=sys.stderr)

    print(json.dumps(
        {
            "tenant_id": tenant.id,
            "slug": tenant.slug,
            "shop_id": shopkeeper.shop_id,
            "username": shopkeeper.username,
            "agent_provisioning_token": raw_token,
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
