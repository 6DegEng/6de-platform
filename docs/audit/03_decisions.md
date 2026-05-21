# Phase 1 Decisions

**Date:** 2026-05-20
**Decided by:** Juan (accepted defaults across the board)
**Supersedes:** `02_open_questions.md`

---

## Blocking decisions (resolved)

### Q1 — Sequence vs. SharePoint roadmap → **(a) Pause Odoo, ship SharePoint Phase 2 first**

The documented `PLATFORM_GOAL_v1.md` Phase 2 (SharePoint document layer via Graph API) takes priority. Odoo-inspired modules are paused at the audit stage. They will resume after SharePoint is in place — at which point the expenses module has a natural home for receipt storage.

**Implication:** **Do NOT run `/goal-architect` next.** The audit artifacts in `docs/audit/` are reference material to pick up later, not a live workstream.

### Q2 — Phase plan → **(b) Revised 7-phase plan**

When Odoo work resumes, the build sequence is:
1. **hr-foundation** — `employees` + `resource_calendars` tables
2. **crm-polish** — finish proposals→opportunities bridge, configurable stages, lost reasons, prorated revenue
3. **sale-quote-flow** — proposal validity_date, line items, "Generate Invoice" action
4. **account-polish** — sequence-on-post, `payment_state`, `amount_residual` derived columns
5. **expenses** — net-new with approval + duplicate-checksum detection (depends on SharePoint Phase 2 for receipt storage)
6. *(optional)* **project-tasks** — only if expenses/timesheet flow reveals task-level need
7. *(optional)* **holidays** — only if firm grows to ~8+ employees

### Q4 — Architecture → **(a) Stay Streamlit-only**

Raw SQL, `db/__init__.py` factory, idempotent migrations via fingerprinting. New modules drop into `modules/{name}/` per existing conventions. Revisit FastAPI when Phase 3 (mobile PWA) or Phase 6 (Stripe/Telegram webhooks) forces the issue.

### Q14 — Autonomy mode → **(b) Autonomous for read-only; interactive for builds**

Audit and architect phases can run autonomously (`--dangerously-skip-permissions` acceptable, walk-away OK). Build phases (schema changes, code generation) run interactively with checkpoints between subagent stages. Reconciles the productivity boost with the standing phase-gate preference.

---

## Non-blocking decisions (defaulted)

These can be revisited per-phase when work resumes. Defaults recorded for the record:

| # | Question | Default chosen |
|---|---|---|
| Q3 | Branch and merge discipline | (a) One branch per phase, merge to main between phases |
| Q5 | SQLAlchemy vs. raw SQL | (a) Keep raw SQL |
| Q6 | Postgres now vs. later | (a) Stay on SQLite; code defensively for Phase 8 portability |
| Q7 | Expense receipt storage | (b) Local storage now, migrate to SharePoint later — superseded by Q1 (a): SharePoint will exist before expenses module is built |
| Q8 | CRM table model | (a) Keep `proposals` + `opportunities` split |
| Q9 | Employees table timing | (a) Build full table when hr-foundation phase runs |
| Q10 | Project tasks | (b) Defer; build only on demand |
| Q11 | Approval flows | (a) Hardcode Juan as sole approver |
| Q12 | Expense OCR | (c) Manual entry first; revisit later |
| Q13 | PTO module | (b) Defer until firm grows |
| Q15 | OneDrive sync during builds | (a) Pause OneDrive sync for autonomous runs |
| Q16 | Update v3.1 → v3.2 in memory | Yes (already done) |

---

## Where this leaves us

**Active workstream returns to S36+ carryover** per `SESSION35_NOTES.md` and `PLATFORM_GOAL_v1.md`: B3 (project addresses), B6 (permits importer), B13–B16 (proposal hygiene), B18 (`contacts` vs `permit_contacts`), B20 (empty-state copy), Engineering Phase 2 (Code Library + Standards Tracker + Practice Library tabs), Cover Sheet PDF export, Auditor results persistence — and then SharePoint document layer (Phase 2).

**This audit is shelved**, not killed. When SharePoint Phase 2 ships, re-read `01_audit_report.md` and start the build pipeline at phase A (hr-foundation).
