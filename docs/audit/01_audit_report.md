# Phase 1 Audit Report — Odoo-Inspired Modules

**Date:** 2026-05-20
**Branch:** `feature/odoo-inspired-modules` (not yet created at time of audit)
**Author:** Claude Code (orchestrated)
**Status:** Audit only — no implementation work performed

---

## Executive summary

The 6DE Company Platform (current version v3.2 per cartography; memory still says v3.1) is a **single-user local Streamlit ERP** backed by SQLite, organized into 10 pages with clean CRUD conventions, idempotent migrations via schema fingerprinting, and a read-only bridge into the calc engine's `common.db`. It is **not a greenfield project**. Several of the modules the original Odoo-inspired prompt asks us to build are partially present already:

- **CRM**: there is a `pages/4_CRM.py` page and an `opportunities` table, but the bridge from the populated `proposals` table (62 rows) was only wired up in S35 and is still propagating; `opportunities` itself sits empty.
- **Accounting / invoicing**: `pages/2_Billing.py`, an `invoices` table, and AR aging on `pages/6_Financials.py` already exist. There is no double-entry GL.
- **Projects**: full CRUD on a `projects` table with milestones, calc-engine linkage, and "+N this month" rollups. No tasks sub-table.
- **Timekeeping**: `pages/5_Timekeeping.py` + a `time_entries` table with labor cost rollup.
- **Accounting (page 9)**: bank transaction categorization rules, recurring expenses, GL summary.

The Odoo addons that map to **net-new** functionality are:

- **`hr` (employees as first-class entities)** — no `employees` table; only `seed_juan_as_employee()` exists.
- **`hr_expense`** — no expense reporting workflow.
- **`hr_holidays`** — no PTO / leave management.

This reframes the original three-module build plan (CRM / accounting / project_hr). A more accurate plan would be a mix of **extension** of existing modules and a smaller set of **net-new** modules, in an order driven by what unblocks what.

**Important context the original prompt did not surface:** `PLATFORM_GOAL_v1.md` lists Phase 2 as **SharePoint document layer via Graph API**, not Odoo-inspired modules. This initiative is a side quest off the documented roadmap. Decision #11 in `02_open_questions.md` flags this — Juan should consciously sequence the two, not let one displace the other.

---

## Module-by-module gap analysis table

