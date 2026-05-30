# 6DE Company Platform — Goal v1: From Local Demo to Cloud-Native Firm OS

**Date:** 2026-05-12 (updated 2026-05-12 — SharePoint + AI integration; 2026-05-12 — phase reordering per Juan's approval)
**Author:** Synthesis of six parallel research streams (`_research/platform_v2_*.md`), extended with SharePoint document-layer and AI-capabilities sections per Juan's expanded scope
**Status:** **APPROVED 2026-05-12.** Phase 0 in progress.
**Supersedes:** Nothing. Complements `_research/ROADMAP_v1.md` (Session 33).

**Change log (this revision):**
- **Approved by Juan 2026-05-12.** Section 10 item #4 (AI Phase 1 trigger) softened: "Juan ships at his discretion; hire #2 = hard trigger if it hasn't happened yet."
- **Phase ordering reversed at Juan's direction:** the hosting / Postgres / cloud-deploy work is moved to the END, not the second step. Everything else is built and debugged locally first. Phases are now numbered by execution sequence.
- **New Phase 7: Chrome-connector review & debug pass** inserted after all feature work, before the cloud flip. Full smoke test of every page, workflow, Graph call, Stripe path (Stripe test mode + Cloudflare Tunnel for webhooks), Telegram alert.
- **Section 11 trade-offs** added: HTTPS for Stripe webhooks (Cloudflare Tunnel), SharePoint redirect URIs (localhost dev → prod URL at hosting flip), no-team-feedback risk for 4–6 months.
- **Cutover plan** added to Phase 7 (2–4 week Render staging period before flip, same $7/mo cost) and Phase 8 (DNS-ahead-of-time, prod redirect URI, Stripe webhook secret swap, data-migration decision, maintenance-window discipline, post-cutover smoke).
- **Section 4a Timeline Anchors** added: May–Oct 2026 = Phases 0–6/7; Oct–Nov 2026 = Phase 7 + staging; Nov 2026 = Phase 8 flip; Dec 2026–Feb 2027 = solo buffer period; Feb–Mar 2027 = first hire.

---

## 0. The Goal in One Paragraph

By **2026-12-31**, the 6DE Company Platform is a cloud-hosted, mobile-usable, multi-user ERP that 6th Degree Engineering actually runs the business on — invoices, permits, projects, time, accounting, calcs — with no daily reason to open Excel, Outlook, or a folder browser to do firm work. The platform charges clients, sends emails, tracks deadlines, files generated documents to SharePoint, and notifies Juan on his phone. It is ready for hire #2 to log in with their own account on day one of their employment, with a knowledge assistant ready to answer "how do we usually handle X?" from internal precedent. The desktop calc engine remains the source of structural truth and bridges into the platform read-only.

**Build strategy:** build and debug everything locally with SQLite first. Flip to Postgres + Render only after Chrome-connector smoke pass. This trades 4–6 months of no-team-feedback risk for the certainty that the cloud flip is a flip, not a rebuild.

---

## 1. North-Star Outcomes (Measurable)

| # | Outcome | How we measure | Target |
|---|---|---|---|
| 1 | **Mobile-usable** | Juan can do AR check, log time, mark a proposal accepted, photograph a site, and look up a permit on his iPhone without leaving the platform | All 5 workflows complete on a phone in <30 seconds each |
| 2 | **Cloud-hosted** | Platform reachable at `app.6thde.com` (or similar) from any internet connection, with TLS, no Juan-desktop dependency | URL up, auth works, SQLite-on-OneDrive eliminated |
| 3 | **Multi-user-ready** | A second user account logs in independently, sees their own time entries, is denied Accounting | Audit log records denied attempt; concurrent edits on same project don't corrupt data |
| 4 | **Money flow closed** | Client receives a Stripe hosted-invoice link, pays via ACH, platform marks paid automatically, Telegram alerts Juan | End-to-end test with one real client invoice; latency <60s from pay to Telegram ping |
| 5 | **Excel-free week** | Juan goes 7 calendar days without opening any `.xlsm` or `.xlsx` for firm operations | Self-reported; tracked via activity log absence of "imported_excel" events |
| 6 | **Permit moat operational** | All active permits tracked, expiration alerts fire to Telegram, Permit Contacts populated | `permits` row count >0, `contacts` populated, Telegram alert verified on a test 30-day-out expiry |
| 7 | **Engineering moat operational** | Engineering Section live with Code Library, Suggested Codes per project, calc-output drill-down | All 3 tabs render against `common.db`; 38+ unique codes indexed |
| 8 | **SharePoint as document store** | Every generated PDF lands in `/Projects/{ProjectNumber}_{ProjectName}/{Calcs\|Drawings\|Permits\|Billing\|Correspondence}` via Graph upload | No human-facing PDFs in Render/Azure blob; SharePoint URLs render correctly in-app |
| 9 | **Knowledge assistant for hires** | A new engineer can ask "show me past calcs for masonry shear walls in coastal flood zone" and get grounded answers with SharePoint citations | Eval harness passes ≥90% on the 50-question ground-truth set |

If at end of year outcomes 1–8 are green, this goal is met. Outcome 9 is conditional on Juan opting in (per §10 item #4 amended) or hire #2 landing within the year.

---

## 2. Constraints & Decisions Made

| Constraint | Decision | Source |
|---|---|---|
| Multi-device access | Phone + tablet **must work fully** | User answer 2026-05-12 |
| Where the platform runs | **Cloud-hosted** (Render → Azure trajectory) | User answer 2026-05-12 |
| User scope | Single user now; plan for **3–5 future hires** in 12–18 months; no client portal ever | User + ROADMAP_v1 J=NEVER |
| PM patterns | Status pills, formula columns (as SQL views), automations engine, activity feed, my-work view. Discard kanban/Gantt/mirror columns | User ask + business audit §3 |
| Online payments | **Stripe ACH-first** | User ask + integrations research |
| Calc engine | Stays local; platform reads `common.db` via lazy bridge; nightly snapshot sync | Data-layer research §4 |
| Human-facing documents | **SharePoint** via Graph, not Render/Azure blob | User direction |
| AI pattern | **AI proposes, human approves, human submits.** No auto-seal, no auto-send | User direction |
| AI content boundary | Do NOT index copyrighted codes (AISC, ACI, IBC, ASCE 7, FBC, ADM, TMS, NDS) | User direction |
| AI cost governance | Per-user monthly token budget, hard-capped | User direction |
| **Build strategy** | **Local-first.** All feature work ships against local SQLite; cloud flip happens after Chrome-connector debug pass | User direction 2026-05-12 |

---

## 3. The Recommended Stack

| Layer | v1 (today) | v2 (target end-2026) | Why |
|---|---|---|---|
| **UI — desktop** | Streamlit on `localhost:8502` | Streamlit, dockerized, behind TLS | No rewrite |
| **UI — mobile** | None | Streamlit PWA wrap → FastAPI+HTMX companion later if needed | Split-stack |
| **Auth** | `streamlit-authenticator` + YAML | `streamlit-authenticator` + `users` table → Entra ID SSO when 5th user | Migrate creds now; SSO later |
| **DB (OLTP)** | SQLite on OneDrive | **Neon Postgres** ($0 → $19/mo Launch) | True Postgres, branching, PITR |
| **DB (vector)** | n/a | **pgvector on Neon** (same DB) | Free with Neon; HNSW scales fine |
| **Hosting** | Local Streamlit | **Render Starter** ($7/mo) → **Azure App Service B1** + Azure DB for PG ($80–90/mo) at SSO/compliance trigger | Cheap start, scale-ready exit |
| **Repo** | OneDrive folder | **Private GitHub repo** | Cloud deploy demands it |
| **Payments** | None | **Stripe Hosted Invoicing** (ACH 0.8% capped $5) | Lowest fee on $5K–$50K invoices |
| **Alerts** | None | **Telegram** via `@HestiaCastilloBot` + Outlook SMTP | Reuse Hermes pattern |
| **Email/Calendar** | Manual | **Microsoft Graph** (free with M365) | Email auto-file, calendar push |
| **Document store** | OneDrive folders, manual | **SharePoint via Graph API** — `msgraph-sdk-python` | Already in tenant; permissions inherit |
| **LLM API** | n/a | **Anthropic Claude API direct** + prompt caching | Best engineering quality |
| **Embeddings** | n/a | **OpenAI text-embedding-3-small** | Cheapest production-quality |
| **Eval harness** | n/a | Claude-as-judge over 50-Q ground-truth | Gate model upgrades on ≥90% |
| **Calc engine** | Local exe + local `common.db` | **Unchanged.** Nightly snapshot to Postgres | Don't move what works |
| **Notifications** | None | Telegram primary; Outlook email secondary; skip iOS web push | Match how Juan gets alerts |

---

## 4. The Phased Roadmap (Execution Sequence)

**Twelve phases. Numbered by execution order.** Each has an explicit gate. One session ≈ 4 focused hours.

The original phase plan executed Postgres+Render second (right after foundation). Juan reversed this on 2026-05-12: build and debug everything locally first, flip the cloud switch as the final step before AI work begins. This trades the convenience of "every commit is live" for the certainty that the production cutover is a one-day flip rather than a 4-month live-debug session.

---

### Phase 0 — Cleanup + Auth Recovery (next session — IN PROGRESS)
**Goal:** Close every empty-page bug. Restore working auth credentials. Cross from "demo" to "useful daily" on local Streamlit.

**Scope (per business audit §5):**
1. B1 — Calculator bridge column rename + pull `client_name`/`code_basis` *(already shipped in S33)*
2. B2 — Financials `Styler.rename` reorder *(already shipped in S33)*
3. B7 + I2 — Seed Juan as `employees.id=1` on DB init
4. B5 + I3 — Collapse `opportunities` into `proposals`; rewire CRM page
5. B4 + I1 — Wire `activity_log` writes into every importer + CRUD path
6. B6 + I4 — `Permitting Contacts.xlsm` importer
7. **Auth recovery** — locate auth YAML, generate fresh bcrypt for primary user, document new password + regen snippet, add Phase 5 TODO to replace YAML with `users` table

**Gate:** Localhost:8502 smoke-tests pass on all 10 pages (Home + 9 numbered). No traceback. No `$0` cards where data exists. Home Recent Activity shows import events. Juan can log in with the reset password.

---

### Phase 1 — Cloud Prerequisites (no deploy)
**Goal:** Every prerequisite for cloud deploy in place. No actual deploy yet.

**Scope:**
1. **Private GitHub repo.** Strip OneDrive paths; calc engine `common.db` reference stays env-var driven via `SIXDE_CALC_DB`. Initial commit captures S33 + Phase 0 work. Add `.github/workflows/test.yml` running existing smoke tests on push.
2. **Fix `config.py` capital-J path** so default works on this user.
3. **Lazy-load calc-bridge.** Imports become lazy + guarded; missing `SIXDE_CALC_DB` produces a clear "Calc engine not reachable" message instead of crashing the page.
4. **Write a Dockerfile.** Multi-stage `python:3.12-slim`. Verify `docker run -p 8502:8502` works locally.
5. **Add `DB_BACKEND` env var seam** in `db/__init__.py`. Postgres branch unimplemented; the seam is the prep work.

**Gate:** `docker run` boots the app against existing SQLite. GitHub Actions test workflow green. Code in private repo. Calc bridge degrades gracefully when env var is unset.

---

### Phase 2 — SharePoint Document Layer
**Goal:** Generated PDFs land in SharePoint via Graph. Every record that produces a document carries a SharePoint pointer. Develop against live tenant from localhost.

**Session 2a — Graph + SharePoint scaffold (~4 hours):**
1. **Entra ID app registration.** Redirect URI `http://localhost:8502/` for dev; add production URL at Phase 8 hosting flip. Delegated scopes: `Sites.ReadWrite.All`, `Files.ReadWrite.All`.
2. **OAuth 2.0 device-code flow** for Juan's M365. Refresh token persisted in `users.ms_graph_refresh_token` (Fernet-encrypted, key in env).
3. **`modules/documents/sharepoint.py`** wraps `msgraph-sdk-python`:
   - `ensure_project_folder(project_number, project_name) -> drive_item_id` — creates `/Projects/{NUM}_{NAME}/{Calcs|Drawings|Permits|Billing|Correspondence}` if missing
   - `upload_bytes(...)` — small files <4MB
   - `upload_large(...)` — chunked via `createUploadSession`, 5MB chunks
   - `get_link(item_id)`, `delete(item_id)`, `list_folder(...)`
4. **Filename sanitization** at boundary: strip `< > : " / \ | ? *`, trim whitespace, collapse spaces, cap per-segment 128 chars, cap full path 255. 20 adversarial unit tests.
5. **Schema deltas on `documents`:** `sharepoint_item_id`, `sharepoint_web_url`, `sharepoint_drive_id`, `sha256`. Re-upload of identical content (same sha256, same `(project_id, category, filename)`) returns the existing item.

**Session 2b — Wire-up + UX (~4 hours):**
6. **Per-project Documents tab** in `1_Projects.py`. Category-grouped, "Open in SharePoint" links, PDF thumbnails.
7. **Backfill scan.** `scripts/scan_existing_project_docs.py` walks existing OneDrive `01_Active Projects/<job> - <name>/` once, indexes file metadata into `documents` without uploading.
8. **Test harness.** `tests/test_sharepoint.py` covers folder idempotency, filename sanitization, chunked upload, 429 throttle retry.

**Gate:** Test PDF uploads to `/Projects/260512_TestProject/Billing/`, returns working SharePoint URL, `documents` row links back. Re-running returns same URL. 50-char-filename-with-illegal-chars uploads sanitized.

---

### Phase 3 — Mobile + Email (PWA + Graph)
**Goal:** Phone-usable; email is first-class data flow. Reuses Graph OAuth from Phase 2.

**Session 3a — PWA wrap + mobile polish (~3 hours):**
1. **Streamlit PWA manifest** + install prompt copy.
2. **Phone-specific CSS** — narrow widths hide power-user columns, stretch metric cards, hide sidebar by default.
3. **5 mobile workflow buttons** on Home: AR check, Log Time, Mark Proposal Accepted, Site Photo, Open Permit.
4. **`st.camera_input`** site-photo flow — pick project → snap → upload to SharePoint `Drawings/` with GPS in EXIF.

**Session 3b — Microsoft Graph email + calendar (~4 hours):** (token already exists from Phase 2)
5. **Inbox watcher** polls Graph; surfaces unfiled project-related emails on Home.
6. **Calendar push** — permits/recerts/milestones become Outlook calendar events.
7. **Send invoices via Graph** (deferred until Phase 6 ships invoice PDF generation — Graph send method now defined; called from Phase 6).

**Gate:** Juan installs PWA on phone home screen, logs time on the train, snaps a job-site photo (lands in SharePoint), inbox-watcher alerts on unfiled email. Outlook calendar shows next 3 permit expirations.

---

### Phase 4 — Engineering Moat (Documents + Deadlines + Engineering Section)
**Goal:** The two features no commercial AE tool offers for this market.

**Session 4a — Documents + Deadlines + Automations (~4 hours):**
1. **Document hub continuation** — extend Phase 2 backfill to `02_Completed Projects/` and `99_Templates/`. New `subconsultant_deliverables` table.
2. **Universal deadline engine (ROADMAP A).** New `compliance_deadlines` table unifying permit expirations, recert CCAs, milestones, license renewals. Single `My Deadlines` view + Telegram + Outlook calendar push.
3. **Automations engine.** `automations(trigger, condition, action)`. Initial rules: proposal accepted → create project + 50% deposit draft invoice; invoice past due_date → status=overdue; permit cca_deadline < 30d → Telegram alert; transaction regex-matches job number → link.

**Session 4b — Engineering Section (~6 hours):**
4. Replace sidebar `Calculator` with `Engineering` umbrella per `ENGINEERING_SECTION_DESIGN.md`.
5. Five tabs: Calculators, Code Library, Suggested Codes per project, Standards Tracker, Practice Library.
6. Seed `codes` table from 38 standards already cited in `common.db.project_outputs.standards_cited`.
7. Lookup `structure_type → expected codes` from historical empirical patterns.

**Gate:** Engineering tab shows codes that should apply for project's structure_type, with checkmarks for codes cited and red flags for missing standards.

---

### Phase 5 — RBAC (conditional on hire #2 during this stretch)
**Goal:** The platform supports more than one human, securely.

**Trigger:** Hire #2 lands during the local-build stretch. If hire happens before this phase, fast-track it; if not, this phase ships immediately before Phase 7 (debug pass) regardless.

**Also closes the YAML auth TODO from Phase 0.** This is where the `users` table replaces `auth_config.yaml` as the source of truth.

**Session 5a — RBAC foundation (~4 hours):**
1. Add `users`, `role_permissions`, `audit_log`, `locks` tables.
2. **Port `auth_config.yaml` → `users` table; archive YAML to `_archive/auth_config_v1.yaml`.** This is the documented migration target referenced from Phase 0's auth recovery.
3. `streamlit_app/auth.py`: add `current_user()`, `require_role()`, `has_permission()`.
4. Wire `require_role(["owner","accountant"])` to Accounting + Financials write paths.
5. Backfill `created_by_user_id=1` on all existing rows.

**Session 5b — Full coverage (~4 hours):**
6. `created_by/updated_by/assigned_to` columns on all named tables.
7. Optimistic-concurrency `updated_at` clause on every UPDATE.
8. `locks` table for proposal-edit + invoice-edit.
9. `activity_log.user_id` wired everywhere (already partial from Phase 0; complete here).
10. Row-level filter on Timekeeping + Expense "my X" views.
11. `audit_log` writes on login_ok, login_fail, permission_denied.

**Gate:** Second user added via User Management page; logs in independently; sees only own timesheet; denied Accounting with audit-log entry; concurrent edits don't corrupt.

---

### Phase 6 — Money Flow (Invoice PDF + Stripe + Telegram)
**Goal:** Close the invoice → cash loop end-to-end. Invoice PDFs land in SharePoint via Phase 2 plumbing.

**Session 6a — Invoice PDF (~4 hours):**
1. One-screen invoice lifecycle in `2_Billing.py`. `weasyprint` or `reportlab`.
2. PDF generated in memory, uploaded via `sharepoint.upload_bytes(project, "Billing", filename, pdf_bytes)`. No local file.
3. State machine: `draft → sent → paid → void`. Buttons gated per state.
4. .eml fallback if Graph send fails — uploaded to SharePoint `Correspondence/`.

**Session 6b — Stripe + Telegram (~4 hours):**
5. Stripe customer + invoice + hosted link per integrations research §"Stripe Wire Pseudocode."
6. **Stripe webhook listener as a FastAPI sidecar.** Local dev needs HTTPS — **set up Cloudflare Tunnel** (free, persistent named hostname, recommended over ngrok which rotates URLs). Webhook updates `invoices.paid_date` + writes `payments` row + writes receipt PDF to SharePoint `Billing/`.
7. **Telegram notify shim.** `modules/notify/telegram.py` reuses `@HestiaCastilloBot`. Fires on: invoice paid, recurring expense due-soon, AR aging 60+ crossing, Z sync results.
8. PCI-SAQ-A acknowledgment documented.

**Gate:** Real $1 test invoice via Stripe Hosted (test mode); PDF in SharePoint; paid from personal email; platform marks paid within 30s; Telegram alert fires; receipt PDF in SharePoint.

---

### Phase 7 — Chrome-Connector Review & Debug Pass *(NEW per Juan)*
**Goal:** Full smoke test of every page, every workflow, every external integration. Catch everything before flipping hosting.

**Why this exists:** Phases 0–6 ship 4–6 months of feature work against local SQLite. The cloud cutover (Phase 8) should be a flip, not a debugging session. This phase is the contract that says the local app is correct before it goes public.

**Scope:**
1. **Chrome connector** drives a scripted run through every page and workflow:
   - Home dashboard — every metric, every alert, every Quick Action
   - Projects — list, filter, edit, milestone create, Calculations tab, Documents tab
   - Billing — proposal CRUD, state transitions, invoice PDF, send-via-Graph, SharePoint landing
   - Permits — permits list, contacts, expiration alerts
   - CRM — pipeline metrics, client edits
   - Timekeeping — time entry, weekly view, employees
   - Financials — all four tabs (AR aging, profitability, utilization, forecast)
   - Bids — list, status
   - Calculator → Engineering (per Phase 4 rename)
   - Accounting — transactions, cashflow, recurring, categorization
2. **External integration smoke:**
   - **SharePoint:** upload a test file from each PDF-generating page; verify URLs render; verify permissions inherit
   - **Microsoft Graph:** send a test email via Graph; verify calendar event creation; verify inbox-watcher matches
   - **Stripe:** end-to-end test-mode invoice → hosted link → pay → webhook → DB update → Telegram alert. **Verify Cloudflare Tunnel survives a 30-minute session.**
   - **Telegram:** all alert types fire; rate-limit handling on burst
3. **Bug capture.** Every defect found gets a B-number (continuing from B23) and a one-line root cause. Critical/High get fixed before Phase 8.
4. **Performance pass.** Each page <2s cold load on Juan's desktop. SQL EXPLAIN on any query >100ms. Add indexes if needed.
5. **Static security pass.** Run `pip-audit` for CVEs in dependencies. Review every `unsafe_allow_html=True` for actual user-content injection paths.

**Gate:** Zero critical/high bugs open. Performance budget met. Cloudflare Tunnel + Stripe webhook stable over a one-hour session. Juan signs off in writing (commit message or session note).

**Cutover plan (added 2026-05-12).** Don't treat the November flip as a single-day event. **Two to four weeks before the target flip date, deploy a Render staging environment pointed at a separate Neon database** and use it as the daily working environment, not localhost. The first week of staging-use surfaces "works on my machine" bugs (path separators, env-var fallbacks, file-permission assumptions). The second week surfaces network-edge bugs (Graph API latency, SharePoint throttling under burst, intermittent webhook delivery, DNS edge cases). By the actual flip, the system has been running on Render for weeks and the cutover is a database swap + DNS change, not a discovery exercise. **Cost:** same $7/mo Render Starter — no additional spend; the staging instance can be torn down once Phase 8 lands or kept as a permanent staging tier.

---

### Phase 8 — Postgres + Render Deploy *(FINAL STEP, not the second)*

> **⚠️ SUPERSEDED 2026-05-29 — hosting target changed to Azure.** The Render + Neon
> plan described in this section was the original Phase 8 design. The canonical
> production target is now **Azure App Service for Linux** + **Azure Database for
> PostgreSQL flexible server** (`sixde-platform-db-jc`) + **Azure Blob Storage** +
> **Azure Key Vault**, pulling the container image from **Azure Container Registry**
> (`sixdeacrjc.azurecr.io`). See `Feature_Research/Hosting_and_Integration_Roadmap.md`
> for the current provisioning plan. The Render/Neon steps below are retained as a
> historical record of the original decision and should not be executed as written.

**Goal:** Platform lives on the internet, real Postgres backend. SQLite-on-OneDrive eliminated.

**Acceleration trigger:** If hire #2 lands while Phases 2–6 are still in progress, Phase 8 jumps the queue ahead of the remaining feature work. Hire #2 needs cloud access; hire #2 doesn't need every feature shipped.

**Session 8a — DB migration (~4 hours):**
1. Provision **Neon Postgres** (US-East-2, free tier). `dev` and `prod` branches.
2. **Enable `pgvector`** on prod (`CREATE EXTENSION vector;`).
3. Translate `db/schema.sql` to Postgres dialect:
   - `AUTOINCREMENT` → `GENERATED ALWAYS AS IDENTITY`
   - `datetime('now')` → `NOW()`
   - `julianday(...)` → `EXTRACT(DAY FROM ...)` (in `v_ar_aging`, `v_cashflow_monthly`)
   - `INSERT OR IGNORE` → `INSERT ... ON CONFLICT DO NOTHING`
   - 0/1 ints → `BOOLEAN`
4. Migrate ~221 SQL calls in `modules/` + ~49 in pages. Implement `DB_BACKEND=postgres` branch (psycopg3 + `@st.cache_resource`).
5. One-shot `scripts/migrate_sqlite_to_postgres.py`. Idempotent. Validate row counts.

**Session 8b — Cloud deploy (~4 hours):**
6. Deploy to Render Starter ($7/mo). Connect GitHub. Env vars via Render dashboard.
7. Custom domain `app.6thde.com`. Render handles TLS.
8. **Add production redirect URI** to Entra ID app registration (was localhost-only since Phase 2).
9. **Reissue Cloudflare Tunnel config** to point at Render's webhook endpoint (was pointing at localhost).
10. Nightly calc-snapshot job. Hermes cron runs `scripts/sync_calc_snapshot.py` at 02:00 UPSERTing into `calc_*_snapshot`.
11. Telegram alert on every successful deploy.
12. **First DR drill.** Restore yesterday's Neon backup to a `dev` branch; verify a sample of rows.

**Gate:** Juan opens `app.6thde.com` on his phone, logs in, sees real data. SQLite `platform.db` archived. Nightly snapshot ran successfully. DR drill passed.

**Cutover checklist (added 2026-05-12 — pre-flight, run in order):**
- [ ] **DNS for `app.6thde.com` set up 1–2 weeks early** so SSL provisioning + propagation has time to settle.
- [ ] **Add production redirect URI** `https://app.6thde.com/` to the existing Entra ID app registration alongside the `http://localhost:8502/` dev URI already in place. No re-registration, no token invalidation.
- [ ] **Stripe live-mode webhook signing secret is different from test mode** — env-var swap (`STRIPE_WEBHOOK_SECRET`, `STRIPE_SECRET_KEY`) is part of the cutover, not a separate task. Both must rotate in lockstep with the test-mode → live-mode account flip.
- [ ] **Data-migration decision (explicit before cutover):** does the local SQLite data move to production, or does production start clean with seed/reference data only? **Default answer: clean start with seed data** (clients, fee_schedule, categorization_rules, employees row for Juan). Local SQLite remains as historical reference.
- [ ] **Maintenance window communicated and scheduled** — even though Juan is currently the only user, the discipline establishes the pattern for when there are more.
- [ ] **Post-cutover smoke test:** re-run the Phase 7 Chrome-connector test plan against production within the first hour. Any regression vs. staging = roll back the DNS, investigate, redo.

---

### Phase 9 — Cloud Scale / Azure + SSO (triggered by hire #5 or first SOC2 ask)
**Goal:** Compliance-ready posture; central identity.

1. Migrate hosting **Render → Azure App Service B1** + **Azure DB for PostgreSQL B1ms** (~$80–90/mo).
2. **Entra ID SSO** via OIDC. Replace `streamlit-authenticator` login form with MSAL redirect.
3. On first SSO login: match by email, set `users.sso_subject`, null `password_hash`.
4. Keep password path alive for external Accountant only.
5. Postgres RLS policies as defense-in-depth.
6. Quarterly DR drill cadence formalized.

**Gate:** All internal users authenticate via Microsoft. MFA enforced via Entra Conditional Access. Test PITR restore completes.

---

### Phase 10 — AI Phase 1: Knowledge Chat / RAG (Juan opts in; hard trigger = hire #2)
**Goal:** Read-only assistant grounded in 6DE precedent.

**Trigger (per §10 item #4 amended 2026-05-12):** Juan ships at his discretion. Hire #2 is the hard trigger if Juan hasn't shipped it before then.

**Prerequisites:** Phase 2 (SharePoint), Phase 5 (RBAC for per-user caps), Phase 8 (Postgres + pgvector).

**Session 10a — Ingestion pipeline (~4 hours):**
1. **Source inventory.** SharePoint sites/folders to index:
   - `Projects/*/Calcs/` — past calc packages
   - `Projects/*/Correspondence/` — client correspondence
   - `99_Templates/` — proposal templates, demand letters, SOPs
   - `Technical Reference/<discipline>/*.md` — internal design memos
   - `99_SOPs/`
   - **Excluded** (do-not-index list, glob match): `AISC*.pdf`, `ACI*.pdf`, `IBC*.pdf`, `ASCE-7*.pdf`, `FBC*.pdf`, `ADM*.pdf`, `TMS*.pdf`, `NDS*.pdf`; client-confidential folders; HR-tagged subfolders.
2. **Scheduled ingestion** — daily Hermes cron at 03:00. Graph walk → mtime-based diff → `pypdf` + recursive text splitter (1000 tokens / 100 overlap) → OpenAI `text-embedding-3-small` → `document_chunks(id, document_id, chunk_index, content, embedding vector(1536), visibility_role, created_at)`.
3. Tagging: `document_id` → `documents.sharepoint_web_url` for citations; `visibility_role` default `all`, tightened for HR/financial; `content_type` (calc/correspondence/sop/proposal_template/memo).
4. **CI test** asserts no `document_chunks` rows reference a do-not-index filename. Quarterly audit.

**Session 10b — Chat UI + retrieval (~4 hours):**
5. New page `0_Assistant.py` (first sidebar position).
6. Retrieval: user query → embed → top-K=8 cosine search filtered by `visibility_role IN (user's roles)` → assemble context → Claude Sonnet with prompt caching on system prompt + retrieved context.
7. Citation rendering: numbered citations link to SharePoint URL of source.
8. **Per-user cost cap.** New `ai_quota(user_id, period_start_date, dollar_cents_used, hard_cap_cents)`. Default $5/user/day. Owner adjustable. Pre-flight estimate; hard stop at 100%, soft warning at 80%.

**Session 10c — Eval harness + gate (~3 hours):**
9. **`evals/rag_eval_set.jsonl`** — 50 ground-truth Q&A pairs across calc precedent, proposal language, SOP recall, code-basis history, deadline rules, vendor contacts. Authored by Juan.
10. `scripts/run_rag_eval.py` runs the 50 questions, grades via Claude-as-judge structured output (`{retrieval_correct, answer_correct, hallucination, citation_valid}`).
11. CI gate: ≥90% answer-correct, 0% hallucination to merge model/prompt changes.

**Cost estimate (5 users):** ~$18–80/mo at projected usage with caching; $550/mo absolute ceiling.

**Gate:** Eval ≥90%. Test query "what codes do we cite for a Miami-Dade footing in coastal flood zone?" returns answers with working SharePoint citations.

---

### Phase 11 — AI Phase 2: Workflow Assists (trigger: Phase 10 stable 60+ days)
**Goal:** AI drafts content in-context. Human always edits and submits.

**Non-negotiable pattern:**
1. AI output goes into an **editable field**, not a confirmation.
2. Draft shown alongside source/context.
3. Explicit user submit. No auto-send.
4. `audit_log` records: AI prompt, AI output, user's edited version, submission.
5. **PE seal never auto-applied.** Any sealing routes through IdenTrust manual-approval queue.

**Five workflows, one session each:** calc package summary drafts, invoice/bid line-item drafts, permit application narratives (draft for human to paste — not auto-submission), client correspondence + demand letters (Word draft → human sends), timesheet anomaly detection.

**Cost estimate:** ~$30–60/mo additional.

**Gate:** Each workflow ships with audit-log entry per use. 4-week spot check: ≥18/20 random samples "useful with light edits."

---

### Phase 12 — AI Phase 3: Agentic (far future — 2027+; trigger: Phase 11 stable 6+ months, Juan opts in)
**Goal:** Multi-step agents handle structured workflows end-to-end. Optional and aggressively gated.

**Possible scope:** "Onboard new project" agent, permit deadline monitoring agent, AR follow-up draft agent.

**Guardrails (non-negotiable):** scoped tool whitelist (no `db.execute`, no SharePoint delete, no Stripe writes, no Outlook send, no IdenTrust sign); step-by-step audit; 20-turn cap per run; $1 cost cap per run; single submit at end (drafts only); kill switch in User Management.

**Cost estimate:** budget $100/mo, hard cap $200/mo.

**Gate:** "Onboard new project" agent produces all drafts correctly in 10/10 trials. Juan opts in via explicit User Management toggle.

---

## 4a. Timeline Anchors *(informational, not commitments)*

Added 2026-05-12 alongside the cutover-plan additions. Calendar guidance, not contractual deadlines — phase gates still take precedence.

| Window | Activity |
|---|---|
| **May–October 2026** | Phases 0–6 (or 0–7 if hire #2 doesn't materialize early) |
| **October–November 2026** | Phase 7 — Chrome-connector debug pass + **2–4 week Render staging period** (per Phase 7 cutover plan) |
| **November 2026** | Phase 8 — hosting flip. Aim for mid-month so DNS/SSL has full propagation buffer before any external use |
| **December 2026 – February 2027** | Buffer period of solo production use. Catch any latent issues; build operational muscle memory; refine alerts and dashboards under real conditions before adding human dependents |
| **February–March 2027** | First hire onboarding (triggers Phase 5 if not already done, plus AI Phase 1 hard trigger per §10 item #4 amended) |

The buffer period exists precisely so that hire #2's first day isn't also "the day we discover the production webhook config is wrong." Solo-Juan operations through that window will surface anything the Chrome-connector pass missed.

---

## 5. Dependency Graph (updated for new sequence)

```
Phase 0 (cleanup + auth) ──► Phase 1 (cloud prereqs, no deploy) ──► Phase 2 (SharePoint) ──┐
                                                                                            ├──► Phase 3 (mobile + Graph)
                                                                                            ├──► Phase 4 (eng moat)
                                                                                            └──► Phase 6 (money) ──┐
                                                                                                                   │
                                                                       Phase 5 (RBAC) ◄─ hire #2 trigger           │
                                                                       (jumps queue if early)                      │
                                                                                                                   ▼
                                                                              Phase 7 (Chrome-connector debug pass)
                                                                                                                   │
                                                                                                                   ▼
                                                                                          Phase 8 (Postgres + Render — FINAL)
                                                                                                                   │
                                                                                                                   ▼
                                                                                          Phase 9 (Azure + SSO) ◄─ hire #5 OR SOC2
                                                                                                                   │
                                                                                                                   ▼
                                                                                          Phase 10 (AI knowledge) ◄─ Juan opts in OR hire #2 hard trigger
                                                                                                                   │
                                                                                                                   ▼
                                                                                          Phase 11 (AI workflow) ◄─ Phase 10 stable 60d
                                                                                                                   │
                                                                                                                   ▼
                                                                                          Phase 12 (AI agentic) ◄─ Phase 11 stable 6mo
```

**Hire #2 acceleration:** if hire #2 lands during Phases 2–6, **Phase 8 jumps the queue** ahead of the remaining feature work. Hire #2 needs a cloud login; they don't need every feature.

---

## 6. Cost Model (unchanged)

| Period | Hosting | DB | Payments | AI | **Total/mo** |
|---|---|---|---|---|---|
| **Today** | $0 (local) | $0 (SQLite) | $0 | $0 | **$0** |
| **Phases 0–7 (local build)** | $0 (local) | $0 (SQLite) | $0 (Stripe test mode) | $0 | **$0** |
| **Phase 8 cutover** | $7 Render | $7 PG / $0 Neon free | per-invoice fees (0.8% ACH capped $5) | $0 | **~$14** + per-invoice |
| **Year 2, 4 users, no AI** | $7 | ~$19 Neon Launch | per-invoice | $0 | **~$26–40** |
| **+ AI Phase 1** | $7 | ~$19 | per-invoice | ~$18–80 | **~$45–110** |
| **+ AI Phase 2** | $7 | ~$19 | per-invoice | ~$50–140 | **~$76–170** |
| **+ AI Phase 3** | $7 | ~$19 | per-invoice | ~$150–270 | **~$176–300** |
| **Phase 9 Azure** | ~$13 | ~$66 | per-invoice | ~$150–270 (all AI) | **~$230–390** |

AI cost hard caps: $5/user/day default; $1/agent-run; $500/mo platform-wide ceiling.

---

## 7. Risk Register (updated)

| Risk | Severity | Mitigation |
|---|---|---|
| **4–6 months without hosted environment** | **Med** *(NEW per Juan's reordering)* | Hire #2 trigger accelerates Phase 8; weekly Juan-on-iPad PWA smoke during Phases 2–6 catches mobile regressions; staging on Cloudflare Tunnel during Phase 7 lets one trusted reviewer test before public flip |
| **Cloudflare Tunnel for Stripe webhooks expires / drops** | **Low** *(NEW)* | Cloudflare Tunnel runs as a Windows service; auto-reconnects; named tunnel keeps URL stable across restarts; Phase 7 verifies 30-min session survival |
| **SharePoint redirect URI mismatch at hosting flip** | **Low** *(NEW)* | Entra ID supports multiple redirect URIs on single app registration; add prod URL in Phase 8 alongside localhost; no re-registration needed |
| Postgres migration breaks SQLite idioms in untested code paths | High | Parallel `DB_BACKEND` flag (Phase 1 seam, Phase 8 implementation); Phase 7 debug pass catches dialect issues before Phase 8 |
| Calc engine `common.db` snapshot drifts | Med | Nightly job logs row counts; weekly Hermes-watch alert on snapshot age >36h |
| Streamlit mobile UX worse than expected | Med | Phase 3 ends with a "did this actually help?" review; FastAPI+HTMX companion escape hatch |
| Stripe webhook delivery fails or duplicates | Low | Idempotency: `stripe_event_id` per payment; nightly Sigma export reconcile |
| Single-region Neon goes down | Low | Free-tier 7-day PITR; Phase 9 (Azure) zonal redundancy |
| RBAC bug exposes Accounting to non-owners | Med | Audit log + Phase 5 gate requires demonstrated denied access; Postgres RLS at Phase 9 |
| OneDrive sync corrupts SQLite snapshot during local build | **High this week, persists until Phase 8** | Manual `platform.db` copy to `_archive/` before each session; this is the load-bearing reason Phase 8 exists |
| SharePoint Graph rate limit (10 req/sec) | Med | Chunked uploader respects 429; bulk-ingestion spreads across hours |
| SharePoint folder permissions misalign with RBAC | Med | Graph calls use authenticated identity; Phase 5 audit at hire #2 |
| Filename sanitization edge case | Low | 20 adversarial unit tests; on 400 from Graph, retry with more aggressive sanitization |
| AI cost overrun | Med | Per-user $5/day; per-run $1; monthly platform-wide $500 ceiling; pre-flight estimate |
| AI hallucinates engineering content | High | (1) No auto-seal. (2) Eval ≥90% on every model upgrade. (3) Workflow Assists always edit-then-submit. (4) PE review gate non-negotiable. |
| AI indexes copyrighted code PDFs | High (legal) | Do-not-index list at ingestion; CI test asserts no chunks from AISC*/etc.; quarterly audit |
| RAG retrieves stale precedent contradicting current code | Med | `created_at` on each chunk; system prompt instructs Claude to flag potentially outdated; Standards Tracker cross-check |
| Anthropic API outage | Low | Phase 10+ degrade gracefully; Azure OpenAI is documented escape hatch |
| Agent loop / runaway cost | High | 20-turn cap; $1/run; kill switch; real-time audit |
| pgvector index performance at scale | Low | HNSW handles 1M+; reassess >500K chunks |

---

## 8. Discarded Ideas

Unchanged from previous revision. Notable: client portal (NEVER), kanban/Gantt/mirror columns (wrong scale), Azure AI Search ($73/mo vs free pgvector), Azure OpenAI as primary LLM (Claude wins on engineering quality), auto-applied PE seals via AI.

---

## 9. What This Plan Doesn't Solve

- **First DR drill** — moved into Phase 8 gate explicitly (was deferred earlier).
- **Local backups of `common.db`** — separate Litestream → B2 backup recommended as a Phase 8 side-quest.
- **Monitoring / uptime** — Telegram on cron failure during local build; Application Insights at Phase 9.
- **Cesar onboarding UX** — Phase 5 ships User Management; the first-30-minutes experience for hire #2 wants a storyboard pass.
- **Email parsing for permit-portal notifications** — fold into Phase 3 (Graph) or Phase 4 (deadline engine).
- **CEU tracker, COI tracker, demand letters** — Phase 11 partially addresses demand letters; CEU/COI still "Later."
- **AI eval continuity** — quarterly eval-set review as the firm's precedent evolves.

---

## 10. Approval Checklist (updated with Juan's amendments)

**Original 7 — all approved 2026-05-12:**
- [x] North-star outcomes (now 9 with SharePoint + Knowledge Chat added)
- [x] Phase ordering — **REVISED:** hosting moved to final step before AI work
- [x] Render as hosting (Phase 8) — vs. Fly.io with Litestream-SQLite, vs. direct-to-Azure
- [x] Neon as Phase 8 DB — vs. Supabase, Render PG, Azure PG
- [x] 4-role RBAC model
- [x] Stripe as payment processor
- [x] Phase 9 trigger: "5th user OR first SOC2 ask"

**New 7 (this revision) — all approved 2026-05-12:**
- [x] SharePoint via Graph as document store
- [x] pgvector on Neon as vector store
- [x] Anthropic Claude API direct as LLM
- [x] **AI Phase 1 trigger: Juan ships at his discretion; hire #2 = hard trigger if it hasn't happened yet** *(amended per Juan)*
- [x] Do-not-index list enforced at ingestion
- [x] AI cost caps ($5/user/day, $500/mo ceiling)
- [x] PE-review gate for all AI-generated engineering content

---

## 11. Trade-offs Called Out (per Juan's ask)

Three trade-offs explicit at Phase 0 start:

1. **Stripe webhooks need HTTPS — local-only dev requires a tunnel.** Phase 6 webhook listener needs a public HTTPS endpoint. **Cloudflare Tunnel** recommended (free, persistent named hostname, auto-reconnect as a Windows service) over ngrok (rotates URLs on restart, painful for the Stripe webhook config). Setup documented in Phase 6 scope; verified in Phase 7 (debug pass).

2. **SharePoint OAuth needs a registered redirect URI.** App registration in Phase 2 uses `http://localhost:8502/` for dev. Microsoft allows multiple redirect URIs on a single app registration, so at Phase 8 (hosting flip) the production URL is *added* to the existing registration — no re-registration, no token invalidation. Token refresh continues to work across the cutover.

3. **4–6 months without a hosted environment = no team feedback loop until late.** Mitigations:
   - **Hire #2 trigger accelerates Phase 8** ahead of remaining feature work. Hire #2 needs cloud access; they don't need every feature shipped.
   - **Juan-on-iPad PWA smoke** weekly during Phases 2–6 catches mobile regressions on a real device without needing a public URL.
   - **Cloudflare Tunnel as staging** during Phase 7 (debug pass) lets one trusted reviewer (e.g., Cesar, or a hired senior eng evaluator) hit the local app over the internet for a final review before Phase 8 makes it permanent.
   - **Cost of being wrong** is bounded: Phase 8 is ~8 focused hours. If something is fundamentally broken at the debug pass, the iteration is "fix it locally" not "fix it in production while users are watching."

---

## 12. Cross-References

| Document | What it has |
|---|---|
| `_research/platform_v2_business_audit.md` | Page-by-page audit, 10-workflow walkthrough |
| `_research/platform_v2_data_layer_summary.md` | Postgres migration mechanics, SQLite-on-OneDrive risks |
| `_research/platform_v2_hosting_summary.md` | Render vs Azure vs Fly comparison |
| `_research/platform_v2_mobile_ux_summary.md` | Streamlit mobile limits, PWA wrap |
| `_research/platform_v2_integrations.md` | Stripe/Graph/Telegram payment + integration playbook |
| `_research/platform_v2_rbac.md` | 4-role model, schema deltas, IdP migration |
| `_research/ROADMAP_v1.md` (Session 33) | 28-item Now/Next/Later/Never matrix |
| `SESSION34_BUG_BACKLOG.md` | B1–B23 — Phase 0 source list |
| `ENGINEERING_SECTION_DESIGN.md` | Engineering tab design — Phase 4 source |

**Not yet authored** (defer until those phases approach):
- `_research/platform_v2_sharepoint.md` — full Graph integration playbook
- `_research/platform_v2_ai.md` — full AI architecture playbook

---

*Authored 2026-05-12. Approved with amendments 2026-05-12. Phase 0 in progress. Pricing tagged "as of Jan 2026 cutoff." Phase estimates are planning targets; gates exist because reality doesn't match the spreadsheet.*
