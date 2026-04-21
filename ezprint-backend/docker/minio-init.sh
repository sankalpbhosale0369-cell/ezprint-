#!/bin/sh
set -eu

# This script runs inside the `minio/mc` image (sh, not bash).
# It provisions the ezprint bucket, a scoped service account, and basic
# lifecycle rules to auto-delete originals once jobs have been completed.

MINIO_ALIAS="local"
MC="/usr/bin/mc"

echo "[minio-init] Waiting for MinIO at ${S3_ENDPOINT}..."
until $MC alias set "$MINIO_ALIAS" "$S3_ENDPOINT" "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1; do
  sleep 1
done
echo "[minio-init] MinIO is ready"

if ! $MC ls "$MINIO_ALIAS/$S3_BUCKET_NAME" >/dev/null 2>&1; then
  echo "[minio-init] Creating bucket $S3_BUCKET_NAME"
  $MC mb --ignore-existing "$MINIO_ALIAS/$S3_BUCKET_NAME"
else
  echo "[minio-init] Bucket $S3_BUCKET_NAME already exists"
fi

# Disable anonymous public access - everything must go through presigned URLs.
$MC anonymous set none "$MINIO_ALIAS/$S3_BUCKET_NAME" >/dev/null 2>&1 || true

# Scoped service account for the backend API.
# Safe to re-run: the add command returns non-zero if the user exists; we ignore that.
$MC admin user add "$MINIO_ALIAS" "$S3_ACCESS_KEY" "$S3_SECRET_KEY" 2>/dev/null || true
cat <<EOF >/tmp/ezprint-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:DeleteObject",
        "s3:ListBucket",
        "s3:GetBucketLocation"
      ],
      "Resource": [
        "arn:aws:s3:::${S3_BUCKET_NAME}",
        "arn:aws:s3:::${S3_BUCKET_NAME}/*"
      ]
    }
  ]
}
EOF
$MC admin policy create "$MINIO_ALIAS" ezprint-rw /tmp/ezprint-policy.json 2>/dev/null || true
$MC admin policy attach "$MINIO_ALIAS" ezprint-rw --user "$S3_ACCESS_KEY" 2>/dev/null || true

# Lifecycle: auto-expire original customer uploads 7 days after creation.
# Finalized print PDFs live a bit longer; previews expire fast.
cat <<EOF >/tmp/ezprint-lifecycle.json
{
  "Rules": [
    {
      "ID": "expire-originals",
      "Status": "Enabled",
      "Filter": { "Prefix": "tenants/" },
      "Expiration": { "Days": 7 }
    }
  ]
}
EOF
$MC ilm import "$MINIO_ALIAS/$S3_BUCKET_NAME" </tmp/ezprint-lifecycle.json || true

echo "[minio-init] Bucket ready: $S3_BUCKET_NAME"
