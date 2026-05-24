# Hosting & Integration Roadmap — 6DE Platform / Vesta / 6de.xyz

**Prepared for:** Juan Castillo
**Date:** May 23, 2026
**Purpose:** Sequence the move from today's split-stack ("Streamlit on local Windows + WordPress on shared host + Vesta on office PC + scattered identity") to a unified state ("one identity, one billing relationship, one console") without an all-or-nothing rewrite. Avoid downtime, preserve what works, defer what's expensive.
**Sibling memos:** [Panamerican_Monday_Deep_Dive.md](../Panamerican_Monday_Deep_Dive.md) (workflow patterns to absorb), [Odoo_Deep_Dive.md](./Odoo_Deep_Dive.md) (feature patterns + the original Vesta concept)

---

## 1. Executive Summary

Three things change. Two things stay where they are.

**Changing:**

1. **6DE Platform** moves from local Windows + OneDrive-hosted SQLite to **Azure App Service + Azure Database for PostgreSQL + Blob Storage**. Solves the OneDrive sync truncation issue, makes it accessible from anywhere (including mobile), and brings auth into Azure AD where M365 already lives.
2. **6de.xyz** moves from **WordPress to a static-site framework (Astro recommended, Next.js acceptable) on Azure Static Web Apps**. Free tier covers the marketing site, git-push deploys, atomic rollback, no more WordPress maintenance.
3. **Vesta gets a public endpoint** at `vesta.6de.xyz` via a small **FastAPI shim + Cloudflare Tunnel** running on the office PC. The Vesta runtime stays on the office PC (no GPU compute bill). The 6DE Platform Sidekick talks to it over HTTPS.

**Staying put:**

- **Vesta runtime stays on the office PC** for the foreseeable future. The Ollama + `qwen2.5:32b` setup needs ~24 GB RAM and ideally a GPU; renting equivalent GPU compute on Azure runs $360–650/mo always-on, which is real money for zero short-term gain.
- **OneDrive remains the engineering document store**. Vesta's RAG indexes from there. Don't move the documents; the friction isn't worth it. (Source code is a different story — see §5.1.)

**The unification glue is Azure AD.** You already have it via Microsoft 365. Wire all three surfaces (website, platform, Vesta admin UI) to authenticate against the same tenant, and you get single sign-on without standing up a separate identity provider.

**Net cost target:** roughly **$75–85/mo** for everything cloud-side. The expensive part (the LLM) keeps running on hardware you already own.

**Realistic effort:** 6–9 weekends of focused work, split across three independent tracks that can run in parallel. The order matters only at cutover, not during construction.

---

## 2. Target Architecture

```
                          ┌──────────────────────┐
                          │   Azure AD tenant    │
                          │   (M365-backed)      │
                          │   single identity    │
                          └──────────┬───────────┘
                                     │
            ┌────────────────────────┼────────────────────────┐
            │ SSO                    │ SSO                    │ SSO
            ▼                        ▼                        ▼
   ┌─────────────────┐    ┌─────────────────────┐    ┌────────────────────┐
   │  6de.xyz        │    │  app.6de.xyz        │    │  vesta.6de.xyz     │
   │  Azure Static   │    │  Azure App Service  │    │  Cloudflare Tunnel │
   │  Web Apps       │    │  (Streamlit, Linux) │    │     ↓              │
   │  (Astro)        │    │     │               │    │  Office PC         │
   │  Free tier      │    │     ▼               │    │  FastAPI shim      │
   │                 │    │  Azure Postgres     │    │     ↓              │
   │  Marketing site │    │  Flex Burstable     │    │  Vesta agent loop  │
   │  Blog, services │    │     │               │    │  (Ollama qwen2.5)  │
   │  Contact form   │    │  Azure Blob        │    │  RAG (ChromaDB)    │
   └─────────────────┘    │  (file uploads)     │    │  Skills, scripts   │
                          │                     │    │  task-queue.json   │
                          │  Platform Sidekick  │◄───┤  HTTPS, shared     │
                          │  → calls vesta.6de  │    │  secret auth       │
                          └─────────────────────┘    └──────────┬─────────┘
                                                                │
                                                       ┌────────▼────────┐
                                                       │  OneDrive       │
                                                       │  (engineering   │
                                                       │   documents)    │
                                                       │  RAG source     │
                                                       └─────────────────┘
```

