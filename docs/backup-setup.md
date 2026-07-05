# Nightly Postgres backup — one-time setup (GATED, ~5 min in Cloud Shell)

The workflow `.github/workflows/backup.yml` dumps the production database
every night at ~2:17am ET and stores it in Azure Blob Storage. It is **inert
until you run the steps below** — merging the PR changes nothing.

**Why:** the platform database is now the only copy of production data.
Azure keeps 7 days of point-in-time restore on the server itself; these
nightly dumps are the independent second line (server deleted, bad
migration discovered late, etc.). Cost: a few cents per month.

Run in [Cloud Shell](https://shell.azure.com) (Bash, signed in as
info@6de.xyz):

## 1. Create the storage account + container + 90-day retention

```bash
az storage account create \
  --name sixdebackupjc --resource-group 6de-platform-rg \
  --location eastus2 --sku Standard_LRS --kind StorageV2 \
  --allow-blob-public-access false

az storage container create \
  --account-name sixdebackupjc --name pg-backups --auth-mode login

# Auto-delete dumps older than 90 days (no manual cleanup ever):
az storage account management-policy create \
  --account-name sixdebackupjc --resource-group 6de-platform-rg \
  --policy '{
    "rules": [{
      "enabled": true, "name": "expire-old-backups", "type": "Lifecycle",
      "definition": {
        "actions": {"baseBlob": {"delete": {"daysAfterModificationGreaterThan": 90}}},
        "filters": {"blobTypes": ["blockBlob"], "prefixMatch": ["pg-backups/"]}
      }
    }]
  }'
```

✅ Verify: `az storage container list --account-name sixdebackupjc --auth-mode login -o table` shows `pg-backups`.

## 2. Let the GitHub deploy identity write blobs + read the DB secret

```bash
SP_ID="d83e5f5e"   # AZURE_CLIENT_ID from the GitHub repo secrets — paste the full value

az role assignment create --role "Storage Blob Data Contributor" \
  --assignee "$SP_ID" \
  --scope $(az storage account show --name sixdebackupjc --query id -o tsv)

az role assignment create --role "Key Vault Secrets User" \
  --assignee "$SP_ID" \
  --scope $(az keyvault show --name sixde-kv-jc --query id -o tsv)

# The workflow also opens/closes a temporary firewall rule on the Postgres
# server, which needs Contributor on the server (the deploy SP currently has
# Contributor only on ACR + the web app):
az role assignment create --role "Contributor" \
  --assignee "$SP_ID" \
  --scope $(az postgres flexible-server show --name sixde-platform-db-jc \
            --resource-group 6de-platform-rg --query id -o tsv)
```

## 3. Flip the switch

```bash
gh variable set BACKUP_ENABLED --body true --repo 6DegEng/6de-platform
```

(Or GitHub → repo → Settings → Secrets and variables → Actions → Variables →
New variable `BACKUP_ENABLED` = `true`.)

## 4. Prove it end-to-end (don't skip)

GitHub → Actions → "Nightly Postgres backup to Blob" → **Run workflow**.
Green run = a `platform_<date>.dump` blob exists:

```bash
az storage blob list --account-name sixdebackupjc \
  --container-name pg-backups --auth-mode login -o table
```

## Restoring (the part that matters in a crisis)

```bash
# Download the dump
az storage blob download --account-name sixdebackupjc \
  --container-name pg-backups --name platform_<DATE>.dump \
  --file restore.dump --auth-mode login

# Restore into a FRESH database (never overwrite prod blindly):
az postgres flexible-server db create \
  --server-name sixde-platform-db-jc --resource-group 6de-platform-rg \
  --database-name platform_restore
pg_restore --dbname="postgresql://sixdeadmin:<PASSWORD>@sixde-platform-db-jc.postgres.database.azure.com:5432/platform_restore?sslmode=require" \
  --no-owner restore.dump
```

Then point the app at `platform_restore` (or rename databases) once the data
is verified. Admin user is **sixdeadmin** (East US 2 server — see the as-run
notes in `docs/azure-postgres-cutover-runbook.md`).

## How to undo / disable

Set `BACKUP_ENABLED` to anything other than `true` (or delete the variable).
The storage account can stay — it costs cents and keeps the existing dumps.
