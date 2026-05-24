# 6DE Company Platform

Internal ERP for **6th Degree Engineering** — Streamlit + SQLite (Postgres at Phase 8). Tracks projects, proposals, permits, billing, calc-engine output, accounting, time, bids, CRM.

**Current phase:** Phase 1 — cloud prerequisites (no deploy yet). See `PLATFORM_GOAL_v1.md` for the full roadmap.

---

## Quick start

```powershell
# 1. Clone
git clone <YOUR_REPO_URL> 6de-platform
cd 6de-platform

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# 3. Install deps
pip install -r requirements.txt

# 4. Bootstrap auth_config.yaml
copy auth_config.example.yaml auth_config.yaml
# Then edit auth_config.yaml — replace EXAMPLE_HASH lines with real bcrypt hashes:
python -c "import bcrypt; print(bcrypt.hashpw(b'YOUR_PASSWORD', bcrypt.gensalt(rounds=12)).decode())"
# Quote the printed hash in YAML with double quotes (it contains `$`).
# Also replace the cookie key with a new random hex:
python -c "import secrets; print(secrets.token_hex(32))"

# 5. Launch
python launch_platform.py
# Opens at http://localhost:8502
```

---

## Environment variables

All paths and behaviors are driven by env vars with sensible defaults. Set them in `.env` or your shell.

| Variable | Default | Purpose |
|---|---|---|
| `PLATFORM_DB_PATH` | `%LOCALAPPDATA%\6th-degree-platform\data\platform.db` (Windows) / `~/.local/share/6th-degree-platform/data/platform.db` (other) | Local SQLite path. Kept out of OneDrive to avoid sync-conflict locks |
| `DB_BACKEND` | `sqlite` | `sqlite` (current) or `postgres` (Phase 8). The postgres branch is intentionally a `NotImplementedError` until Phase 8 |
| `PLATFORM_DATABASE_URL` | (unset) | Used only when `DB_BACKEND=postgres` — full Postgres URL |
| `AUTH_CONFIG_PATH` | `<project_root>/auth_config.yaml` | Where to load `streamlit-authenticator` credentials. Override for prod secrets-store paths |
| `SIXDE_CALC_DB` | OneDrive path | Calc engine `common.db` (read-only bridge). Unset = bridge gracefully reports unavailable |
| `SIXDE_STRUCTURAL_DB` | OneDrive path | Calc engine structural DB |
| `SIXDE_DRAINAGE_DB` | OneDrive path | Calc engine drainage DB |
| `SIXDE_INSPECTION_DB` | OneDrive path | Calc engine inspection DB |
| `SIXDE_CALC_EXE` | OneDrive path | PyWebView calculator launcher exe path |

The startup banner from `python launch_platform.py` prints the resolved values — use it to verify env vars took effect.

---

## Project layout

```
07_Company_Platform/
├── PLATFORM_GOAL_v1.md           # Phased roadmap, approved 2026-05-12
├── CHANGELOG.md                   # Session-by-session change log
├── README.md                      # This file
├── Dockerfile / .dockerignore     # Container build (Phase 8 hosting prep)
├── .github/workflows/ci.yml       # Lint + smoke-import on every push
├── .gitignore                     # Excludes secrets, DB, research artifacts
├── config.py                      # All env-var-driven paths
├── launch_platform.py             # Local launcher; prints config banner
├── requirements.txt
├── auth_config.example.yaml       # Template; copy to auth_config.yaml locally
├── db/
│   ├── __init__.py                # ensure_db(), connection factory, migrations
│   └── schema.sql                 # Table definitions
├── modules/                       # Domain logic — one folder per page
│   ├── accounting/
│   ├── banking/                   # BofA CSV import, categorization rules CRUD
│   ├── bids/
│   ├── billing/
│   ├── calculator/                # Lazy bridge to common.db; safe when missing
│   ├── crm/
│   ├── dashboard/
│   ├── documents/
│   ├── financials/
│   ├── invoicing/
│   ├── permits/
│   ├── projects/
│   ├── subconsultants/
│   └── timekeeping/
├── streamlit_app/
│   ├── Home.py                    # Dashboard
│   ├── auth.py                    # require_auth(), AUTH_CONFIG_PATH loader
│   ├── components/                # Shared formatters, widgets
│   └── pages/                     # Auto-routed sidebar pages
├── scripts/
│   ├── sync_accounting.py         # Nightly Excel hash-and-import
│   └── importers/                 # Bootstrap data importers
├── docs/
│   └── data_definitions.md        # What each metric actually computes
└── tests/
    └── test_smoke.py              # 5 smoke tests run by CI
```

---

## Database

The platform uses SQLite locally and is preparing for Postgres at Phase 8.

