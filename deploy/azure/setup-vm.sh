#!/usr/bin/env bash
# Run this locally (requires `az` CLI, already logged in).
# Creates the Azure VM, sets a DNS label, and opens HTTP/HTTPS ports.
set -euo pipefail

RESOURCE_GROUP="${RESOURCE_GROUP:-ezprint-rg}"
VM_NAME="${VM_NAME:-ezprint-vm}"
LOCATION="${LOCATION:-eastus}"
SIZE="${SIZE:-Standard_B2ms}"
ADMIN_USER="${ADMIN_USER:-azureuser}"
DNS_LABEL="ezprint-$(openssl rand -hex 4)"

echo "=== Creating resource group: $RESOURCE_GROUP in $LOCATION ==="
az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output table

echo ""
echo "=== Creating VM: $VM_NAME ($SIZE, Ubuntu 22.04) ==="
az vm create \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --image Ubuntu2204 \
  --size "$SIZE" \
  --admin-username "$ADMIN_USER" \
  --generate-ssh-keys \
  --public-ip-sku Standard \
  --output table

echo ""
echo "=== Setting DNS label: $DNS_LABEL ==="
# Resolve the public IP resource ID from the VM's NIC
PIP_ID=$(az vm show \
  --resource-group "$RESOURCE_GROUP" \
  --name "$VM_NAME" \
  --query "networkProfile.networkInterfaces[0].id" \
  --output tsv \
  | xargs -I{} az network nic show --ids {} --query "ipConfigurations[0].publicIpAddress.id" --output tsv)

az network public-ip update \
  --ids "$PIP_ID" \
  --dns-name "$DNS_LABEL" \
  --output table

echo ""
echo "=== Opening ports 80 and 443 ==="
az vm open-port --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --port 80  --priority 900
az vm open-port --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --port 443 --priority 901

FQDN="${DNS_LABEL}.${LOCATION}.cloudapp.azure.com"
PUBLIC_IP=$(az network public-ip show --ids "$PIP_ID" --query ipAddress --output tsv)

cat <<EOF

============================================================
  VM READY
  FQDN:        $FQDN
  Public IP:   $PUBLIC_IP
  SSH:         ssh ${ADMIN_USER}@${FQDN}

  Next steps:
  1. Copy the repo to the VM:
       rsync -avz --exclude '.git' --exclude '__pycache__' \\
         /path/to/EzPrint-/ ${ADMIN_USER}@${FQDN}:~/EzPrint/

  2. SSH in and run the bootstrap script:
       ssh ${ADMIN_USER}@${FQDN}
       bash ~/EzPrint/deploy/azure/bootstrap-vm.sh

  3. In .env set:
       API_DOMAIN=${FQDN}
       ACME_EMAIL=your@email.com
       PUBLIC_BASE_URL=https://${FQDN}
       S3_PUBLIC_ENDPOINT=https://${FQDN}/s3
============================================================
EOF