Each box is one billable thing. The arrows are HTTPS calls. The dotted nothing-special is the office PC sitting in the corner doing the GPU work for free.

---

## 3. Current State Inventory

| What | Where | How accessed | Pain points |
|---|---|---|---|
| 6DE Platform (Streamlit) | Local Windows, OneDrive-synced repo, SQLite DBs in OneDrive | `Launch_6DE_Platform.bat` on Juan's PC | OneDrive sync truncates files mid-write; only Juan can use it; not mobile |
| 6de.xyz | WordPress on shared/managed hosting | Browser, public | Hard to edit, plugin maintenance, no preview-on-PR, slow iteration |
| Vesta | Office PC | Telegram bot (chat 8624235438), `! vcal` / `! vemail` shortcuts | Tied to Juan's Telegram; no programmatic access for the platform |
| M365 / Azure AD | Microsoft cloud (existing tenant `372f1dc2-…`) | Outlook, Vesta via Graph API | Identity is already in Azure AD; nothing else uses it for SSO yet |
| OneDrive | Microsoft cloud, mounted on Juan's PC | Native Windows mount | Sync race conditions when programmatic writes happen (see Session 3e calc UI issue) |
| Engineering calc engine | Local Windows, `common.db` SQLite | Bridge module in platform | Tightly coupled to OneDrive path; same sync risk |
| Source code | OneDrive folder, git remote | git push to (assumed) GitHub | OneDrive sync + git internals is a recipe for `.git` corruption |

The pattern: too much in OneDrive, nothing in a cloud-native runtime.

---

## 4. Three Parallel Migration Tracks

Each track is independent. You can do them in any order, or in parallel if you have the attention budget. The crossover layer (Track D, Auth Unification) blocks nothing — you can ship each surface with stub auth and unify later.

| Track | Scope | Effort | Risk | Blocks anything? |
|---|---|---|---|---|
| **A** | Platform → Azure App Service + Postgres | 2–3 weekends | Medium (DB migration) | Nothing — runs alongside local until cutover |
| **B** | Vesta → public endpoint via FastAPI + Cloudflare Tunnel | 1 weekend | Low | Vesta integration in Sidekick V1+ |
| **C** | Website → Astro on Azure Static Web Apps | 1–2 weekends | Low | Nothing — DNS cutover at the end |
| **D** | Auth unification across A/B/C | 1 weekend | Medium (config) | Nothing — can land last |

**Recommended sequence** if you do them serially: **B → A → C → D**. Rationale in §10.

---

## 5. Track A — Platform to Azure

### 5.1 The first un-fork: source code out of OneDrive

Before touching Azure, move the platform source code out of `C:\Users\Juan\OneDrive - 6th Degree Engineering\…\07_Company_Platform` and into a non-synced path like `C:\Users\Juan\code\6de-platform`. The OneDrive sync race condition that truncated `8_Calculator.py` mid-Session-3e will keep happening; git's internals are especially vulnerable.

- Clone fresh from your git remote into `C:\Users\Juan\code\6de-platform`.
- Update `Launch_6DE_Platform.bat` to point at the new path.
- Delete the OneDrive copy (after confirming the remote has everything).
- Engineering documents stay in OneDrive — that's data, not code.
- This is a one-evening task and pays dividends immediately even before Azure.

### 5.2 Containerize

The platform needs to run on Linux App Service. That means a Dockerfile.

- Base image: `python:3.11-slim`
- Install system deps: `gcc`, `libpq-dev` (for psycopg2), `libsqlite3-0` (transitional, drop once Postgres migration is done)
- Copy `requirements.txt`, `pip install`
- Copy `streamlit_app/`, `modules/`, `db/`, `config.py`, `auth_config.yaml`
- Expose port 8000
- ENTRYPOINT: `streamlit run streamlit_app/Home.py --server.port 8000 --server.address 0.0.0.0 --server.enableCORS false --server.enableXsrfProtection false`
- Build locally, smoke test (`docker run -p 8000:8000 ...`), confirm Streamlit renders.

