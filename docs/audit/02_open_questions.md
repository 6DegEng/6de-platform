# Phase 1 Open Questions — Decisions Needed Before Architecture

**Date:** 2026-05-20
**Status:** Awaiting Juan's decisions
**Prerequisite for:** `/goal-architect` (Phase 2 of the Odoo-inspired prompt)

Each question lists the **default I would pick** if you said "just decide" — but they all matter enough that I'd rather not.

---

## Strategic / sequencing

### Q1. **This initiative vs. the documented Phase 2 (SharePoint document layer)** — biggest call

`PLATFORM_GOAL_v1.md` says Phase 2 is "SharePoint document layer via Graph API." The Odoo-inspired modules are not on that roadmap. Three plausible answers:

- **(a) Pause Odoo work, ship SharePoint first.** Document layer is foundational for the expenses module (receipts need a home) and for the engineering Cover Sheet PDF flow.
- **(b) Run them in parallel.** SharePoint on one branch, Odoo modules on another. Higher merge risk; only works if you're personally context-switching cleanly.
- **(c) Pause SharePoint, ship 1–2 Odoo modules first.** Bet that expenses + CRM polish deliver more visible value sooner than a document layer.

**Default if you don't pick:** (a). The document layer unblocks expenses (receipt storage) and is already on your roadmap. The Odoo work is a side quest until the roadmap says otherwise.

### Q2. **Original 3-module plan vs. revised 5–7 phase plan**

The original prompt said `/goal-build crm`, `/goal-build accounting`, `/goal-build project_hr`. The audit recommends a different split (see `01_audit_report.md` § "Recommended phase ordering"): hr-foundation → crm-polish → sale-quote-flow → account-polish → expenses → (optional task layer) → (optional holidays).

- **(a) Stick with original 3-module plan** — bundle work and accept that "CRM" includes extending sale + invoicing where they overlap.
- **(b) Adopt revised phase plan** — smaller commits, more checkpoints, easier to pause and resume.

**Default if you don't pick:** (b). Aligns with your standing preference for phase gates at natural checkpoints, and the smaller phases let you cut off any one of them if it stops delivering value.

### Q3. **Branch and merge discipline**

The original prompt creates `feature/odoo-inspired-modules` and assumes one long-lived branch. With the revised phase plan:

- **(a) One branch per phase** (`feature/odoo-hr-foundation`, `feature/odoo-crm-polish`, etc.), merge to main between phases.
- **(b) One long-lived branch** for all Odoo work, merge once at the end.
- **(c) Trunk-based** — merge after every phase directly to main on a single rolling branch.

**Default if you don't pick:** (a). Matches phase-gate cadence; if a phase goes sideways, only one phase's diff to discard.

---

## Architectural

### Q4. **Streamlit-only vs. FastAPI-backed vs. hybrid**

The original prompt's Phase 2 (`/goal-architect`) was going to evaluate these three. Given the cartography shows the platform is currently **pure Streamlit + SQLite + raw SQL** with clean conventions, the question is whether the new modules are an excuse to refactor toward an API.

- **(a) Stay Streamlit-only.** Keep raw SQL, keep `db/__init__.py` factory, add modules as more `streamlit_app/pages/N_X.py` files. Lowest cost.
- **(b) FastAPI backend, Streamlit becomes UI client.** Lets you add mobile/PWA (Phase 3 in roadmap) and webhooks later. ~2× initial cost.
- **(c) Hybrid.** Streamlit for ops UI; FastAPI only for things that need external API access (Stripe webhooks, Telegram alerts, mobile). Pragmatic.

**Default if you don't pick:** (a). The platform works. Don't refactor speculatively. Revisit when Phase 3 (mobile) or Phase 6 (Stripe/Telegram) makes (c) inevitable.

### Q5. **SQLAlchemy / SQLModel vs. raw SQL**

The platform uses raw `sqlite3` + manual DDL today. The original prompt's conventions section says "All persistence goes through a single SQLAlchemy session factory — no ad-hoc sqlite3.connect() calls." That contradicts the current codebase.

- **(a) Keep raw SQL.** Stay consistent with the existing 10 pages.
- **(b) Adopt SQLAlchemy / SQLModel for new modules only.** Coexistence is fine; new tables get the ORM, existing tables stay raw.
- **(c) Adopt and migrate everything.** Multi-session refactor; high cost.

**Default if you don't pick:** (a). Raw SQL is working, idempotent migrations are clever, and the cartography found zero ad-hoc connection calls outside the factory — the discipline is already there without an ORM.

### Q6. **Postgres now vs. later**

Phase 8 of the documented roadmap is the Postgres flip. The Odoo addons assume relational guarantees (FKs, transactions, sequences) that SQLite mostly provides but with caveats.

- **(a) Build new modules against SQLite, plan FK names and sequence usage to be portable.** Defer migration.
- **(b) Stand up Postgres now for new modules; older tables stay on SQLite.** Dual-DB complexity.
- **(c) Migrate everything to Postgres now.** Big bang; out of scope for this initiative.

**Default if you don't pick:** (a). The fingerprinted migration system already supports `DB_BACKEND=postgres` as a hook; portability discipline is a coding habit, not a migration project.

### Q7. **SharePoint integration for expense receipts** — depends on Q1

If Q1 = (a) (SharePoint first), expense receipts have a natural home. If Q1 = (b) or (c), expense receipts need a storage answer.

