#!/usr/bin/env bash
# ----------------------------------------------------------------------------
# Azure Shadow Cost v1 — one-shot deploy
# Prereqs: az CLI, logged in (az login), correct subscription set.
# Deploys:
#   1. Resource group
#   2. App Service Plan + App Service with system-assigned MI (main.bicep)
#   3. Sub-scoped role assignments for the MI (role-assignments.bicep)
#   4. Zip-deploys the backend + frontend code
# ----------------------------------------------------------------------------
set -euo pipefail

# ---- inputs (override via env) ----
RG="${RG:-rg-azshc}"
LOCATION="${LOCATION:-eastus}"
APP_NAME="${APP_NAME:-azshc}"
SUB_ID="${SUB_ID:-$(az account show --query id -o tsv)}"
REQUIRED_TAGS="${REQUIRED_TAGS:-Owner,CostCenter,Environment,Application}"

echo ">> Target subscription: $SUB_ID"
echo ">> Resource group:      $RG ($LOCATION)"
echo ">> App base name:       $APP_NAME"

# ---- 1. resource group ----
az group create -n "$RG" -l "$LOCATION" -o none

# ---- 2. main infra ----
echo ">> Deploying App Service + Managed Identity..."
DEPLOY_OUT=$(az deployment group create \
  --resource-group "$RG" \
  --template-file "$(dirname "$0")/main.bicep" \
  --parameters appName="$APP_NAME" targetSubscriptionId="$SUB_ID" requiredTags="$REQUIRED_TAGS" \
  --query properties.outputs -o json)

SITE_NAME=$(echo "$DEPLOY_OUT" | jq -r .siteName.value)
SITE_HOST=$(echo "$DEPLOY_OUT" | jq -r .siteHostname.value)
MI_OBJECT=$(echo "$DEPLOY_OUT" | jq -r .principalId.value)
echo ">> App: $SITE_NAME ($SITE_HOST)"
echo ">> MI principalId: $MI_OBJECT"

# ---- 3. role assignments ----
echo ">> Granting Reader + Cost Management Reader at sub scope..."
az deployment sub create \
  --location "$LOCATION" \
  --template-file "$(dirname "$0")/role-assignments.bicep" \
  --parameters principalId="$MI_OBJECT" \
  -o none

# ---- 4. code deploy ----
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ZIP="/tmp/${APP_NAME}.zip"
echo ">> Packaging $ROOT -> $ZIP"
rm -f "$ZIP"
( cd "$ROOT" && zip -qr "$ZIP" backend frontend requirements.txt -x '*/__pycache__/*' '*.pyc' )

echo ">> Zip-deploying..."
az webapp deploy \
  --resource-group "$RG" \
  --name "$SITE_NAME" \
  --src-path "$ZIP" \
  --type zip \
  -o none

echo ""
echo "Done. Open: https://${SITE_HOST}"
echo "If the site 503s for the first ~60s, that's gunicorn warming up."