### 5.3 SQLite → Postgres migration

You have at least two SQLite DBs: the platform's own (`db/__init__.py` setup) and the calc engine's `common.db`. Both need to move.

- **Pick a migration tool**: `pgloader` is the standard for SQLite→Postgres. Single command, handles schema + data + foreign keys.
- **Alembic regenerate**: re-run `alembic upgrade head` against an empty Postgres DB to confirm migrations apply cleanly (catches dialect-specific SQL that worked on SQLite).
- **Fix dialect issues**: SQLite is forgiving about types and FKs; Postgres is not. Likely issues:
  - `JSON` columns (subagent 6b.3's `saved_views.filters_json` etc.) need `JSONB` for indexing
  - Auto-increment integer PKs need `SERIAL` or `IDENTITY`
  - Date/datetime columns need explicit timezone (`TIMESTAMP WITH TIME ZONE`)
  - Boolean columns: SQLite stores as 0/1, Postgres needs actual booleans
- **Run pgloader**: from a snapshot of the SQLite file, push to a fresh Postgres instance, validate row counts and a few sample queries.
- **Calc engine DB (`common.db`)**: same treatment. The bridge module in `modules/calculator/bridge.py` becomes a Postgres reader instead of a SQLite reader. Same SQL works (the bridge already uses ANSI SQL).

### 5.4 Azure provisioning (one-time, ~1 hour)

```bash
# Conceptual — actual commands depend on whether you use Portal, CLI, or Bicep
az group create --name 6de-platform-rg --location eastus2
az postgres flexible-server create \
  --name 6de-platform-db \
  --resource-group 6de-platform-rg \
  --location eastus2 \
  --tier Burstable --sku-name Standard_B1ms \
  --storage-size 32 \
  --version 16
az appservice plan create \
  --name 6de-platform-plan \
  --resource-group 6de-platform-rg \
  --is-linux --sku B2
az webapp create \
  --resource-group 6de-platform-rg \
  --plan 6de-platform-plan \
  --name 6de-platform \
  --deployment-container-image-name <your-registry>/6de-platform:latest
az storage account create \
  --name 6deplatformstorage \
  --resource-group 6de-platform-rg \
  --sku Standard_LRS
```

Set app settings: `DATABASE_URL`, `STREAMLIT_SERVER_HEADLESS=true`, `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`, `ANTHROPIC_API_KEY` (if/when Vesta V0 needs the fallback path), `VESTA_BASE_URL=https://vesta.6de.xyz` (Track B output).

### 5.5 Streamlit on App Service quirks

- App Service supports WebSockets, but you must enable it: `az webapp config set --web-sockets-enabled true`. Streamlit's interactivity will not work otherwise.
- App Service Linux uses port 8000 by default. Tell Streamlit to bind there.
- Health check endpoint: Streamlit doesn't expose one. Configure App Service to use `/` with a 30s startup delay.
- Always-on: enable it. Otherwise the app cold-starts on every request and you'll see 30s waits.
- Logging: pipe `stdout`/`stderr` to App Service log stream so you can `az webapp log tail` from anywhere.

### 5.6 Cutover

- Stand up the Azure stack with a fresh Postgres + an initial data migration from local SQLite.
- DNS: point `app.6de.xyz` to the App Service. SSL via Azure-managed cert (free, auto-renewing).
- Smoke test all 9 pages.
- Run side-by-side for a week (use Azure for new work, keep local as the source of truth).
- Final data sync (re-run pgloader against the latest SQLite snapshot, confirm row counts match).
- Cut over: local platform becomes read-only archive. Azure is canonical.

### 5.7 Cost (Track A)

| Resource | SKU | Monthly |
|---|---|---|
| App Service Plan | Linux B2 (2 vCPU, 3.5 GB RAM) | ~$55 |
| Postgres Flexible Server | Burstable B1ms (1 vCPU, 2 GB) | ~$16 |
| Postgres storage | 32 GB | ~$4 |
| Blob Storage | LRS, ~10 GB | ~$2 |
| Egress | <100 GB/mo at single-user load | ~$2 |
| **Track A subtotal** | | **~$80/mo** |

---

## 6. Track B — Vesta Public Endpoint

### 6.1 The shape of the bridge

Vesta today only speaks Telegram. The 6DE Platform Sidekick needs a programmatic endpoint. The minimum-viable shim is a **single-process FastAPI server** running on the same office PC as the Vesta agent, with two routes:

```python
# vesta_api.py — runs on office PC alongside the Vesta agent loop
from fastapi import FastAPI, HTTPException, Depends, Header
import subprocess, json, os
from pathlib import Path

app = FastAPI(title="Vesta Bridge")
VESTA_HOME = Path(r"C:\Users\Juan\vesta")
SHARED_SECRET = os.environ["VESTA_SHARED_SECRET"]

def verify(authorization: str = Header(None)):
    if authorization != f"Bearer {SHARED_SECRET}":
        raise HTTPException(401, "unauthorized")

@app.post("/rag/query", dependencies=[Depends(verify)])
def rag_query(payload: dict):
    """Pass through to Vesta's existing rag/query.py script."""
    q = payload["question"]
    r = subprocess.run(
        ["python", str(VESTA_HOME / "rag" / "query.py"), q],
        capture_output=True, text=True, timeout=60,
    )
    if r.returncode != 0:
        raise HTTPException(500, r.stderr)
    return {"answer": r.stdout, "sources": _parse_sources(r.stdout)}

@app.get("/queue", dependencies=[Depends(verify)])
def get_queue():
    """Read the overnight task queue."""
    return json.loads((VESTA_HOME / "task-queue.json").read_text(encoding="utf-8"))

@app.post("/queue", dependencies=[Depends(verify)])
def add_to_queue(payload: dict):
    """Pass through to queue_task.py."""
    subprocess.run(
        ["python", str(VESTA_HOME / "scripts" / "queue_task.py"),
         "--description", payload["description"],
         "--source", "6de-platform"],
        check=True,
    )
    return {"status": "queued"}
```

That's the entire integration. No async, no orchestration, no LLM proxy. Three routes that wrap three existing CLI invocations.

### 6.2 Cloudflare Tunnel

Cloudflare Tunnel exposes a local service to the public internet via Cloudflare's edge without opening a router port. Setup:

1. `cloudflared` install on the office PC (`winget install --id Cloudflare.cloudflared`).
2. Log in: `cloudflared tunnel login` (opens browser, auth via your Cloudflare account).
3. Create tunnel: `cloudflared tunnel create vesta-bridge`. Saves credentials to `%USERPROFILE%\.cloudflared\<tunnel-id>.json`.
4. Route: `cloudflared tunnel route dns vesta-bridge vesta.6de.xyz`.
5. Config file `%USERPROFILE%\.cloudflared\config.yml`:
   ```yaml
   tunnel: <tunnel-id>
   credentials-file: C:\Users\Juan\.cloudflared\<tunnel-id>.json
   ingress:
     - hostname: vesta.6de.xyz
       service: http://localhost:8765
     - service: http_status:404
   ```
6. Install as Windows service: `cloudflared service install`. Starts on boot.
7. Start FastAPI on port 8765: `uvicorn vesta_api:app --host 127.0.0.1 --port 8765`. Run as a scheduled task on login, or as a Windows service via `nssm`.

Result: `https://vesta.6de.xyz` reaches your FastAPI shim. Free SSL (Cloudflare-managed). No router config. No public IP exposure.

### 6.3 Auth between platform and Vesta

For Track B alone, use a **shared secret**: generate a long random string, set it in both Azure App Service (`VESTA_SHARED_SECRET`) and the office PC environment. The platform sends it in the `Authorization: Bearer <secret>` header. The FastAPI shim validates.

This is intentionally crude — it's enough for one user, one platform instance, one shim. When Track D (Azure AD SSO) lands, upgrade to JWT validation against your Azure AD tenant.

### 6.4 Failure modes

- **Office PC off** → vesta.6de.xyz returns Cloudflare 502. Sidekick must render `st.info("Vesta is offline — your office PC isn't reachable")` and continue. Don't block the platform's other work.
- **Office internet down** → same.
- **Vesta agent stuck** → RAG query timeout returns 504 after 60s. Same graceful-degrade.
- **task-queue.json corrupt** → 500 with the parse error. Vesta's own daily backup of the queue (set this up if not already) is the recovery mechanism.

Sidekick should treat Vesta as a flaky external service from day one. The platform never blocks on Vesta being available.

### 6.5 Cost (Track B)

| Resource | Cost |
|---|---|
| Cloudflare Tunnel | $0 (free tier) |
| Office PC power (already running) | $0 incremental |
| Domain `6de.xyz` (existing) | $0 incremental |
| **Track B subtotal** | **$0/mo** |

---

## 7. Track C — Website to Astro on Azure Static Web Apps

### 7.1 Why Astro over Next.js

- **Astro is content-first.** Marketing sites are 95% content. Astro renders to plain HTML at build time, ships zero JS by default, and you only add JS islands where you need them (a contact form, an animation). Faster, simpler, less to maintain.
- **Next.js is app-first.** It's what you'd pick if 6de.xyz had a dashboard, a logged-in area, server actions. It doesn't, and shouldn't — that's what `app.6de.xyz` is for.
- **Migration scope:** WordPress → Astro is "rewrite the templates as `.astro` files and copy the content." A handful of pages, a contact form, a blog index, a few service detail pages. Realistic for a weekend.
- **base44 output:** if base44 exports HTML/CSS, you can drop the markup into an Astro layout almost verbatim. If it only exports for its own runtime, treat the base44 design as the visual reference and reimplement (Claude Code can do this in an evening with the screenshots and copy in hand).

### 7.2 Project shape

```
6de-website/
├── astro.config.mjs
├── package.json
├── src/
│   ├── layouts/
│   │   └── BaseLayout.astro
│   ├── components/
│   │   ├── Header.astro
│   │   ├── Footer.astro
│   │   └── ContactForm.astro
│   ├── pages/
│   │   ├── index.astro
│   │   ├── services/
│   │   │   ├── structural.astro
│   │   │   ├── civil.astro
│   │   │   └── inspections.astro
│   │   ├── about.astro
│   │   ├── contact.astro
│   │   └── blog/
│   │       ├── index.astro
│   │       └── [slug].astro       # markdown-driven posts
│   └── content/
│       └── posts/                  # *.md files = blog posts
└── public/                         # static assets
```

Content authoring becomes: edit a markdown file → commit to git → PR → preview URL on Azure SWA → merge → live.

### 7.3 Azure Static Web Apps setup

- GitHub repo for the site (separate from the platform repo).
- Azure Portal → Create resource → Static Web App.
- Source: GitHub, branch `main`, Astro preset.
- Build command: `npm run build`. Output directory: `dist`.
- Azure SWA generates a GitHub Actions workflow on first deploy.
- DNS: add `CNAME` for `6de.xyz` (or `www.6de.xyz` + apex redirect) pointing at the Azure SWA hostname. SSL is automatic.
- Preview deploys: every PR gets a unique `<pr-N>.<random>.<region>.4.azurestaticapps.net` URL. Review before merge.

### 7.4 Contact form

WordPress has Contact Form 7 or similar. Astro has nothing built-in (it's static). Options:
- **Azure Function** (lightweight): one HTTP-triggered function that POSTs the form to your `info@6de.xyz` via Graph API or SMTP. ~$0/mo at this volume.
- **Formspree / Tally / Web3Forms**: third-party form-to-email service. $0–$10/mo. Adds a vendor.
- **Azure SWA's built-in API**: write a tiny Node function in `api/contact.js` of the SWA repo. Lives in the same deploy, free.

Recommend the third — same repo, same deploy, no extra vendor.

### 7.5 WordPress sunset

- Export all blog posts to markdown (use `wordpress-export-to-markdown` npm tool — feed it the WP XML export, get markdown out).
- Manually re-author the service pages (probably 3–5 pages, faster to rewrite than to scrape).
- 301 redirects from WP URLs to new Astro URLs: configure in Azure SWA's `staticwebapp.config.json`.
- DNS cutover: change CNAME → Azure SWA. Lower TTL beforehand for fast rollback.
- After 30 days with no traffic to the WP host: cancel the WordPress hosting.

### 7.6 Cost (Track C)

| Resource | Cost |
|---|---|
| Azure Static Web Apps | Free tier (100 GB/mo bandwidth, custom domain, SSL) |
| Domain `6de.xyz` | already owned |
| WordPress hosting (canceled after sunset) | **-$X/mo** existing savings |
| **Track C subtotal** | **$0/mo + recurring savings** |

---

## 8. Track D — Auth Unification (Azure AD SSO)

### 8.1 What this gets you

One sign-in across `6de.xyz` (if/where it has gated content), `app.6de.xyz` (the platform), and `vesta.6de.xyz` (the bridge). When your first hire arrives, you provision them in Azure AD once and they have access to everything. When they leave, you disable them once and access is gone everywhere.

### 8.2 App registrations

In the Azure AD tenant (already exists, ID `372f1dc2-…`), create three app registrations:

| App | Redirect URI | Purpose |
|---|---|---|
| `6DE Platform` | `https://app.6de.xyz/oauth/callback` | Streamlit auth |
| `6DE Website` | `https://6de.xyz/.auth/login/aad/callback` | SWA built-in auth (if any gated page) |
| `Vesta Bridge` | n/a — daemon, uses JWT validation | Platform → Vesta calls |

### 8.3 Streamlit auth

Streamlit doesn't have native Azure AD. Use `streamlit-authenticator` configured with OIDC pointing at the tenant's `.well-known/openid-configuration` endpoint, OR put App Service Authentication ("EasyAuth") in front of Streamlit so the user is already authenticated at the platform's edge. EasyAuth is the simpler path — no Streamlit code changes, just App Service config.

### 8.4 Vesta JWT validation

Upgrade the FastAPI shim's `verify()` dependency from "shared secret" to "validate JWT from Azure AD." `fastapi-azure-auth` is the standard library; ~20 lines of code change. The platform fetches an access token for the `Vesta Bridge` app's resource and includes it in the `Authorization` header.

### 8.5 Cost (Track D)

$0. Azure AD is bundled with M365.

---

## 9. Total Cost Model

| Component | Monthly |
|---|---|
| Track A (Platform) | ~$80 |
| Track B (Vesta) | $0 |
| Track C (Website) | $0 |
| Track D (Auth) | $0 |
| Domain `6de.xyz` (existing) | ~$1 amortized |
| **Total cloud spend** | **~$80/mo** |
| Existing WordPress hosting (canceled after Track C) | -$X savings |

If usage grows: B2 → B3 App Service (+$55/mo), Postgres B1ms → B2ms (+$16/mo). Realistic ceiling for a 5-person firm: **~$200/mo**. Most SaaS comparables (Monday, Asana, ClickUp at $20-40/user/mo × 5 users = $100-200/mo for *just project tracking*) hit the same number for less capability.

---

## 10. Sequencing Recommendation

### If serial: **B → A → C → D**

1. **Track B first (1 weekend).** Get the Vesta bridge live. This unblocks Sidekick V0 in the next platform session AND gives you a Cloudflare account with a tunnel set up, which is useful infrastructure regardless. Low risk, immediate value.
2. **Track A second (2–3 weekends).** Move the platform to Azure. Biggest win, biggest risk, do it when you have focused time. Sidekick V0 can ship before A lands — it just talks to vesta.6de.xyz from your local Streamlit until the Azure cutover.
3. **Track C third (1–2 weekends).** Website migration. Independent of everything else; do it when you're in the mood for design work rather than infra. base44 evaluation lives in this track.
4. **Track D last (1 weekend).** Auth unification. Wait until A and C are stable; SSO is a UX upgrade, not a blocker.

### If parallel: **B and C can run simultaneously**

A needs your full attention. B is an evening, C is design-focused. The combinations B+C in one weekend or A solo over a long weekend both work.

### Pre-flight (before any track)

- **§5.1 first**: move the platform source out of OneDrive. One evening. Unblocks everything else and stops the truncation bug from biting Session 3e and beyond.
- **Set up a GitHub remote** for the platform if not already (the Session 3e prompt assumes one).
- **Create a Cloudflare account** and add `6de.xyz` to it. Free, takes 10 minutes, prerequisite for Track B.

---

## 11. Cutover Playbooks

### A — Platform cutover

1. **T-7 days:** Azure stack provisioned, app deployed, schema migrated, sample data loaded. Smoke tested.
2. **T-3 days:** Production data dumped from local SQLite, loaded into Azure Postgres. Side-by-side validation (run a few queries on both, confirm matching).
3. **T-1 day:** Lower DNS TTL on `app.6de.xyz` to 300s (5 min).
4. **T-0 (Friday evening):** Final data sync. Stop using the local platform. Cut DNS to Azure. Smoke test from a phone (validates the cutover including SSL).
5. **T+1 to T+7:** Local platform stays running but read-only (rename `Launch_6DE_Platform.bat` so it requires a flag to launch). If Azure breaks, revert DNS.
6. **T+7:** Decommission local DBs.

**Rollback:** revert the DNS record. Local platform was untouched for the week.

### B — Vesta bridge cutover

No cutover needed — it's additive. Vesta keeps doing what it does on Telegram. The bridge just adds an HTTP entry point. The platform either uses it or doesn't.

### C — Website cutover

1. Astro site fully built, hosted on Azure SWA's default `*.azurestaticapps.net` URL. Tested.
2. Lower DNS TTL on `6de.xyz` to 300s a day in advance.
3. Update DNS to point at the Azure SWA. WordPress is still up.
4. Wait 24 hours. Check analytics, contact form, all pages.
5. If clean: cancel WordPress hosting after 30 days (gives time for indexing to catch up + lets you roll back if anything regresses).

**Rollback:** revert DNS to WordPress hosting.

### D — Auth cutover

Per-app, not big-bang:
1. Add Azure AD as a second login option on the platform. Both work.
2. Use Azure AD yourself for two weeks. Confirm no issues.
3. Disable the old login. Document the recovery path (Azure AD admin → reset password).

---

## 12. Decision Points / Open Questions

- **Astro vs Next.js for the website.** I recommended Astro for content-heavy / low-interactivity. If you want a single React component library shared between the website and the platform's eventual Next.js rewrite, Next.js is the consistency play. Either works; pick on developer experience preference.
- **base44 output format.** Need to confirm whether base44 exports clean HTML/CSS you can drop into Astro components, or whether it's a closed runtime. If the latter, treat it as design reference only.
- **Postgres tier sizing.** Burstable B1ms (2 GB RAM) is enough for single-user + small data. When the second user arrives, watch CPU credit consumption — may need to bump to B2ms.
- **Backup posture.** Azure Postgres has automated backups (7-day retention on Burstable). Want point-in-time recovery beyond 7 days? Need to manually push DB dumps to Blob on a cron.
- **Disaster recovery for office-PC-as-Vesta-host.** If the PC dies, Vesta is down until replaced. Acceptable risk today; revisit when Vesta becomes load-bearing for client-facing work.
- **Engineering documents path.** Stay on OneDrive vs. eventual migration to SharePoint document library with proper API access vs. eventual Blob with indexed structure. Deferred but worth noting as a future Track E.
- **VPN / IP allowlisting.** Do you want the platform reachable from the public internet, or only from your home/office IPs (plus Cloudflare for the tunnel)? Azure App Service Access Restrictions are free. Recommend public + Azure AD auth gate, not IP allowlist (IP allowlist breaks mobile + travel).

---

## 13. What This Doesn't Solve (Honest Limits)

- **Mobile UX** is still Streamlit-on-a-phone, which is mediocre. Real mobile fluency requires picking the 2–3 pages you actually use mobile (probably: open a project, log time, glance at the dashboard) and rebuilding them as a Next.js mini-app on `app.6de.xyz/m/*`. Not in this roadmap; tracked as a future effort.
- **Vesta still depends on the office PC being on.** Single point of failure remains. The Cloudflare Tunnel removes the network exposure problem, not the hardware-availability problem.
- **No offline mode.** Lose internet, you lose the platform. Not solved by any hosting move; would require a PWA + sync layer (large project).
- **No multi-region failover.** Single Azure region (recommend East US 2 for proximity to Miami). If the region has an outage, the platform is down. Acceptable at this scale.
- **No real CI/CD yet.** Each track adds GitHub Actions for its own deploy, but coordinated multi-service deploys (e.g. "I changed both the platform and the Astro site for a shared design tweak") would benefit from a monorepo + Nx/Turborepo eventually. Not in scope; revisit at 3+ services.

---

## 14. Sibling-Memo Cross-References

This roadmap deliberately doesn't re-litigate decisions made in the sibling memos:

- **Project pipeline data model and workflow automations** → see [Panamerican_Monday_Deep_Dive.md](../Panamerican_Monday_Deep_Dive.md). Those features land in the platform regardless of where it's hosted.
- **Vesta Sidekick architecture and per-page context plumbing** → see [Odoo_Deep_Dive.md §4](./Odoo_Deep_Dive.md). The Sidekick is the consumer of the Track B bridge.
- **Engineering calculator native ports** → see the Single-Ply Attachment calc that landed in `modules/calculator/`. Pattern stays the same on Azure (Postgres-backed metadata, Blob-backed calc memo PDFs once Sign integration arrives).

---

## Appendix A — Cloudflare Tunnel one-shot setup

```powershell
# Install cloudflared on the office PC
winget install --id Cloudflare.cloudflared

# Authenticate (opens browser)
cloudflared tunnel login

# Create the tunnel
cloudflared tunnel create vesta-bridge

# Route DNS through Cloudflare (requires 6de.xyz on Cloudflare nameservers)
cloudflared tunnel route dns vesta-bridge vesta.6de.xyz

# Edit config — replace <TUNNEL-ID> with the one printed by `create`
notepad $env:USERPROFILE\.cloudflared\config.yml
# Contents:
#   tunnel: <TUNNEL-ID>
#   credentials-file: C:\Users\Juan\.cloudflared\<TUNNEL-ID>.json
#   ingress:
#     - hostname: vesta.6de.xyz
#       service: http://localhost:8765
#     - service: http_status:404

# Install as Windows service (auto-start on boot)
cloudflared service install

# Verify
cloudflared tunnel info vesta-bridge
```

## Appendix B — FastAPI shim deployment

```powershell
# On the office PC, after cloning a small repo with vesta_api.py
python -m pip install fastapi uvicorn[standard]

# Set the shared secret (use any long random string)
[Environment]::SetEnvironmentVariable("VESTA_SHARED_SECRET", "<long-random-string>", "User")

# Run interactively to verify
uvicorn vesta_api:app --host 127.0.0.1 --port 8765

# When happy, install as a Windows service via NSSM
nssm install vesta-api "C:\Python311\python.exe" "-m uvicorn vesta_api:app --host 127.0.0.1 --port 8765"
nssm start vesta-api

# Smoke test from anywhere
curl https://vesta.6de.xyz/queue -H "Authorization: Bearer <secret>"
```

## Appendix C — pgloader sketch

```bash
# On any machine with pgloader installed
cat > migrate.load <<'EOF'
LOAD DATABASE
  FROM sqlite:///path/to/platform.sqlite
  INTO postgresql://user:pass@<azure-host>:5432/platform
WITH include drop, create tables, create indexes, reset sequences,
     workers = 4, concurrency = 1
CAST type datetime to "timestamp with time zone",
     type json to jsonb;
EOF
pgloader migrate.load
```
