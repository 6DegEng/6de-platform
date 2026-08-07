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

## 1. Current state (verified 2026-08-07)

- **Prod is DOWN-ish:** every page shows `psycopg.OperationalError: the connection is closed`
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

## 2. THE ONE HUMAN ACTION THAT UNBLOCKS EVERYTHING

```
cd C:\Users\JuanCastillo\code\6de-platform
gh auth login        # (or sign in when Git Credential Manager prompts on first push)
```

Without this, nothing ships. With it, the loop below runs indefinitely.

---

## 3. Verification bar (the "earn a merge" checklist — run EVERY loop iteration)

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

## 5. Data-freshness pipeline (projects / clients / CRM / accounting)

Goal: the platform stays current with `Project_Tracker_2026.xlsx` and
`Accounting_6DE_2026.xlsm` without manual debugging passes. The workbooks live on OneDrive on
Juan's machines, so sync must run locally, not in the cloud.

- **Phase A (build, ungated):** make all importers idempotent, path-portable, dry-run by
  default with penny-exact reconciliation reports (tracker → Projects/Proposals/CRM;
  accounting → Transactions; permits later). `scripts/sync_accounting.py`'s hash-gate pattern
  (only import when the file changed) is the right seam — extend it to the tracker.
- **Phase B (one supervised run, gated):** first `--commit` for each importer against prod with
  Juan watching; verify totals against the workbooks to the penny. Undo paths documented first.
- **Phase C (standing sync, one-time approval):** a Windows Task Scheduler job (nightly) that
  runs hash-gated dry-run → auto-commit only when reconciliation is exact, logging every run;
  any mismatch = skip + flag instead of write. After Juan approves the scheme once, routine
  syncs are no longer individually gated. This turns "keep it up to date" into a non-event.

## 6. Backlog (post-NOW, pick top-down; Impact/Effort/Risk)

| # | Item | I/E/R | Notes |
|---|------|-------|-------|
| B1 | CRM/proposals → opportunities import (pipeline $0 today) | H/M/L | Old PR #35 branch `feat/crm-polish` on origin has most of it — rebase/salvage instead of rebuilding |
| B2 | Timesheets parity + HR foundation | H/M/M | Old PR #34 branch on origin; needs 3 data decisions (gated bits → WAITING) |
| B3 | Permits importer (table empty) | M/M/L | |
| B4 | Engineering calc-DB in prod (`common.db` bundle-or-blob) | M/M/M | Infra decision gated → WAITING |
| B5 | Page-level role authorization (`modules/auth.py:21` TODO) | M/M/L | Everyone authenticated sees Accounting/Financials today |
| B6 | Connection pool (advisor ④) | M/M/M | Deferred by design until 3–4 concurrent users |
| B7 | Route inline muted-color literals through `palette.py` | L/L/L | Makes the next retheme one file |
| B8 | Dependency lockfile (pip-compile) so deploys are reproducible | M/L/L | Range pins currently allow surprise upgrades at image build |
| B9 | Remove vestigial PyInstaller launcher files | L/L/L | Confirm with Juan before deleting (delete = gated) |
| B10 | `check_contrast.py` + ruff into CI as required checks | L/L/L | |
| B11 | Uptime monitor wiring once Juan creates the account (⑤) | M/L/L | Endpoint from NOW-6; signup gated |
| B12 | Old stale `origin/*` branch cleanup (~40) | L/L/L | Deletion = gated, batch-ask Juan once |

## 7. Session Log (append-only; newest first)

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

## 8. WAITING ON JUAN (refresh every session)

1. **`gh auth login` in the clone** — unblocks all shipping (§2). ~2 minutes.
2. Optional immediate relief before the deploy: restart Web App `6de-platform-jc` in the Azure
   portal (clears the dead connection until it idles out again).
3. Top-nav vs sidebar decision (`feat/top-nav-header` — run `streamlit run streamlit_app/app.py` to try it).
4. Supervised importer `--commit` runs (accounting first: dry-run says 705 rows / Net $6,098.49
   reconciles to the penny), then the standing-sync scheme approval (§5 Phase C).
5. Uptime-monitor account signup (free tier, e.g. UptimeRobot) once the health endpoint ships.
6. Engineering calc-DB decision: bundle `common.db` in the image vs pull from blob (+ set `SIXDE_CALC_DB`).
7. Flip repo 6DegEng/6de-platform private (fee schedule is public; 60-day cron auto-disable risk).
8. Timesheet data decisions for B2 (260304 building mapping; add Halil as employee w/ role; dup row 260223).
