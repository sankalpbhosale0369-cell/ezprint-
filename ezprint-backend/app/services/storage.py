"""MinIO / S3 storage service with strict per-tenant prefixing.

Layout inside the single `ezprint` bucket::

    tenants/{tenant_id}/jobs/{job_id}/original/{filename}
    tenants/{tenant_id}/jobs/{job_id}/print/{job_id}.pdf
    tenants/{tenant_id}/jobs/{job_id}/previews/page-{n}.jpg
    _system/qr/{tenant_id}.png

EVERY caller MUST pass `tenant_id`. The service enforces at runtime that
generated object keys begin with the tenant's prefix, raising if not — this
is the last line of defense against a tenancy bug leaking data across shops.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Optional
from urllib.parse import urlparse, urlunparse

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)

_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


def _sanitize_filename(name: str) -> str:
    """Strip path separators / control chars. Keeps dots for extensions."""
    clean = _SAFE_FILENAME.sub("_", PurePosixPath(name).name.strip())
    return clean or "file"


@dataclass(frozen=True)
class PresignedUpload:
    url: str
    object_key: str
    expires_in: int
    method: str = "PUT"


class TenantScopeViolation(RuntimeError):
    """Raised when code attempts to touch a key outside its tenant prefix."""


def _split_public_endpoint(raw: str) -> tuple[str, str]:
    """Split a configured public endpoint into a bare ``scheme://host`` part
    and an optional path prefix.

    This exists because some single-host deploys expose MinIO under a path
    prefix on the same Caddy (e.g. ``https://host.example/s3``), and that
    proxy then strips the prefix before forwarding to MinIO. SigV4 signs the
    CanonicalURI as-issued, so we MUST build the boto3 client against the
    bare host (``https://host.example``) to match what MinIO actually sees
    after stripping. The prefix is re-injected into the returned URL, in a
    way that does not change the signature.
    """
    if not raw:
        return raw, ""
    p = urlparse(raw)
    scheme = p.scheme or "http"
    netloc = p.netloc or p.path  # tolerate values missing scheme
    if not p.netloc:
        # urlparse puts "host:port" into .path when scheme is absent
        return raw, ""
    prefix = (p.path or "").rstrip("/")
    bare = f"{scheme}://{netloc}"
    return bare, prefix


class StorageService:
    """Thin wrapper around boto3 with per-tenant enforcement."""

    def __init__(self) -> None:
        self._internal_endpoint = settings.s3_endpoint
        raw_public = settings.s3_public_endpoint or settings.s3_endpoint
        self._public_endpoint, self._public_url_prefix = _split_public_endpoint(raw_public)
        self._bucket = settings.s3_bucket_name
        self._region = settings.s3_region

    # ------------------------------------------------------------------ clients
    def _make_client(self, endpoint_url: str):
        return self._make_client_with_creds(endpoint_url, settings.s3_access_key, settings.s3_secret_key)

    def _make_client_with_creds(self, endpoint_url: str, access_key: str, secret_key: str):
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=self._region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                # Disable automatic CRC32 checksums added by botocore 1.35+;
                # MinIO AGPL does not implement the flexible-checksum S3 extension.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    @property
    def internal_client(self):
        """Client used for server-side ops (inside the docker network)."""
        if not hasattr(self, "_internal_client"):
            self._internal_client = self._make_client(self._internal_endpoint)
        return self._internal_client

    @property
    def public_client(self):
        """Client used ONLY to sign URLs that browsers/agents will hit."""
        if not hasattr(self, "_public_client"):
            self._public_client = self._make_client(self._public_endpoint)
        return self._public_client

    @property
    def bucket(self) -> str:
        return self._bucket

    # --------------------------------------------------------------- key helpers
    @staticmethod
    def tenant_prefix(tenant_id: str) -> str:
        return f"tenants/{tenant_id}/"

    @staticmethod
    def job_prefix(tenant_id: str, job_id: str) -> str:
        return f"tenants/{tenant_id}/jobs/{job_id}/"

    @classmethod
    def original_key(cls, tenant_id: str, job_id: str, filename: str) -> str:
        return f"{cls.job_prefix(tenant_id, job_id)}original/{_sanitize_filename(filename)}"

    @classmethod
    def print_key(cls, tenant_id: str, job_id: str) -> str:
        return f"{cls.job_prefix(tenant_id, job_id)}print/{job_id}.pdf"

    @classmethod
    def preview_key(cls, tenant_id: str, job_id: str, page: int) -> str:
        return f"{cls.job_prefix(tenant_id, job_id)}previews/page-{page}.jpg"

    @staticmethod
    def qr_key(tenant_id: str) -> str:
        return f"_system/qr/{tenant_id}.png"

    # ---------------------------------------------------------------- guardrail
    def _assert_tenant_scope(self, key: str, tenant_id: str) -> None:
        expected = self.tenant_prefix(tenant_id)
        if not key.startswith(expected):
            logger.error("tenant scope violation: key=%s tenant=%s", key, tenant_id)
            raise TenantScopeViolation(
                f"Key {key!r} is outside tenant {tenant_id!r} prefix"
            )

    # -------------------------------------------------------------------- lifecycle
    def ensure_bucket(self) -> None:
        """Create the bucket if missing, then apply CORS so browsers can PUT directly."""
        try:
            self.internal_client.head_bucket(Bucket=self._bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code not in {"404", "NoSuchBucket", "NotFound"}:
                raise
            logger.info("creating bucket %s", self._bucket)
            self.internal_client.create_bucket(Bucket=self._bucket)

        # Allow browsers (customer upload page) to PUT files directly to presigned URLs.
        # PutBucketCors requires root/admin credentials; use them if provided.
        try:
            if settings.minio_root_user and settings.minio_root_password:
                admin_client = self._make_client_with_creds(
                    self._internal_endpoint, settings.minio_root_user, settings.minio_root_password
                )
            else:
                admin_client = self.internal_client
            admin_client.put_bucket_cors(
                Bucket=self._bucket,
                CORSConfiguration={
                    "CORSRules": [{
                        "AllowedHeaders": ["*"],
                        "AllowedMethods": ["GET", "PUT", "POST", "DELETE", "HEAD"],
                        "AllowedOrigins": ["*"],
                        "ExposeHeaders": ["ETag", "Content-Length"],
                        "MaxAgeSeconds": 3600,
                    }]
                },
            )
            logger.info("bucket CORS configured for %s", self._bucket)
        except ClientError as exc:
            logger.warning("put_bucket_cors failed (non-fatal): %s", exc)

    def ensure_tenant_prefix(self, tenant_id: str) -> None:
        """Drop a `.keep` marker so the tenant's folder is visible in mc/console."""
        key = f"{self.tenant_prefix(tenant_id)}.keep"
        try:
            self.internal_client.put_object(
                Bucket=self._bucket, Key=key, Body=b"", ContentType="text/plain"
            )
        except ClientError as exc:  # non-fatal
            logger.warning("ensure_tenant_prefix failed for %s: %s", tenant_id, exc)

    # --------------------------------------------------------------- presigning
    def _apply_public_prefix(self, signed_url: str) -> str:
        """Inject the configured public URL prefix into a boto3-signed URL.

        Does NOT change the query string, so the SigV4 signature remains
        valid. The prefix is expected to be stripped back off by a proxy
        (e.g. Caddy `handle_path /s3/*`) before the request reaches MinIO,
        so MinIO recomputes the signature over the same CanonicalURI that
        boto3 signed.
        """
        if not self._public_url_prefix:
            return signed_url
        p = urlparse(signed_url)
        new_path = f"{self._public_url_prefix}{p.path}"
        return urlunparse(p._replace(path=new_path))

    def presign_put(
        self,
        tenant_id: str,
        object_key: str,
        content_type: Optional[str] = None,
        expires_in: int = 900,
    ) -> PresignedUpload:
        self._assert_tenant_scope(object_key, tenant_id)
        params = {"Bucket": self._bucket, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type
        url = self.public_client.generate_presigned_url(
            "put_object", Params=params, ExpiresIn=expires_in
        )
        url = self._apply_public_prefix(url)
        return PresignedUpload(url=url, object_key=object_key, expires_in=expires_in)

    def presign_get(
        self,
        tenant_id: str,
        object_key: str,
        expires_in: int = 900,
        download_filename: Optional[str] = None,
    ) -> str:
        self._assert_tenant_scope(object_key, tenant_id)
        params = {"Bucket": self._bucket, "Key": object_key}
        if download_filename:
            safe = _sanitize_filename(download_filename)
            params["ResponseContentDisposition"] = f'attachment; filename="{safe}"'
        url = self.public_client.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in
        )
        return self._apply_public_prefix(url)

    # ----------------------------------------------------------------- object ops
    def head(self, tenant_id: str, object_key: str) -> dict:
        self._assert_tenant_scope(object_key, tenant_id)
        return self.internal_client.head_object(Bucket=self._bucket, Key=object_key)

    def delete_prefix(self, tenant_id: str, prefix: str) -> int:
        """Delete all objects under a prefix. Returns count of deleted objects."""
        self._assert_tenant_scope(prefix, tenant_id)
        paginator = self.internal_client.get_paginator("list_objects_v2")
        deleted = 0
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = page.get("Contents") or []
            if not objects:
                continue
            self.internal_client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": o["Key"]} for o in objects]},
            )
            deleted += len(objects)
        return deleted

    def put_bytes(
        self, tenant_id: str, object_key: str, body: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._assert_tenant_scope(object_key, tenant_id)
        self.internal_client.put_object(
            Bucket=self._bucket, Key=object_key, Body=body, ContentType=content_type
        )


storage = StorageService()
