# 6DE Platform — Roadmap, Fixes & Continuous-Loop Plan

> This is the file `CLAUDE.md` mandates ("decision queue and roadmap") — it did not exist until now.
> Created 2026-08-07 by a Cowork full-sweep session (live-site debug in Chrome + full repo sweep).
> **This file is the memory between sessions. Every dev session reads it first and appends to the
> Session Log before pausing.** Plain English throughout — Juan is a PE, not a programmer.

---

## 0. Operating policy — REDUCED GATES (Juan's directive, 2026-08-07)

Juan explicitly asked for **as few gated actions, pull requests, approvals, and merges as
possible** so sessions can run continuously. This supersedes the stricter gate list in
`CLAUDE.md` (update that file's gate section to match this policy — that edit is itself ungated).

**UNGATED — do continuously, no permission needed:**
- All local work: code, tests, docs, refactors, branches, local runs.
- Committing **directly to `main` for small, low-risk changes**; short-lived branches for bigger ones.
- **Pushing to origin and merging to `main`** — PROVIDED the full verification bar passes first
  (see §3). Merging auto-deploys; that is accepted. No PR ceremony required for solo work:
  merge locally (`git merge --no-ff`) or push `main` directly. Open a PR only when a change is
  risky enough that a diff record helps.
- Post-deploy verification (health poll, live smoke check).

**STILL GATED — the short list (log in WAITING ON JUAN and keep working):**
1. Prod **data** writes and schema migrations (importer `--commit`, DELETE/UPDATE against prod DB).
2. Money / cloud quota / new Azure resources.
3. DNS, domains, Key Vault, secrets, Entra/auth config.
4. External comms (email, posting) and new external service signups (e.g., uptime monitor account).
5. Deleting files or data; anything under `01_Vesta\`.

**Verification replaces approval.** The reason merges can be ungated is that nothing merges
without the full proof bar in §3. A wrong-but-tested-and-reversible change on main is
acceptable; a silent unverified one is not.

---

## 1. Current state

> **SUPERSEDED — this section describes the state BEFORE the 2026-08-07 loop session.
> Kept for the root-cause record. Live now: prod is HEALTHY, running the navy+gold
> theme with self-healing connections, error boundaries on all 10 pages, and `/Health`.
> Still true below: prod data is stale/empty, and there is no external monitoring yet.**

- ~~**Prod is DOWN-ish:**~~ FIXED — was `psycopg.OperationalError: the connection is closed`
  (verified live in Chrome, Home + Projects). Root cause: `@st.cache_resource` caches one
  `PgConnection` for the process lifetime (`db/__init__.py:543`); Azure Postgres drops idle
  sockets; deployed code has no keepalives and no reconnect, so the cached handle dies and every
  page funnels into `pg_compat.py:302` `conn._pg.cursor()`. **Stopgap until deploy: restarting
  the Azure Web App clears it temporarily** (Portal → 6de-platform-jc → Restart).
- **The fix is DONE but stranded:** branch `fix/pg-connection-healing` (2 commits, 2026-08-07)
  adds `_is_dead()` / `_ensure_live()` / retry-once healing, libpq keepalives, `Home.py` error
  boundary + cached dashboard reads (advisor items ①②③), with 581 tests green. **Never pushed —
  GitHub auth is not set up on this machine**, so prod still runs main frozen at 2026-07-05.
- **A month of finished work is local-only** (one disk failure from gone):
  `feat/navy-gold-theme` (6 commits — the navy #2E3186 / gold #D4B878 rebrand matching 6de.xyz,
  verified against the live website today), `feat/top-nav-header` (stacked prototype),
  `feat/accounting-txn-importer` (dry-run-gated importer fix).
- **Data is stale/empty in prod:** `invoices`, `time_entries`, `expenses`, `opportunities`,
  accounting `transactions` all empty; projects imported once on 2026-06-11. Importers hardcode
  the dead `C:\Users\Juan\` account paths (`scripts/importers/*.py:33`).
- **No monitoring:** only `/_stcore/health` (container liveness, not DB). Nightly pg_dump backup
  workflow exists and is solid.

## 1.1 Live QA tour — 2026-08-08 (Cowork, post-deploy, all 11 pages in real Chrome)

**Healthy:** every page renders on the navy+gold theme, zero tracebacks, `/Health` green
(`backend: postgres`, ~33 ms). The outage class is confirmed dead.

**Findings (queue for the loop, roughly by value):**
1. **Data gaps are now THE product problem** — CRM pipeline $0 / 0 opportunities; Financials,
   Billing, AR aging all $0.00; Accounting "No transactions match"; Permits empty; Timekeeping
   0 hrs. Everything except Projects (68 rows) is an empty shell. → §5 is the priority. (Juan,
   2026-08-08: the workbooks are where he actually works — see §5 directive.)
2. **Dashboard "Working Rate 60%"** — suspicious: every time source is empty, so where does
   60% come from? Verify definition; if it's a placeholder, label or remove it.
3. **IA mismatch:** sidebar labels the calc page "Engineering" but its URL is `/Calculator`;
   hitting `/Engineering` shows a "Page not found" toast on the Dashboard. Rename page file or
   label so link text == URL.
4. **`/Health` page renders Streamlit's default sidebar** (plain Home/Projects/…/Bids/Health
   list) instead of the branded grouped sidebar — inconsistent chrome, and it exposes internal
   page names ("Bids" vs the branded "Gov Solicitations" label).
5. **Projects grid polish:** Next Action text can overlap the City column at default widths
   (row 260526); several **Completed projects show 0–1% progress** — data quality from the
   one-time import (progress % was never backfilled), worth a rule (Completed ⇒ 100%).
6. **Recent Activity is frozen at Jun 11, 2026** — it reflects the one-time import. Becomes
   live automatically once §5 sync runs; until then it reads as staleness.

## 2. ~~THE ONE HUMAN ACTION~~ — DONE 2026-08-07

`gh auth login` is complete (account `6DegEng`) and git identity is configured
(`Juan Castillo <juan@6de.xyz>`; there was no `.gitconfig` on this machine at all).
Shipping is unblocked and all four branches are backed up on origin.

**Next-session prompt: the `/goal` loop prompt from 2026-08-07 still works verbatim.**
Step 0 (the `gh auth login` fallback) is now a no-op, and §4 items 1–7 are done, so the
loop will correctly fall through to §5 Phase A / §6 backlog on its next pass.

---

## 3. Verification bar (the "earn a merge" checklist — run EVERY loop iteration)

0. **`ruff check . --select=E,F,W --ignore=E501,E402`** — the exact CI invocation. Added
   2026-08-08 after CI sat RED on main for three commits: merging straight to main skips
   the PR check surface, so nothing surfaced a lint error until someone looked. Cheap, and
   it is the difference between "tests pass" and "CI passes".
0b. **After any push to main, actually check the run:** `gh run list --branch main --limit 2`.
   A deploy can succeed while CI fails — they are separate workflows.
1. `pytest tests/ -q` green on SQLite; on Postgres too (`docker-compose.dev.yml`) when the
   change touches DB/SQL. (Docker/WSL2 may still need provisioning on this machine — if
   unavailable, note it in the log; presentation-only changes may ship on SQLite-green alone.)
2. `python scripts/check_contrast.py` green for any color/theme change.
3. Self code-review of the full diff (+ security review for backend/auth/DB work); fix findings.
4. Live proof where visual/behavioral: run the app locally, screenshot or reproduce the fix.
5. After any merge that deploys: poll the site until healthy, then load 2–3 real pages in a
   browser (or `curl`) and confirm no traceback. **A deploy is not "done" until the live site
   is verified.** If broken: fix forward immediately or `git revert` the merge — reverting main
   is always available and ungated.
6. Append what shipped to the Session Log (§7) — one line each, plain English.

> **STATUS 2026-08-07 (end of loop session): §4 NOW queue items 1–7 are ALL DONE and
> live-verified. Item 8 is a taste decision for Juan.** The next session starts at §5
> Phase A (data freshness) or §6 backlog top-down. See §7 for what shipped.

## 4. NOW queue (strict order, first session after `gh auth login`)

1. **Push everything immediately** (pure backup, changes nothing live):
   `git push -u origin fix/pg-connection-healing feat/navy-gold-theme feat/top-nav-header feat/accounting-txn-importer`
2. **Merge `fix/pg-connection-healing` → main** → auto-deploy → verify live (§3.5). This ends
   the outage class: keepalives + self-healing reconnect + error screen + cached dashboard.
3. **Merge `feat/navy-gold-theme` → main** → deploy → verify. This delivers the brand-color
   directive (navy #2E3186 / gold #D4B878 per 6de.xyz and the letterhead).
4. **Merge `feat/accounting-txn-importer` → main** (no runtime behavior change; the `--commit`
   prod run stays gated → WAITING ON JUAN).
5. **Error boundary on all 10 pages** — Home.py got one; `1_Projects.py` … `9_Accounting.py`
   and `components/sidebar.py` still call `ensure_db()` bare. Extract Home's boundary into a
   shared helper, apply everywhere. (Advisor item ② finished properly.)
6. **App-level health endpoint** — a lightweight page/route that runs `SELECT 1` and reports
   DB + app status (JSON-ish text). This is the hook for uptime monitoring (item ⑤ — the
   external monitor signup itself is gated, but the endpoint isn't).
7. **Kill the dead-account paths** — env-var + `Path.home()` resolution for all three importers
   (pattern already exists in `config.py` and on the accounting branch); fix
   `scripts/sync_accounting.py` which inherits the broken import.
8. **`feat/top-nav-header`**: leave pushed but unmerged — needs Juan's taste decision
   (top nav vs sidebar). → WAITING ON JUAN.

## 5. Data-freshness pipeline — NOW THE #1 WORKSTREAM (Juan's directive, 2026-08-08)

> **Juan, verbatim intent:** "I would like for me to be able to work in the Excel sheets that
> I already have and have it auto-populate that information into the Azure Streamlit app…
> I need everything to stay in sync as tightly as possible so that I can transition into
> using the platform over using the OneDrive files."
>
> Translation: **Excel is the source of truth and Juan's working surface. The platform is a
> read-mostly mirror until parity is proven.** Sync direction is one-way (workbooks → DB).
> The platform must never write back to the workbooks. Juan has approved the *scheme* of
> recurring automated prod writes for this sync (that's what "tightly in sync" means) — the
> FIRST commit run per importer is still supervised (Phase B) to validate reconciliation.

Sources: `Project_Tracker_2026.xlsx` (Projects / Proposals / CRM sheets),
`Accounting_6DE_2026.xlsm` (Transactions / Recurring / CRM), later timesheets + permits.
Workbooks live on OneDrive on Juan's machines → the sync runner executes locally on his PC.

- **Phase A (build, ungated — do first):** one orchestrator `scripts/sync_all.py`:
  - per-source hash gate (skip if unchanged — `sync_accounting.py` pattern), read-only copy
    before parsing (never open the live OneDrive file for write, never hold a lock),
  - idempotent upserts keyed on stable IDs (job #, transaction date+amount+desc hash),
  - dry-run reconciliation FIRST, auto-commit ONLY when totals reconcile exactly
    (tracker: contract $ to the penny; accounting: Net vs Cashflow sheet to the penny);
    any mismatch → skip + log + flag, never a partial write,
  - structured JSONL run log + a **last-sync/freshness line surfaced on `/Health`** (and a
    small "Data as of…" caption on Dashboard) so staleness is visible in the app itself,
  - proposals → CRM opportunities mapping included (salvage `feat/crm-polish` from origin).
- **Phase A.2 — Permits sub-pipeline (Juan's directive 2026-08-08):** permits are filed *inside
  each project's OneDrive folder*, so **project↔permit linkage is the integral piece** — the
  link key is the job # (folder prefix `YYMMDD - Name` == tracker Job # == `projects` row; the
  `permits` table already has a project FK, as the Permits form shows). Build
  `scripts/importers/import_permits.py` into `sync_all.py`:
  - walk `06_Engineering/01_Active Projects/<YYMMDD - Name>/`, regex `UP\d{8}` / `UPA\d{8}`
    out of folder names, file names, registration/permit logs, and `_CLAUDE_BRIEF.md`;
    upsert permits keyed `(job #, UP #)` with jurisdiction + whatever status the records give,
  - ALSO seed a row for every tracker project currently in the AHJ/Permitting bucket, so the
    Permits tab tracks "active projects in permitting" even where no UP number is parsed yet,
  - source of truth = **records on disk/email/tracker only** — per the `permitting` skill's
    2026-08-06 lockout lesson, NEVER auto-scrape the county EPS portal for status; portal
    lookups stay human-paced and manual. The Cowork `permitting` skill (10_AI\02_Cowork\
    04_Skills\permitting) documents the number anatomy and folder conventions to parse.
- **Phase B (first supervised `--commit` per importer — GATED, ~30 min of Juan's time):**
  accounting first (dry-run already reconciles: 705 rows, Net $6,098.49), then tracker
  (invoice synthesis + clients), then CRM/opportunities. Undo paths documented before each.
- **Phase C (standing sync — scheme pre-approved 2026-08-08, registration is Juan's click):**
  Windows Task Scheduler job every ~30 min: `sync_all.py --commit` with the Phase-A guardrails.
  AI prepares `register_sync_task.ps1`; **Juan runs it once** (persistence guardrail — AI never
  registers scheduled tasks itself). Nightly pg_dump backup already provides the safety net.
- **Phase D (later, optional):** cloud-side pull via Microsoft Graph (Azure Function reads the
  SharePoint copies) so sync doesn't depend on Juan's PC being on. Needs app registration +
  secrets = gated; only worth it if Phase C's PC-dependency proves annoying.

## 6. Backlog (post-NOW, pick top-down; Impact/Effort/Risk)

| # | Item | I/E/R | Notes |
|---|------|-------|-------|
| B1 | CRM/proposals → opportunities import (pipeline $0 today) | H/M/L | Old PR #35 branch `feat/crm-polish` on origin has most of it — rebase/salvage instead of rebuilding |
| B2 | Timesheets parity + HR foundation | H/M/M | Old PR #34 branch on origin; needs 3 data decisions (gated bits → WAITING) |
| B3 | Permits importer (table empty) | H/M/L | PROMOTED into §5 Phase A.2 (Juan 2026-08-08) — folder-walk + tracker seed, linked by job # |
| B4 | Engineering calc-DB in prod (`common.db` bundle-or-blob) | M/M/M | Infra decision gated → WAITING |
| B5 | Page-level role authorization (`modules/auth.py:21` TODO) | M/M/L | Everyone authenticated sees Accounting/Financials today |
| B6 | Connection pool (advisor ④) | M/M/M | Deferred by design until 3–4 concurrent users |
| B7 | Route inline muted-color literals through `palette.py` | L/L/L | Makes the next retheme one file |
| B8 | Dependency lockfile (pip-compile) so deploys are reproducible | M/L/L | Range pins currently allow surprise upgrades at image build |
| B9 | ~~Remove vestigial PyInstaller launcher files~~ | — | SUPERSEDED by B13 — Juan wants the launcher REVIVED, not deleted (2026-08-08) |
| B10 | `check_contrast.py` + ruff into CI as required checks | L/L/L | |
| B11 | Uptime monitor wiring once Juan creates the account (⑤) | M/L/L | Endpoint from NOW-6; signup gated |
| B12 | Old stale `origin/*` branch cleanup (~40) | L/L/L | Deletion = gated, batch-ask Juan once |
| B14 | Mobile home-screen polish (Juan asked about iOS, 2026-08-08): proper PWA touches — 6DE app icon (`apple-touch-icon`), navy `theme-color`, standalone display manifest — so "Add to Home Screen" on iPhone looks/feels like an app. No native app for now (App Store overhead not justified for an internal tool). | M/L/L | Streamlit static-asset injection; verify on a real phone. |
| B13 | **Desktop launcher (Juan approved 2026-08-08):** revive `launcher.py` / `launcher.spec` / `Launch_6DE_Platform.bat` so double-clicking an icon runs the Streamlit app locally against the **Azure Postgres** (same live data as the website, no Easy Auth portal login) | H/M/M | Build/test everything ungated (local run against Docker PG first). Going live needs the two gated enablers in §8 item 9. Do NOT create a second local database — one source of truth. Launcher should read the DSN from a local `.env`/`PLATFORM_DATABASE_URL`, never hardcode it. Interim already done: Juan can "Install as app" from Edge for a desktop icon onto the hosted site. |

## 6.1 BLOCKER for accounting sync — schema migration (GATED, found 2026-08-08)

**The accounting importer cannot be trusted until this is fixed, and `sync_all.py`
now correctly refuses to run it.** Two constraints in `db/schema.sql` silently discard
real rows because the importer uses `INSERT OR IGNORE`, which swallows the violation:

| Constraint | What it eats | Cost |
|---|---|---|
| `CHECK (account_type IN ('Debit','Credit'))` | the workbook's legitimate `'Business'` rows | **270 rows, $26,798.49** |
| `UNIQUE (txn_date, amount, description)` | genuinely repeated charges (two identical fees in one day) | **11 rows** |

Total predicted shortfall **$24,379.62** — confirmed exactly against a real commit run
(workbook $44,225.13 vs database $19,845.51).

**Proposed fix (needs Juan's OK — schema migration is gated):**
1. Widen the CHECK to include `'Business'` (and any other account types in the
   workbook), or drop the CHECK and validate in the importer where a rejection can be
   *reported* instead of swallowed.
2. Replace the UNIQUE key with one that admits legitimate repeats — add an
   `occurrence` column numbering identical (date, amount, description) rows within a
   sheet, and key on `(txn_date, amount, description, occurrence)`. Stable when Juan
   inserts rows, unlike keying on the spreadsheet row number.
3. Separately: replace `INSERT OR IGNORE` in `import_transactions` with an explicit
   upsert so a constraint violation can never again vanish silently. **This is the
   root cause** — the constraints are just where it showed up first.

## 7. Session Log (append-only; newest first)

- **2026-08-08 (Claude Code marathon — §5 Phase A shipped):**
  - **CI had been RED on main since 2026-08-07** (three commits) — a lint-only failure
    that merging straight to main never surfaced. `tests-postgres` was green throughout,
    so nothing functional reached prod. Fixed, and added ruff + "check the run after
    pushing" to the §3 bar so a green deploy is no longer mistaken for a green CI.
  - **`scripts/sync_all.py` shipped** — hash-gated, snapshot-before-parse, dry-run
    reconciliation, commit only on an exact match, post-write verification, JSONL run
    log, freshness in the DB.
  - **It immediately earned its keep:** a commit run against a throwaway DB reported
    "reconciled OK" and produced books off by **$24,379.62**. Root cause is
    `INSERT OR IGNORE` hiding two constraint violations (see §6.1). Reconciliation now
    predicts the shortfall to the cent and REFUSES the accounting import. Tracker
    imports cleanly and verifies exactly ($231,452.00).
  - **Freshness is visible in the app**: "Data as of ..." on the Dashboard, and a
    Data-freshness panel on `/Health` that flags a stale or mismatched source in red.
  - Corrected drift: the accounting dry-run figures in §8 were stale (705 rows /
    $6,098.49); the workbook now reads **770 rows / net $44,225.13**.

- **2026-08-08 (Cowork QA tour):** Full 11-page live tour in Chrome post-deploy — healthy,
  on-brand, no tracebacks; findings logged as §1.1. Juan's Excel-first sync directive recorded;
  §5 rewritten as the #1 workstream with the sync architecture (hash-gate → dry-run reconcile →
  auto-commit-only-on-exact-match → freshness surfaced on `/Health`); standing-sync scheme
  pre-approved, first commit runs still supervised. New marathon loop prompt issued.

- **2026-08-07 (Claude Code loop session, part 2 — NOW queue 1–7 COMPLETE):**
  - **Error boundary on all 10 pages.** Added `connect_or_explain()` so each page is a
    one-liner, not nine copies of the same try/except. Verified live against a dead
    database: Projects shows the branded panel with page chrome intact, not a traceback.
  - **`/Health` page shipped and live** — runs a real `SELECT 1` and reports backend,
    latency, status. Live in prod: `status: ok, backend: postgres`. Deliberately NOT
    wired into the Docker HEALTHCHECK: Azure restarts unhealthy containers, so a
    DB-aware container check would turn a brief database blip into a restart loop that
    takes the app fully down — replacing the friendly error page with nothing.
  - **Docs-only commits no longer redeploy production.** A ROADMAP edit had triggered a
    full image rebuild + container restart for zero runtime change.
  - **All three importers are path-portable.** Verified by resolution, not inspection —
    which caught a second defect: the tracker path also had a stray space
    (`01_ Active Projects` vs the real `01_Active Projects`), so fixing only the
    username would have left it broken.
  - **Found and fixed a live break I had just shipped:** the accounting-importer
    refactor merged earlier today dropped the module-level `SOURCE` constant, which
    `scripts/sync_accounting.py` imports directly — that module was DEAD at import time
    and the nightly-sync seam (§5 Phase A) could not load. Restored and pinned by a test.
  - Test suite 570 -> **675 green**.
  - Deploy-verification lesson worth keeping: the first page load after a deploy is
    often still the OLD container mid-swap. It can look healthy because the restart
    cleared the dead socket. **Confirm a marker from the new code before believing it.**
    Separately, a stale client-side page list made `/Health` 404 after it was genuinely
    deployed — a cache-busting query param proved the route was fine.

- **2026-08-07 (Claude Code loop session — the outage is OVER):**
  - Git identity was missing entirely on this machine (no `.gitconfig`); set to
    Juan Castillo <juan@6de.xyz>. `gh auth login` done by Juan → shipping unblocked.
  - `CLAUDE.md` gate section rewritten to match §0 reduced-gate policy.
  - **All 4 local branches pushed to origin** — a month of work is no longer one disk
    failure from gone.
  - **`fix/pg-connection-healing` merged (PR #39) and deployed.** CI green on BOTH
    backends (643 tests on real Postgres 16). **Live site verified healed**: Home shows
    41 active projects / $76.7K backlog, Projects shows 68/41/27, no traceback.
  - Caught during verification: the first live page load after deploy was still the OLD
    container mid-swap (looked healthy only because the restart cleared the dead socket).
    Confirmed the new code by checking for the new Refresh control before calling it done.

- **2026-08-07 (Cowork sweep):** Live outage verified (all pages, connection-closed traceback);
  root cause + fix-branch state confirmed; brand palette verified against 6de.xyz; this file
  created; reduced-gate policy recorded; handover prompt issued. A Claude Code session was
  active in this clone during the sweep (committed `e7f550e` — keepalives/error-boundary/
  cached-reads). Nothing pushed (auth blocker stands).

## 8. WAITING ON JUAN (refreshed 2026-08-07, end of loop session)

*(`gh auth login` and the Azure restart stopgap are DONE — both removed from this list.)*

1. **Easy Auth exclusion for `/Health`** — the endpoint is live and working, but Azure
   Easy Auth answers 401 to anonymous requests on every path except `/_stcore/health`,
   so an uptime monitor cannot read it yet. Adding the exclusion is auth config = gated.
   **This blocks item 2 below.**
2. Uptime-monitor account signup (free tier, e.g. UptimeRobot) — needs item 1 first.
3. **Approve the accounting schema fix (§6.1) — NOW TOP PRIORITY of your items.**
   ~15 min to review. Two constraints in `schema.sql`, combined with `INSERT OR IGNORE`,
   silently discard **$24,379.62** of real transactions (270 `'Business'` rows + 11
   legitimately repeated charges). `sync_all.py` proves this and REFUSES to import
   accounting until it's fixed — deliberately, because wrong financials on the dashboard
   are worse than stale ones. Schema migration = gated, so it needs your nod.
4. **Supervised importer `--commit` runs** (§5 Phase B), ~30 min with the session
   watching. **Tracker is ready right now** — it reconciles and post-write-verifies
   exactly ($231,452.00 across 50 projects). **Accounting is blocked on item 3.**
   Current accounting dry-run reads 770 rows / net $44,225.13 (the older
   705 rows / $6,098.49 figure was stale — you've been working in the workbook since).
   After these runs the only remaining click is `register_sync_task.ps1` once.
4. Top-nav vs sidebar taste decision (`feat/top-nav-header`, pushed but unmerged —
   run `streamlit run streamlit_app/app.py` to try it). This is §4 item 8.
5. Engineering calc-DB decision: bundle `common.db` in the image vs pull from blob
   (+ set `SIXDE_CALC_DB`).
6. Flip repo 6DegEng/6de-platform private (fee schedule is public; 60-day cron
   auto-disable risk).
7. Timesheet data decisions for B2 (260304 building mapping; add Halil as employee
   w/ role; dup row 260223).
8. Batch-approval to delete the ~40 stale `origin/*` branches (B12) — deletion is gated.
   (The PyInstaller launcher files are NO LONGER deletion candidates — see B13.)
9. **Desktop-launcher enablers (B13, both gated — needed only when the launcher is ready
   to point at prod):** (a) an Azure Postgres firewall rule allowing Juan's PC/office IP
   (Azure config); (b) putting the database connection string on Juan's PC — recommend a
   dedicated Postgres user for desktop use (so it can be revoked independently of the
   web app's credential) stored in a local `.env` the repo already gitignores. Sessions:
   stage the exact commands/steps for both; Juan executes.
