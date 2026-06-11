# Azure Postgres cutover runbook — kill the wipe-on-redeploy bug for good

**What this fixes:** the deployed app stores its SQLite database *inside* the
container, so every redeploy wipes all data (the "everything shows $0 / zero
projects" bug). This runbook moves the data to a managed Postgres server that
survives every redeploy, restart, and scale event.

**Who runs it:** Juan (or a supervised session), in Azure Cloud Shell
(<https://shell.azure.com>, Bash), signed in as **info@6de.xyz** (Owner).
Total time ~15 minutes, most of it waiting for the server to provision.

**Cost:** the smallest Postgres flexible server (Standard_B1ms burstable,
32 GB) is roughly **$13–16/month**. Key Vault is pennies. This is the only
new spend.

**The code is already done.** The app reads `DB_BACKEND` and
`PLATFORM_DATABASE_URL` from app settings; the full test suite passes against
Postgres. Nothing in this runbook touches code.

> Every step has a ✅ verification and an ↩ rollback. If a verification
> fails, stop and paste the output into the next session — do not push on.

---

## Step 0 (optional but recommended) — instant tourniquet, no new resources

Before provisioning anything, you can stop the data loss *today* by moving
the SQLite file onto the App Service's persistent `/home` share:

```bash
az webapp config appsettings set \
  --name 6de-platform-jc --resource-group 6de-platform-rg \
  --settings WEBSITES_ENABLE_APP_SERVICE_STORAGE=true \
             PLATFORM_DB_PATH=/home/data/platform.db
az webapp restart --name 6de-platform-jc --resource-group 6de-platform-rg
```

✅ Verify: browse the app, add a test client, then
`az webapp restart --name 6de-platform-jc --resource-group 6de-platform-rg`
and confirm the test client is still there.

↩ Rollback: remove the two settings
(`az webapp config appsettings delete --name 6de-platform-jc --resource-group 6de-platform-rg --setting-names WEBSITES_ENABLE_APP_SERVICE_STORAGE PLATFORM_DB_PATH`).

This keeps single-file SQLite (no concurrent writers, no managed backups), so
still do the Postgres cutover below when ready. Steps 1–7 work the same
whether or not you did Step 0.

---

## Step 1 — provision the Postgres server (~5–8 min)

Pick a strong admin password first (Cloud Shell will not echo it back):

```bash
read -s -p "Postgres admin password: " PGPASS && echo
```

```bash
az postgres flexible-server create \
  --name sixde-platform-db-jc \
  --resource-group 6de-platform-rg \
  --location eastus \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16 \
  --admin-user platformadmin \
  --admin-password "$PGPASS" \
  --database-name platform \
  --public-access None \
  --yes
```

✅ Verify:
`az postgres flexible-server show --name sixde-platform-db-jc --resource-group 6de-platform-rg --query state -o tsv`
prints `Ready`.

↩ Rollback (removes the server and any data on it):
`az postgres flexible-server delete --name sixde-platform-db-jc --resource-group 6de-platform-rg --yes`

## Step 2 — open the firewall for Azure-hosted services

```bash
az postgres flexible-server firewall-rule create \
  --name sixde-platform-db-jc --resource-group 6de-platform-rg \
  --rule-name AllowAzureServices \
  --start-ip-address 0.0.0.0 --end-ip-address 0.0.0.0
```

Honest caveat: the 0.0.0.0–0.0.0.0 rule is Azure's "allow Azure-hosted
services" rule — not the public internet, but it does include *any* Azure
customer's resources, with only the password standing between them and the
DB. That's acceptable to get off ephemeral SQLite today; a hardening
follow-up (VNet integration / private endpoint, or restricting to the App
Service's outbound IPs) is queued in the aftercare list.

✅ Verify: `az postgres flexible-server firewall-rule list --name sixde-platform-db-jc --resource-group 6de-platform-rg -o table` shows `AllowAzureServices`.

↩ Rollback: `az postgres flexible-server firewall-rule delete --name sixde-platform-db-jc --resource-group 6de-platform-rg --rule-name AllowAzureServices --yes`

## Step 3 — create the Key Vault and store the connection string

```bash
az keyvault create \
  --name sixde-kv-jc --resource-group 6de-platform-rg --location eastus

az keyvault secret set \
  --vault-name sixde-kv-jc --name platform-database-url \
  --value "postgresql://platformadmin:${PGPASS}@sixde-platform-db-jc.postgres.database.azure.com:5432/platform?sslmode=require" \
  -o none
```

(`-o none` matters — without it, az echoes the secret value, password
included, into the terminal scrollback.)

✅ Verify: `az keyvault secret show --vault-name sixde-kv-jc --name platform-database-url --query name -o tsv` prints `platform-database-url`.

↩ Rollback: `az keyvault delete --name sixde-kv-jc`

## Step 4 — let the web app read the secret (managed identity)

```bash
az webapp identity assign \
  --name 6de-platform-jc --resource-group 6de-platform-rg

PRINCIPAL_ID=$(az webapp identity show \
  --name 6de-platform-jc --resource-group 6de-platform-rg \
  --query principalId -o tsv)

az keyvault set-policy \
  --name sixde-kv-jc \
  --object-id "$PRINCIPAL_ID" \
  --secret-permissions get
```

(If `set-policy` errors because the vault uses RBAC authorization, use:
`az role assignment create --role "Key Vault Secrets User" --assignee "$PRINCIPAL_ID" --scope $(az keyvault show --name sixde-kv-jc --query id -o tsv)`)

✅ Verify: `az webapp identity show --name 6de-platform-jc --resource-group 6de-platform-rg --query principalId -o tsv` prints a GUID.

↩ Rollback: `az webapp identity remove --name 6de-platform-jc --resource-group 6de-platform-rg`

## Step 5 — flip the app to Postgres

```bash
SECRET_URI=$(az keyvault secret show \
  --vault-name sixde-kv-jc --name platform-database-url \
  --query id -o tsv)

az webapp config appsettings set \
  --name 6de-platform-jc --resource-group 6de-platform-rg \
  --settings DB_BACKEND=postgres \
             "PLATFORM_DATABASE_URL=@Microsoft.KeyVault(SecretUri=${SECRET_URI})"

az webapp restart --name 6de-platform-jc --resource-group 6de-platform-rg
```

✅ Verify (wait ~60s for cold start):
`curl -s -o /dev/null -w "%{http_code}\n" https://6de-platform-jc.azurewebsites.net/_stcore/health`
prints `200`. Then sign in and confirm every page loads. The app creates the
schema and seeds itself on first boot — Dashboard will show zero data until
Step 6. If the app errors instead, check
`az webapp log tail --name 6de-platform-jc --resource-group 6de-platform-rg`
for a Key Vault reference problem (the setting value would start with
`@Microsoft.KeyVault` in the error).

↩ Rollback (back to exactly today's behavior):
```bash
az webapp config appsettings set \
  --name 6de-platform-jc --resource-group 6de-platform-rg \
  --settings DB_BACKEND=sqlite
az webapp restart --name 6de-platform-jc --resource-group 6de-platform-rg
```

## Step 6 — import the real data

Run from a machine with the repo + tracker (Juan's PC). The import reads the
tracker **read-only** and writes to Azure Postgres. First open a temporary
firewall hole for your home IP:

```bash
# in Cloud Shell — find your home IP at https://ifconfig.me
az postgres flexible-server firewall-rule create \
  --name sixde-platform-db-jc --resource-group 6de-platform-rg \
  --rule-name juan-home --start-ip-address <YOUR_IP> --end-ip-address <YOUR_IP>
```

```powershell
# on Juan's PC, in C:\Users\Juan\code\6de-platform (PowerShell)
# Pull the connection string from Key Vault — do NOT type the password into
# the shell (PowerShell persists command history to disk).
az login   # if not already signed in as info@6de.xyz
$env:DB_BACKEND = "postgres"
$env:PLATFORM_DATABASE_URL = az keyvault secret show --vault-name sixde-kv-jc --name platform-database-url --query value -o tsv

# dry-run first — review the per-row report:
.venv\Scripts\python.exe scripts\import_legacy_xlsx.py --file "C:\Users\Juan\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\06_Engineering\01_Active Projects\Project_Tracker_2026.xlsx"

# then commit:
.venv\Scripts\python.exe scripts\import_legacy_xlsx.py --file "C:\Users\Juan\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\06_Engineering\01_Active Projects\Project_Tracker_2026.xlsx" --commit
```

✅ Verify: refresh the deployed app — Dashboard shows real project counts and
dollar figures matching the tracker (the rehearsal in
`docs/postgres-rehearsal-2026-06-11.md` records the expected numbers).

↩ Rollback: the import is idempotent (re-running updates rather than
duplicates). To start truly fresh, drop and recreate the database:
`az postgres flexible-server db delete --server-name sixde-platform-db-jc --resource-group 6de-platform-rg --database-name platform --yes`
then `... db create ... --database-name platform` and restart the app.

Afterwards, close the temporary hole and clear the connection string from
the shell (it would otherwise linger — and the test suite refuses to run
while a non-local PLATFORM_DATABASE_URL is set, by design):
```bash
az postgres flexible-server firewall-rule delete \
  --name sixde-platform-db-jc --resource-group 6de-platform-rg \
  --rule-name juan-home --yes
```
```powershell
Remove-Item Env:PLATFORM_DATABASE_URL; Remove-Item Env:DB_BACKEND
```

## Step 7 — prove the bug is dead

```bash
az webapp restart --name 6de-platform-jc --resource-group 6de-platform-rg
```

✅ Verify: after the restart the data is **still there**. Then make any
trivial commit to `main` (or re-run the Deploy to Azure workflow) and verify
the data survives a full redeploy. That redeploy used to wipe everything —
if the data survives it, the bug is dead.

---

## Aftercare (queued, separate session)

- **Network hardening:** replace the AllowAzureServices firewall rule with
  VNet integration + private endpoint (or restrict to the App Service's
  outbound IPs). Consider Entra ID auth for the app's DB identity.
- Nightly `pg_dump` backup to blob storage (script ships in a follow-up PR).
- Flexible Server has 7-day point-in-time restore built in — that's already
  better than anything SQLite had.
- Once stable for a week, remove the legacy in-container SQLite from the
  image (it's harmless meanwhile — just unused).
