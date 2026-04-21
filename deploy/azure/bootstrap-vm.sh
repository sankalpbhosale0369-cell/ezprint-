#!/usr/bin/env bash
# Run this on the Azure VM after copying the repo.
# Installs Docker, generates secrets, and prepares .env for the first launch.
set -euo pipefail

REPO_DIR="${REPO_DIR:-$HOME/EzPrint}"
BACKEND_DIR="$REPO_DIR/ezprint-backend"

echo "=== Installing Docker ==="
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"

echo ""
echo "=== Generating .env from template ==="
cp "$REPO_DIR/deploy/azure/env.template" "$BACKEND_DIR/.env"

JWT=$(openssl rand -hex 32)
PGPASS=$(openssl rand -hex 16)
MINIOADMINPASS=$(openssl rand -hex 16)
S3PASS=$(openssl rand -hex 16)

sed -i "s|__JWT_SECRET__|$JWT|g"               "$BACKEND_DIR/.env"
sed -i "s|__POSTGRES_PASSWORD__|$PGPASS|g"     "$BACKEND_DIR/.env"
# DATABASE_URL also embeds the password
sed -i "s|__PGPASS_IN_URL__|$PGPASS|g"         "$BACKEND_DIR/.env"
sed -i "s|__MINIO_ROOT_PASSWORD__|$MINIOADMINPASS|g" "$BACKEND_DIR/.env"
sed -i "s|__S3_SECRET_KEY__|$S3PASS|g"         "$BACKEND_DIR/.env"

cat <<EOF

=== NEXT STEPS ===

1. Edit $BACKEND_DIR/.env and fill in the two required values:

     API_DOMAIN=<your-fqdn>.eastus.cloudapp.azure.com
     ACME_EMAIL=your@email.com

   PUBLIC_BASE_URL and S3_PUBLIC_ENDPOINT will be set for you once you
   substitute API_DOMAIN — or just edit them directly:

     PUBLIC_BASE_URL=https://<your-fqdn>.eastus.cloudapp.azure.com
     S3_PUBLIC_ENDPOINT=https://<your-fqdn>.eastus.cloudapp.azure.com/s3

2. Log out and back in (or run 'newgrp docker') so Docker group takes effect.

3. Start the stack:

     cd $BACKEND_DIR
     docker compose \\
       -f docker-compose.yml \\
       -f docker-compose.prod.yml \\
       -f docker-compose.azure.yml \\
       up -d --build

4. Seed demo data:

     docker compose exec api python -m app.scripts.seed_demo

5. Verify:

     curl https://<your-fqdn>.eastus.cloudapp.azure.com/healthz
EOF