### Where the DB file lives

`%LOCALAPPDATA%\6th-degree-platform\data\platform.db` on Windows. **Not in OneDrive** — OneDrive's sync agent grabs file handles and causes `database is locked` cascades. This was the Phase 0-A blocker.

If you've upgraded from a pre-Phase-1 install, the legacy DB at `<project_root>/db/platform.db` is copied automatically to the new location on first `ensure_db()` call. The legacy file is left in place but no longer touched.

### Schema migrations

`db/__init__.py` stores a SHA-256 fingerprint of `schema.sql + _ALTER_COLUMNS` in a `_meta` table. On every `ensure_db()` call, it compares the current code's fingerprint to the stored one — migrations run only when they differ. This eliminates the per-page-load ALTER TABLE cascade that caused Phase 0-A locking.

### Resetting

```powershell
# Stop Streamlit, then:
Remove-Item "$env:LOCALAPPDATA\6th-degree-platform\data\platform.db*"
python launch_platform.py
# ensure_db() rebuilds the schema, runs the seeds, and bridges proposals -> opportunities.
```

### Re-importing the source data

The platform was bootstrapped from two Excel workbooks via:

```powershell
python scripts/importers/import_all.py
python scripts/importers/import_permitting_contacts.py
```

Both are idempotent — re-running them only inserts what's new.

---

## Docker (Phase 8 prep)

A Dockerfile is in the repo so production deploy (Phase 8) is a flip, not a rewrite. Local Docker is **not** required for dev — use `python launch_platform.py` instead.

```powershell
# Build
docker build -t 6de-platform .

# Run with a mounted data volume + auth secret
docker run -p 8000:8000 `
    -e DB_BACKEND=sqlite `
    -e PLATFORM_DB_PATH=/data/platform.db `
    -e AUTH_CONFIG_PATH=/secrets/auth_config.yaml `
    -v 6de_data:/data `
    -v ${PWD}\auth_config.yaml:/secrets/auth_config.yaml:ro `
    6de-platform
# App at http://localhost:8000
```

At Phase 8 (Render), the volume becomes a Render Persistent Disk, auth is mounted from Render Secrets, and `DB_BACKEND` flips to `postgres` with `PLATFORM_DATABASE_URL` pointing at Neon.

---

## Calc engine bridge

The platform reads the calc engine's `common.db` **read-only** via `modules/calculator/bridge.py`. The bridge is lazy: imports don't touch the calc DB at module load, and `db.get_calc_connection()` returns `None` if `CALC_DB_PATH` is unset or the file is missing. Pages that consume the bridge (currently `8_Calculator.py`) check for `None` and render a graceful "calc bridge unavailable" notice when running in environments without the calc engine (CI, future cloud deploy).

To verify the lazy behavior locally:

```powershell
$env:SIXDE_CALC_DB = "C:\nonexistent\path.db"
python launch_platform.py
# Calculator page should load without traceback; show the unavailable notice.
```

---

## Running the tests

```powershell
pytest tests/ -q
```

Five smoke tests live in `tests/test_smoke.py`. CI runs them on every push. They cover schema init, transaction dedup, invoice numbering, and the `transactions.source` column migration.

The banking module has 78 additional tests covering the CSV parser (encoding, date/amount edge cases, header detection), categorization engine (priority ordering, first-match-wins, CRUD), and a full round-trip integration test (parse -> categorize -> commit -> dedup on reimport).

---

## Common operations

### Reset the admin password

```powershell
# Generate a new hash:
python -c "import bcrypt; print(bcrypt.hashpw(b'NEW_PASSWORD', bcrypt.gensalt(rounds=12)).decode())"
# Then edit auth_config.yaml — replace the value under credentials.usernames.admin.password.
# Quote with double quotes (the hash contains `$`).
```

### Stop a stuck Streamlit on port 8502

```powershell
Get-NetTCPConnection -LocalPort 8502 -ErrorAction SilentlyContinue |
    ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### View activity log

```powershell
python -c "import sys; sys.path.insert(0, '.'); from db import ensure_db; conn = ensure_db(); [print(r['created_at'], r['entity_type'], r['action']) for r in conn.execute('SELECT * FROM activity_log ORDER BY id DESC LIMIT 20').fetchall()]"
```

---

## Documentation pointers

- `PLATFORM_GOAL_v1.md` — full phased roadmap (12 phases, approved)
- `docs/data_definitions.md` — what each money metric actually computes (avoid the cash-basis-vs-invoice-basis trap)
- `CHANGELOG.md` — what shipped in each session
- `_research/crm_data_discovery.md` — Phase 0.5 data discovery (local-only)
- `SESSION34_BUG_BACKLOG.md` — open bug backlog (local-only)
