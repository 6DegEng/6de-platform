#!/usr/bin/env bash
# =============================================================================
# 6DE Platform — Azure App Service provisioning (Phase 8 hosting flip)
# =============================================================================
# Idempotent: safe to re-run. Each step checks for the resource before creating.
# Run AFTER the App Service "Total VMs" / regional vCPU quota is approved in
# eastus2 (see QUOTA note below). Everything else (RG, Postgres, KV, ACR,
# Storage, App Insights, Log Analytics) is already provisioned.
#
# Prereqs:
#   - az login   (account: juan@6de.xyz, subscription "6DE Production")
#   - The container image must exist in ACR:
#       az acr build --registry sixdeacrjc --image 6de-platform:latest --file Dockerfile .
#     (On a cp1252 Windows console, prefix with PYTHONIOENCODING=utf-8 to avoid
#      a client-side colorama UnicodeEncodeError while streaming build logs —
#      the build itself still runs server-side regardless.)
#
# QUOTA (the current blocker, 2026-05-29):
#   `az appservice plan create ... --sku B2` fails with
#     "Current Limit (Total VMs): 0 ... required: 1".
#   App Service Linux Basic needs a regional "Total VMs" / vCPU quota > 0 in
#   eastus2. Request it in Portal → Subscription "6DE Production" → Usage+quotas
#   → filter region=East US 2, provider=Microsoft.Web (App Service), and raise
#   the App Service vCPU/instance limit to >= 2 (B2 = 2 vCPU). NOTE: the
#   "Standard BS Family vCPUs" line in `az vm list-usage` is NOT the gating
#   quota for App Service — it is a separate dimension and was a red herring.
# =============================================================================
set -euo pipefail

# --- Canonical environment (from CLAUDE_CODE_RESUME_PROMPT.md) ----------------
RG=6de-platform-rg
# Plan lives in centralus (eastus2 was capacity-blocked for B2). The plan
# already exists (created 2026-05-31), so step 1 below is a no-op; LOC only
# matters if the plan ever has to be recreated.
LOC=centralus
ACR_NAME=sixdeacrjc
KV_NAME=sixde-kv-jc
STORAGE_NAME=sixdeplatformjc
PG_NAME=sixde-platform-db-jc
APP_NAME=6de-platform-jc
APP_PLAN=6de-platform-plan
IMAGE="${ACR_NAME}.azurecr.io/6de-platform:latest"
PG_ADMIN_USER=sixdeadmin

echo "==> Subscription: $(az account show --query name -o tsv)"

# --- 1. App Service Plan (B2 Linux) ------------------------------------------
if az appservice plan show -g "$RG" -n "$APP_PLAN" >/dev/null 2>&1; then
  echo "==> Plan $APP_PLAN already exists — skipping."
else
  echo "==> Creating App Service Plan $APP_PLAN (B2 Linux)..."
  az appservice plan create -g "$RG" -n "$APP_PLAN" -l "$LOC" --is-linux --sku B2
fi

# --- 2. Web App (from ACR image) ---------------------------------------------
if az webapp show -g "$RG" -n "$APP_NAME" >/dev/null 2>&1; then
  echo "==> Web App $APP_NAME already exists — skipping create."
else
  echo "==> Creating Web App $APP_NAME from $IMAGE ..."
  az webapp create -g "$RG" -p "$APP_PLAN" -n "$APP_NAME" \
    --deployment-container-image-name "$IMAGE"
fi

# --- 3. System-assigned managed identity -------------------------------------
echo "==> Ensuring system-assigned managed identity..."
PRINCIPAL_ID=$(az webapp identity assign -g "$RG" -n "$APP_NAME" \
  --query principalId -o tsv)
echo "    principalId=$PRINCIPAL_ID"