- **(a) Defer expenses module until SharePoint is live.**
- **(b) Store receipts in `%LOCALAPPDATA%\6th-degree-platform\receipts\` for now; migrate to SharePoint later.**
- **(c) Use OneDrive folder structure directly.** (Concerns: sync conflicts during uploads.)

**Default if you don't pick:** (b). Local storage is fast and the migration to SharePoint later is just a path change in `config.py`.

---

## Module-specific

### Q8. **CRM table model: keep `proposals` + `opportunities` split, or unify per Odoo's `crm.lead` pattern**

Odoo uses one `crm.lead` table with a `type` discriminator (`lead` vs `opportunity`). Your schema has `proposals` (62 rows, historical) and `opportunities` (empty, bridged in S35).

- **(a) Keep both tables.** Bridge stays one-directional (proposals → opportunities). Historical data preserved as-is.
- **(b) Unify into one `crm_records` table with `type` discriminator.** Cleaner long-term, but requires migrating 62 historical rows.
- **(c) Deprecate `proposals` once bridge is complete.** Read-only archive table; new records only go to `opportunities`.

**Default if you don't pick:** (a). Migration risk vs. cleanliness — not worth it for 62 rows. Revisit when the firm grows past 500 historical proposals.

### Q9. **Employees table: full HR foundation, or only as needed**

- **(a) Build full `employees` table now** (manager FK, resource_calendar, contractor type). Includes a one-row migration for Juan.
- **(b) Defer until a second person joins.** Stick with `seed_juan_as_employee()` until there's a second employee or contractor whose data needs to live somewhere.

**Default if you don't pick:** (a). If the answer to Q2 is (b) and the phase plan starts with hr-foundation, this is already decided.

### Q10. **Project tasks: add now or defer**

- **(a) Add a `project_tasks` table now** with personal stages + dependencies. Build the kanban UI.
- **(b) Defer.** Add only if/when expense reporting or timesheet flow reveals a need for task-level granularity.

**Default if you don't pick:** (b). The audit recommends building it only on demand. Projects work fine today without it.

### Q11. **Approval flows: single approver vs. configurable**

For expenses and (if built) holidays, who approves?

- **(a) Hardcode Juan as sole approver.** Cheapest. Works for 5–15 person firm.
- **(b) `requires_approval_by` FK on each request, defaulting to manager_id.** Flexible. Useful if firm grows.

**Default if you don't pick:** (a). Hardcoded today; refactor to (b) is one-table change later.

### Q12. **Expenses: receipt OCR / auto-categorization, or manual entry only**

- **(a) Manual entry.** Employee uploads receipt, types in amount/category. Cheap.
- **(b) Auto-extract with Tesseract or Azure Document Intelligence.** ~1 week of integration work, ongoing API costs if cloud.
- **(c) Defer to a future module pass.** Ship manual first, add OCR later.

**Default if you don't pick:** (c). Ship manual first. If you find yourself manually entering >5 receipts/week, then revisit.

### Q13. **PTO module — build at all in this initiative**

- **(a) Yes, build as the last phase (G).** Even if 1 person, sets up the table shape for future.
- **(b) No, defer until the firm grows.** Track PTO in a spreadsheet for now.

**Default if you don't pick:** (b). It's the lowest-value net-new module per the audit. Build only when employee count justifies it.

---

## Operational

### Q14. **`--dangerously-skip-permissions` and "walk away 2–4 hours"**

The original prompt's setup section recommends `claude --dangerously-skip-permissions` with the expectation that you walk away for hours. Memory says you prefer phase gates at natural checkpoints. These conflict.

- **(a) Drop the autonomous mode.** Run phases interactively, with `AskUserQuestion` checkpoints between major steps.
- **(b) Keep autonomous mode for read-only phases only** (audit + architect). Switch to interactive for build phases.
- **(c) Full autonomous as written in the original prompt.** Trust the branch + git as the safety net.

**Default if you don't pick:** (b). Reconciles your phase-gate preference with the genuine productivity boost of letting research run unattended.

### Q15. **OneDrive vs. local working directory during builds**

Cartography confirms the platform lives under OneDrive. The original prompt's autonomous runs (subagents writing files, running pytest, committing) will trigger OneDrive sync churn and occasional file-lock conflicts that look like build failures.

- **(a) Pause OneDrive sync** for the duration of each autonomous run.
- **(b) Move working copy to `~/code/6de-platform/` and rsync to OneDrive periodically.** More complex, but isolates churn.
- **(c) Leave OneDrive on, accept occasional retry-due-to-file-lock failures.** Cheapest.

**Default if you don't pick:** (a). Pause is one click; resume is one click. The pain of (c) is real — pytest randomly failing because OneDrive grabbed a `.pyc` file mid-write is hard to debug after the fact.

### Q16. **Update memory note about platform version**

Memory currently says v3.1. Cartography found v3.2. Independent of the rest of this audit, I can update the memory entry. Yes/no?

**Default if you don't pick:** yes, update.

---

## Recommended decision path

If you'd rather not answer 16 questions, the **minimum set** that unblocks Phase 2 (`/goal-architect`):

1. **Q1** — sequence vs. SharePoint roadmap
2. **Q2** — which phase plan
3. **Q4** — architecture (just confirm "stay Streamlit-only" if that's the gut call)
4. **Q14** — autonomy mode

The rest can default and be revisited during `/goal-architect` or per-phase. Tell me your answers to those four (or "go with defaults") and I can proceed.