| Odoo addon | Current platform state | Classification | Complexity to bring to "small-firm reference quality" | Unblocks |
|---|---|---|---|---|
| `crm` | Page 4 + `opportunities` table (empty) + `proposals` table (62 rows). Bridge wired in S35 but still being verified. | **Partial overlap** | **M** — finish bridge wiring, add configurable stage table, lost-reason taxonomy, prorated revenue forecast | `sale` (quote→order conversion) |
| `sale` | `proposals` table acts as a thin quotation analog. No validity_date, no line items in the Odoo sense, no quote→order→invoice state machine. | **Partial overlap** | **M** — extend proposals with line items, validity_date, and a `generate_invoice()` action | `account` (single integration seam) |
| `account` | `invoices` table + Billing page + Financials AR aging. Single-entry; no GL. | **Partial overlap (intentionally simple)** | **S–M** — improve invoice workflow (sequence-on-post pattern, payment_state derivation, residual amount). **Do NOT add double-entry GL** unless decision changes. | `hr_expense` (posting seam) |
| `project` | `projects` table + page + milestones + calc-engine linkage. **No tasks sub-table.** | **Already covered (mostly)** | **S–M** — optional: add a `project_tasks` table with dependencies and personal stages | `hr_timesheet` (task-level time tracking) |
| `hr` (employees) | Implicit user→employee identity for Juan only via `seed_juan_as_employee()`. No `employees` table found in inventory. | **Net-new (foundation)** | **M** — `employees` table, `resource_calendar` for working hours, manager FK, contractor type. Unblocks every other HR module. | `hr_timesheet`, `hr_expense`, `hr_holidays` |
| `hr_timesheet` | `time_entries` table + Timekeeping page + labor cost rollup. Probably keyed by user, not by employee. | **Partial overlap** | **S** — once `employees` exists, align FK and add optional `task_id`. Keep "time entries == analytic lines" pattern from Odoo. | n/a |
| `hr_expense` | Not present. | **Net-new** | **M** — receipts as attachments, own-account vs company-account split, simple submit→approve→post flow, posting integration to `invoices`/GL table | n/a |
| `hr_holidays` | Not present. | **Net-new** | **M–L** — allocation vs request split, single-approver flow (skip Odoo's two-level), mandatory-day calendar | n/a |

**Complexity legend:** S = ~½ day, M = 1–2 days, L = 3–5 days, XL = 1+ week (calibrated for a solo developer working in focused sessions).

---

## Module-by-module detail

### CRM (partial overlap, M)

**What exists:**
- `pages/4_CRM.py` reads from `opportunities` table.
- `proposals` table populated with 62 rows from historical Excel imports.
- `bridge_proposals_to_opportunities()` idempotent seed function was added in S35 (`db/__init__.py`) but the importer side of the bridge is still pending verification (S34 B5 carryover).

**Gap vs. Odoo `crm`:**
- **Stage table is missing.** Stages are likely hardcoded in the page; Odoo has `crm.stage` as a configurable data table. Worth adopting.
- **No `lost_reason` taxonomy.** Why-we-lost data is high-value for an engineering firm doing proposal analysis.
- **No prorated revenue (`expected_revenue × probability ÷ 100`).** Cheap to add as a SQL view or computed column.
- **No assignment logic.** Single-user platform makes this irrelevant for now; matters once the firm grows past 1 salesperson.

**What to skip from Odoo:**
- UTM campaign tracking. You don't run ads to win structural engineering work.
- Multi-team routing and team-based access rules.
- Recurring-revenue / MRR fields. Engineering work is project-based.

### Sale (partial overlap, M)

**What exists:**
- `proposals` table behaves as a quotation. CRUD via Billing page.

**Gap vs. Odoo `sale`:**
- **No `validity_date` on proposals.** Engineering quotes typically expire after 30–60 days — adding this single field unlocks "expiring soon" dashboards.
- **No structured `order_line` table.** Proposals probably store a single dollar amount, not itemized scope. Odoo's pattern is one header + many lines; that's worth replicating for proposals where scope-of-work matters.
- **No quote → order → invoice state machine.** A "Convert to Invoice" button on accepted proposals would close the loop and likely already aligns with what the Billing page is trying to do.
- **Address split (invoice_address vs shipping_address):** not relevant for service work; skip.

**What to steal:**
- `_get_invoiceable_lines()` hook pattern — allows progress billing (30% on signing, 70% on delivery) without restructuring the order. Common in engineering contracts.
- `invoice_status` (`no`/`to invoice`/`invoiced`/`upselling`) as a derived "what's next" column on the proposal list view.

### Account (partial overlap, intentionally simple, S–M)

**What exists:**
- `invoices` table + Billing page + Financials AR aging. Sufficient for AR side of a single-firm shop.

**Recommendation:** **Do NOT add double-entry GL.** A 5–15 person engineering firm is best served by single-entry invoices + payments + a quarterly export to QuickBooks (or whatever the bookkeeping setup is). Reimplementing Xero is a 6-month detour with zero engineering-firm-specific upside.

**What to steal from Odoo (cheaply):**
- **Sequence-number-on-post pattern.** Draft invoices stay unnumbered; only posted invoices consume an `INV-####` slot. Avoids gaps in the official record when drafts are deleted. Trivial to implement on the existing `invoices` table.
- **`payment_state` derived from reconciliation** rather than a manually-toggled boolean. Compute from sum-of-payments vs invoice total. Trivial.
- **`amount_residual` as a first-class column.** Instant AR aging without subqueries. Trivial.

**What to skip:**
- Full double-entry GL.
- Multi-currency / FX revaluation.
- Tax codes / fiscal positions.
- Bank statement import / reconciliation engine.

### Project (already covered, S optional)

**What exists:**
- `projects` table + page with create/edit/search/milestones.
- Calc-engine linkage via `link_calc_to_erp()` and `get_linked_calcs()`.
- "+N this month" delta tracking (fixed in S35 B8).

**Optional enhancement:** Add a `project_tasks` table mirroring Odoo's `project.task`:
- `stage_id` for kanban columns (configurable).
- `state` selection for lifecycle (in_progress, changes_requested, approved, done, canceled).
- `depend_on_ids` many-to-many for task dependencies.
- **`personal_stage_id`** — each engineer's private kanban lanes independent of shared stages. This is a genuinely good UX pattern stolen from Odoo.
- `allocated_hours` and subtask rollup.

Skip Odoo's `recurring_task`, `portal_rating`, and `is_template` features.

**Verdict:** Defer task-layer addition until `hr_timesheet` integration drives the need. Don't build it speculatively.

### HR / employees (net-new foundation, M)

**Why this is foundational:** every other HR module (`hr_timesheet`, `hr_expense`, `hr_holidays`) leans on an `employees` table for FK targets and on `resource_calendar` for working-hours math. Build this first or the others will accumulate workarounds.

**Suggested table shape (trimmed from Odoo `hr.employee`):**
- `name`, `work_email`, `work_phone`, `job_title`
- `user_id` (FK → users / auth_config.yaml entries) — **nullable** for contractors who don't have logins
- `manager_id` (recursive FK)
- `employee_type` enum: `employee` / `contractor` / `intern`
- `resource_calendar_id` (FK → `resource_calendars` table — see below)
- `contract_date_start`, `contract_date_end`
- `bank_account_*` fields if payroll lives in-platform (probably skip; QuickBooks handles it)
- `active` boolean for soft-deletes

**Skip from Odoo:**
- `web_hierarchy` org-chart widget.
- Skills / certifications / departments-of-departments.
- `coach_id` separate from `manager_id`.
- Multi-company assignment.

**Resource calendars:** small `resource_calendars` table with one row per schedule (e.g., "Standard 40hr", "Part-time M-W-F"). Referenced by employees, leaves, and timesheets.

### HR / timesheet (partial overlap, S)

**What exists:** `time_entries` table + Timekeeping page + labor cost rollup. Probably keyed by `user_id` directly.

**Gap vs. Odoo `hr_timesheet`:**
- **Should be keyed by `employee_id`, not `user_id`**, once employees exist. Lets you track contractor time without auth identity.
- **Add optional `task_id`** FK to the (forthcoming) `project_tasks` table.

**The pattern to keep:** Odoo treats timesheets as analytic ledger lines (one table, dual purpose). The current platform's `time_entries` table likely already plays this role. Don't introduce a second table.

**Skip:** UOM abstraction, multi-company isolation, private-task carve-outs, formal approval state machine. Use access control + edit logs instead.

### HR / expenses (net-new, M)

**Why valuable:** engineering firms routinely have site visits, equipment purchases, travel — manual tracking via email screenshots and spreadsheets is the norm and is a quick-win to replace.

**Suggested table shape (trimmed from `hr.expense`):**
- `employee_id`, `category` (use a configurable taxonomy table instead of Odoo's `product_id`), `date`, `amount`, `description`
- `payment_mode` enum: `own_account` (employee paid, needs reimbursement) / `company_account` (company card)
- `vendor_name` (free text — no need for full vendor master)
- `attachment_path` for receipt (filesystem or SharePoint URL — depends on Phase 2 decision)
- `project_id` optional FK — for re-billable expenses
- `state` enum: `draft` / `submitted` / `approved` / `posted` / `paid`

**The genuine win to steal:** **duplicate-receipt detection via attachment checksum.** Catches double-submission instantly.

**Skip:**
- Tax breakdown on expenses (US receipts already include tax in total).
- Multi-currency expense rate-of-day handling.
- Odoo's dual `approval_state` + computed `state` complexity. Use one state field.

**Posting integration:** post approved expenses into either `invoices` (if billable to a client) or a new `expense_postings` table that feeds the GL summary on page 9. Discuss with Juan — depends on QuickBooks export shape.

### HR / holidays (net-new, M–L)

**Lowest priority of the three HR adds.** A 5-person firm can track PTO in a shared spreadsheet without this — the value materializes around 8+ employees.

**Suggested table shape:**
- `leaves`: `employee_id`, `leave_type_id`, `request_date_from`, `request_date_to`, `number_of_days` (computed via `resource_calendar`), `state` (`submitted`/`approved`/`refused`/`cancelled`), `description`
- `leave_allocations`: `employee_id`, `leave_type_id`, `year`, `days_allocated`. Balance = sum(allocations) − sum(approved leaves).
- `leave_types`: `name`, `requires_approval`, `paid` boolean.

**Pattern to steal:** Allocation vs request as separate tables. Makes "how much PTO do I have left?" trivial.

**Skip:**
- Odoo's two-level approval (`validate1` then `validate`). Single approver is enough at this scale.
- Public-holiday calendar imports per country.
- Accrual rules ("1.5 days per month worked"). Set annual balance manually.
- Integration with payroll work entries.

---

## Recommended phase ordering

The original Odoo-inspired prompt proposed three sequential builds:
1. `/goal-build crm`
2. `/goal-build accounting`
3. `/goal-build project_hr`

Given what already exists, a more accurate ordering is:

### Recommended sequence

| # | Build phase | What it does | Why this order |
|---|---|---|---|
| **A** | **hr-foundation** | Adds `employees` + `resource_calendars` tables. Migrates the implicit Juan-only employee record. Aligns `time_entries.user_id` → `employee_id`. | Foundational. Every later HR module depends on this. Cheap to do first because it touches few existing tables. |
| **B** | **crm-polish** | Finishes proposals→opportunities bridge wiring. Adds configurable `crm_stages` table, `lost_reasons` taxonomy, prorated revenue derived column. | Closes S34 B5 carryover and gives CRM a "finished" feel. Independent of HR work. |
| **C** | **sale-quote-flow** | Extends proposals with `validity_date` and a `proposal_lines` sub-table. Adds "Generate Invoice" action. Adopts Odoo's `invoice_status` derived column on proposals. | Builds on (B). Closes the quote-to-cash loop visibly. |
| **D** | **account-polish** | Sequence-on-post for invoice numbers. `payment_state` and `amount_residual` derived columns. Better AR aging on Financials page. | Builds on (C). Small, high-impact. Stays single-entry — no GL. |
| **E** | **expenses** | Net-new `expenses` table + approval flow + receipt attachments + duplicate-checksum detection. Optional billable-to-project linkage. | Highest-ROI net-new module. Depends on (A) for `employee_id`. |
| **F** | **project-tasks** *(optional)* | Adds `project_tasks` table with personal stages and dependencies. Aligns `time_entries.task_id`. | Only do if (E) reveals a need for task-level cost tracking. Otherwise defer. |
| **G** | **holidays** *(lowest priority)* | Net-new `leaves` + `leave_allocations` + `leave_types` tables. Single-approver workflow. | Lowest frequency, easiest to work around manually. Build if/when firm grows to ~8+ employees. |

Phases **A through E** could realistically ship in 5–8 focused sessions following the existing session-notes cadence. **F and G are explicitly optional** and shouldn't block (E).

### Sequencing against existing roadmap

`PLATFORM_GOAL_v1.md` puts **Phase 2 = SharePoint document layer via Graph API** next after Phase 0/1. That work is currently in-progress in some form (S35 just shipped, S36+ carries over B3/B6/B13–B16/B18/B20 plus Engineering Phase 2). The Odoo-inspired phases above are a **parallel track**, not a replacement. See `02_open_questions.md` #11 for the sequencing decision Juan needs to make consciously.

---

## What we are explicitly NOT recommending

To keep this audit honest, here are things from the Odoo source that **look attractive but should not be built**:

- **Double-entry general ledger.** The platform's role is to capture operational truth (projects, invoices, expenses, time) and export to QuickBooks for the books of record. Reimplementing Xero is a year-long detour with no upside for a 5–15 person firm.
- **UTM tracking on CRM leads.** Not the customer-acquisition channel for engineering work.
- **Pricelists.** One firm, one price list — flat columns on the proposal suffice.
- **Multi-currency anywhere.** USD only.
- **Tax codes / fiscal positions.** US sales tax on engineering services is usually nil; QuickBooks handles edge cases.
- **Two-level approval flows.** Single approver everywhere.
- **Public-holiday calendar imports.** Manual setup is faster than configuring a country calendar.
- **`portal_rating` (clients rating tasks).** Wrong audience for this platform.
- **`web_hierarchy` org-chart widget.** Aesthetic, not useful at this size.

---

## Appendices

- `appendix_a_odoo_survey.md` — full per-addon survey of 8 Odoo modules (CRM, sale, account, project, hr, hr_timesheet, hr_expense, hr_holidays). Manifests + central model files fetched from `raw.githubusercontent.com/odoo/odoo/master/addons/`.
- `appendix_b_platform_cartography.md` — full current-state map of the v3.2 Streamlit platform including launcher behavior, page inventory, persistence layer, shared infrastructure, recent direction, extension points, mermaid architecture diagram, and risks/smells.

These appendices are the raw inputs that fed this synthesis. If a recommendation above looks wrong, start there.

---

## Sign-off

This audit was produced **read-only**. No code, no schemas, no commits. The next step is `/goal-architect` per the original prompt, but only after Juan resolves the open questions in `02_open_questions.md`.
