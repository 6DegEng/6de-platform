# Azure provisioning

Scripts to deploy the 6DE Platform container to **Azure App Service for Linux**
(the canonical Phase 8 hosting target — see
`Feature_Research/Hosting_and_Integration_Roadmap.md`).

## Status (2026-05-29)

Foundational resources are provisioned (RG `6de-platform-rg` eastus2, Postgres
`sixde-platform-db-jc`, KV `sixde-kv-jc`, ACR `sixdeacrjc`, Storage
`sixdeplatformjc`, App Insights, Log Analytics). **The App Service Plan + Web
App are blocked on a regional "Total VMs" / vCPU quota** that is currently `0`
in eastus2:

```
az appservice plan create ... --sku B2
ERROR: Operation cannot be completed without additional quota.
Current Limit (Total VMs): 0 ... required: 1
```

> The `Standard BS Family vCPUs` line in `az vm list-usage` (limit 10) is **not**
> the gating quota for App Service — it is a separate dimension. Request the
> App Service vCPU/instance quota in Portal → Subscription → Usage + quotas →
> region `East US 2`, provider `Microsoft.Web`, raise to ≥ 2 (B2 = 2 vCPU).

## Once quota is approved — one command

```bash
# 1. Build the image into ACR (server-side; client log-streaming may crash on a
#    cp1252 Windows console — prefix PYTHONIOENCODING=utf-8 to avoid it).
PYTHONIOENCODING=utf-8 az acr build --registry sixdeacrjc \
  --image 6de-platform:latest --file Dockerfile .

# 2. Provision plan + webapp + identity + roles + settings + verify.
bash scripts/azure/provision_app_service.sh
```

The script is idempotent — re-running it skips resources that already exist and
re-applies role assignments / app settings.

## Secrets still to stage in Key Vault before a real (non-smoke) deploy

- `auth-config-yaml` — the `streamlit-authenticator` credentials (bcrypt hashes
  + cookie key), mounted to `/home/secrets/auth_config.yaml` via a KV reference
  or a startup step.
- `platform-database-url` — the Azure Postgres connection string, for the
  eventual `DB_BACKEND=postgres` flip.
- `appinsights-connection-string` — referenced by the script's app settings.

The first deploy can run on `DB_BACKEND=sqlite` with no auth secret: Streamlit
still boots and `/_stcore/health` returns 200, which validates the pull/run
pipeline before secrets are wired.