# --- 4. Role assignments (RBAC) ----------------------------------------------
# ACR pull (admin user is disabled on the registry — identity is the path).
#
# ⚠️ KNOWN BLOCKER (2026-05-31): `az role assignment create` fails from the
# current CLI session with "(MissingSubscription) The request did not have a
# subscription or a valid tenant level resource provider." even though the
# account is Owner, the subscription is active, Graph works, and Authorization
# *reads* succeed — i.e. Authorization *writes* are blocked (likely a tenant
# policy / ABAC condition / write-token gap). If this happens, grant the role
# in the PORTAL instead:
#   ACR sixdeacrjc → Access control (IAM) → Add role assignment → AcrPull →
#   Managed identity → 6de-platform-jc.  Then re-run from step 5 (or just
#   `az webapp restart -g 6de-platform-rg -n 6de-platform-jc`).
# The function below tries the CLI and prints the manual fallback if it fails.
ACR_ID=$(az acr show -n "$ACR_NAME" --query id -o tsv)
grant_role() {  # $1=role  $2=scope  $3=label
  if az role assignment create --assignee-object-id "$PRINCIPAL_ID" \
       --assignee-principal-type ServicePrincipal --role "$1" --scope "$2" >/dev/null 2>&1; then
    echo "    granted $1 on $3"
  else
    echo "    !! could not grant $1 on $3 from CLI — grant it in the portal (IAM → Add role assignment → $1 → managed identity $APP_NAME)"
  fi
}
echo "==> Granting AcrPull on $ACR_NAME ..."
grant_role AcrPull "$ACR_ID" "$ACR_NAME"

# Key Vault uses RBAC (enableRbacAuthorization=true) — grant Secrets User.
KV_ID=$(az keyvault show -n "$KV_NAME" --query id -o tsv)
echo "==> Granting 'Key Vault Secrets User' on $KV_NAME ..."
grant_role "Key Vault Secrets User" "$KV_ID" "$KV_NAME"

# Tell the web app to pull from ACR using the managed identity.
echo "==> Pointing Web App at ACR via managed identity..."
az webapp config set -g "$RG" -n "$APP_NAME" --generic-configurations \
  '{"acrUseManagedIdentityCreds": true}' >/dev/null

# --- 5. App settings ----------------------------------------------------------
# WEBSITES_PORT must match the container's Streamlit port (8000, per Dockerfile).
# Secrets are pulled from Key Vault via references so they never live in config.
# KV refs require the secrets to exist: postgres-admin-password (present), and
# (to be added) auth-config-yaml + platform-database-url. Until those exist,
# the app boots on SQLite and the login page degrades gracefully; /_stcore/health
# is the Streamlit server liveness check and returns 200 once the container runs.
echo "==> Setting app settings..."
az webapp config appsettings set -g "$RG" -n "$APP_NAME" --settings \
  WEBSITES_PORT=8000 \
  STREAMLIT_SERVER_PORT=8000 \
  STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
  STREAMLIT_SERVER_HEADLESS=true \
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
  DB_BACKEND=sqlite \
  PLATFORM_DB_PATH=/home/data/platform.db \
  AUTH_CONFIG_PATH=/home/secrets/auth_config.yaml \
  APPLICATIONINSIGHTS_CONNECTION_STRING="@Microsoft.KeyVault(VaultName=${KV_NAME};SecretName=appinsights-connection-string)" \
  >/dev/null
# NOTE: /home is the App Service persistent share — survives restarts. For the
# Postgres flip, set DB_BACKEND=postgres and
# PLATFORM_DATABASE_URL="@Microsoft.KeyVault(VaultName=${KV_NAME};SecretName=platform-database-url)".

# --- 6. Restart + verify ------------------------------------------------------
echo "==> Restarting to pull the image..."
az webapp restart -g "$RG" -n "$APP_NAME"

HOST=$(az webapp show -g "$RG" -n "$APP_NAME" --query defaultHostName -o tsv)
echo "==> Web App host: https://${HOST}"
echo "==> Waiting for container to start (cold pull can take 1-3 min)..."
for i in $(seq 1 18); do
  code=$(curl -s -o /dev/null -w "%{http_code}" "https://${HOST}/_stcore/health" || true)
  echo "    [$i] /_stcore/health -> ${code}"
  if [ "$code" = "200" ]; then echo "==> HEALTHY ✓"; break; fi
  sleep 10
done

echo
echo "==> Verify block:"
az appservice plan show -g "$RG" -n "$APP_PLAN" --query "{state:provisioningState,sku:sku.name}" -o json
az webapp show -g "$RG" -n "$APP_NAME" --query "{state:state,host:defaultHostName}" -o json
echo "Done. If health != 200, check logs: az webapp log tail -g $RG -n $APP_NAME"
