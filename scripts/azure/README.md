# Azure provisioning

Scripts to deploy the 6DE Platform container to **Azure App Service for Linux**
(the canonical Phase 8 hosting target — see
`Feature_Research/Hosting_and_Integration_Roadmap.md`).

## Status (2026-05-31) — deployed except one role grant

Capacity gate **cleared** by creating the plan in **`centralus`** (eastus2 stays
B2-capacity-blocked). The Web App is created and configured; it is **not yet
serving** because the managed identity could not be granted `AcrPull` from the
CLI (see blocker below), so the container can't pull the image.

Done (verified 2026-05-31):
- App Service Plan `6de-platform-plan` — **Ready**, B2 Basic, **Central US**.
- Web App `6de-platform-jc` created; image wired `DOCKER|sixdeacrjc.azurecr.io/6de-platform:latest`.
- System-assigned managed identity (`principalId ce5b4856-cc6b-467f-a921-eb0196daabdc`).
- `acrUseManagedIdentityCreds=true`; `WEBSITES_PORT=8000` (matches the Dockerfile),
  Streamlit headless settings, `DB_BACKEND=sqlite`, https-only, healthCheckPath `/_stcore/health`.
- `https://6de-platform-jc.azurewebsites.net/_stcore/health` → **503** (no image pull yet).

### ⚠️ Blocker — grant AcrPull (needs portal / an identity with Authorization-write)

`az role assignment create` fails from the CLI with `(MissingSubscription) The
request did not have a subscription or a valid tenant level resource provider`
even though the account is Owner, the subscription is active, Microsoft Graph
works, and Authorization **reads** succeed. Authorization **writes** are blocked
(tenant policy / ABAC / write-token gap). **Grant it in the portal:**

> ACR `sixdeacrjc` → Access control (IAM) → Add role assignment → **AcrPull** →
> Assign access to **Managed identity** → select **6de-platform-jc** → Review + assign.

Then finish the deploy:

```bash
az webapp restart -g 6de-platform-rg -n 6de-platform-jc
curl -s -o /dev/null -w "%{http_code}\n" https://6de-platform-jc.azurewebsites.net/_stcore/health   # expect 200
```

## Re-running the script

```bash
bash scripts/azure/provision_app_service.sh   # idempotent; region var is centralus, plan-create is a no-op
```

It skips existing resources and re-applies settings; the AcrPull/KV grants print
a portal fallback if the CLI write is still blocked.

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
