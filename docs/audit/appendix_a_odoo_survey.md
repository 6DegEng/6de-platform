# Appendix A — Odoo Addon Survey

**Date:** 2026-05-20
**Method:** Manifests + central model files fetched from `raw.githubusercontent.com/odoo/odoo/master/addons/`. READMEs were either thin or absent — manifests + models gave better signal.
**Fetch result:** 8/8 manifests, 8/8 central model files. No failed fetches.

Files fetched per module: `__manifest__.py` + most central model under `models/`.

---

## crm

**Purpose** — Track sales leads, qualify them into opportunities, and drive them through a configurable pipeline toward won/lost outcomes.

**Key data model**
- `crm.lead` is one table that does double duty via a `type` selection (`lead` vs `opportunity`).
- `stage_id` (FK → `crm.stage`) drives kanban position; `probability` (0-100 float) drives forecasting and is constrained to 100 on Won stages.
- `won_status` computed field: `won` / `lost` / `pending`; `lost_reason_id` (FK → `crm.lost.reason`) captures why deals die.
- Revenue split into `expected_revenue` (one-shot) + `recurring_revenue` + `recurring_plan` (monthly/yearly), with `prorated_revenue` = expected × probability ÷ 100.
- Contact info lives directly on the lead (`partner_name`, `contact_name`, `email_from`, `phone`) — `partner_id` (FK → `res.partner`) is optional and only populated when a real contact record exists.
- Assignment: `user_id` (salesperson) and `team_id` (sales team, auto-computed from user).
- UTM tracking trio (`campaign_id`, `medium_id`, `source_id`) plus `tag_ids`.
- Date trail: `create_date`, `date_open`, `date_conversion`, `date_deadline`, `date_closed`, `date_last_stage_update`.

**Workflows**
- Lead → Opportunity via `convert_opportunity()` which flips `type`, sets `date_conversion`, and runs `_handle_partner_assignment()` to create/link a `res.partner`.
- Opportunity advances through user-configurable `crm.stage` records; reaching a Won stage forces probability to 100; Lost path sets `won_status=lost` and requires a `lost_reason_id`.

**Dependencies on other Odoo addons** — `base_setup`, `base_install_request`, `sales_team`, `mail`, `calendar`, `resource`, `utm`, `web_tour`, `contacts`, `digest`, `phone_validation`.

**Notable features to consider stealing**
- The lead-vs-opportunity unification on one table (cheap, avoids dual schemas).
- Prorated revenue as a derived column for instant forecast rollups.
- `lost_reason_id` as a structured taxonomy — much better than free-text "why did we lose this" notes.
- Stage table is data, not code — admins reconfigure pipelines without touching the schema.

**Notable features to skip**
- UTM tracking (you're not running ad campaigns to attract engineering clients).
- Multi-team routing logic and team-based access rules.
- Phone validation against international formats.
- Recurring-revenue / MRR fields — irrelevant for project-based engineering work.

---

## sale

**Purpose** — Convert customer-facing quotations into confirmed sales orders that feed invoicing and (optionally) delivery.

**Key data model**
- `sale.order` header with `state`: `draft` (quotation), `sent` (emailed), `sale` (confirmed), `cancel`. A `locked` boolean prevents further edits.
- `partner_id` plus computed `partner_invoice_id` and `partner_shipping_id` for split billing/shipping addresses.
- Dates: `date_order`, `commitment_date` (promised), `delivery_date` (computed), `validity_date` (quote expiry).
- `order_line` (one2many to `sale.order.line`) carries products, quantities, prices, taxes.
- Computed monetary fields: `amount_untaxed`, `amount_tax`, `amount_total`, plus `amount_to_invoice` / `amount_invoiced` / `amount_paid` aggregates.
- `invoice_status` (`no` / `to invoice` / `invoiced` / `upselling`) and `delivery_status` drive next-action UI.
- `invoicing_closed` boolean to manually mark "we're done billing this even if numbers disagree."

**Workflows**
- Quote → Sent → Confirmed: `action_quotation_sent()` → `action_confirm()` (transitions to `sale`, optionally fires `_send_order_confirmation_mail`).
- Cancel path: `action_cancel()` from any non-locked state; cleans up draft invoices.
- Invoice generation: `_create_invoices()` builds `account.move` records from `_get_invoiceable_lines()`, grouped by `_get_invoice_grouping_keys()` (partner, currency, fiscal position). **This is the integration seam with `account`.**

**Dependencies on other Odoo addons** — `sales_team`, `account_payment`, `utm`.

**Notable features to consider stealing**
- Quotation validity_date with auto-expiry — useful for engineering proposals.
- The `invoice_status` derived column as a clear "what's next" signal at the list level.
- Separating invoice address from shipping address on the order itself, not just the partner.
- The `_get_invoiceable_lines()` hook pattern — lets you bill progress (e.g., 30% on signing, 70% on delivery) without restructuring the order.

**Notable features to skip**
- Down-payment wizard and product-template down-payments (small firm just invoices manually in tranches).
- Pricelist machinery (you have one client, one price).
- Fiscal positions, tax mapping by region.
- `action_lock`/`action_unlock` audit ceremony — overkill at 5-15 employees.

---

## account

**Purpose** — Double-entry general ledger that records every financial event as a journal entry, with specialized "move types" for customer invoices, vendor bills, and credit notes.

**Key data model**
- `account.move` is the universal journal entry. `move_type`: `out_invoice` (customer invoice), `in_invoice` (vendor bill), `out_refund`/`in_refund` (credit notes), `out_receipt`/`in_receipt` (cash receipts), `entry` (manual GL).
- `state`: `draft` (editable) → `posted` (locked into ledger) → `cancel`.
- `line_ids` (one2many to `account.move.line`) are the actual debit/credit rows; the header just summarizes.
- `partner_id`, `journal_id` (which book it posts to), `date` (accounting date, may differ from invoice date), `currency_id`.
- Money: `amount_untaxed`, `amount_tax`, `amount_total`, `amount_residual` (outstanding balance after partial payments).
- `payment_state`: `not_paid` / `partial` / `in_payment` / `paid` / `reversed` / `blocked`.

**Workflows**
- Draft → Posted via `action_post()` (locks lines, assigns sequence number, validates balanced debits/credits).
- Reset to draft is permitted but audit-trailed; cancel creates a reversal entry rather than deleting.
- Reconciliation: payments (separate model) reconcile against `account.move.line` to advance `payment_state`.

**Dependencies on other Odoo addons** — `base_setup`, `onboarding`, `product`, `analytic`, `portal`, `digest`.

**Notable features to consider stealing**
- The `move_type` discriminator pattern: one table, many document flavors, cleaner than separate Invoice/Bill/CreditNote tables.
- `payment_state` derived from reconciliation rather than a manually-toggled boolean.
- `amount_residual` as a first-class column — instant AR aging without subqueries.
- Sequence-number-on-post (draft invoices stay unnumbered, only posted invoices consume an INV-#### slot — avoids gaps in the official record).

**Notable features to skip**
- Full double-entry GL — a 5-15 person engineering firm is best served by single-entry "invoices + payments + a quarterly export to QuickBooks." Don't reimplement Xero.
- Multi-currency, exchange-rate revaluation.
- Fiscal positions, tax codes, tax grids (US sales tax on engineering services is usually nil; let QB handle exceptions).
- Bank statement import / reconciliation engine.

---

## project

**Purpose** — Lightweight project + task tracker with kanban stages, dependencies, and hooks for time tracking.

**Key data model**
- `project.task` keyed to a `project_id` (required for normal tasks; "private tasks" without a project are explicitly forbidden by timesheets).
- `stage_id` (FK → `project.task.type`) for kanban columns; `state` selection separately tracks lifecycle: `01_in_progress`, `02_changes_requested`, `03_approved`, `04_waiting_normal`, `1_done`, `1_canceled`.
- `priority` (Low/Medium/High/Urgent), `user_ids` (many2many assignees — yes, multi-assignee by default), `tag_ids`.
- Hierarchy: `parent_id` for subtasks (circular-reference guard), `milestone_id` (FK → `project.milestone`).
- Dependencies: `depend_on_ids` ("Blocked By") and computed inverse `dependent_ids` ("Blocks"); `is_blocked_by_dependences()` checks if any blocker is still open.
- Scheduling: `date_deadline`, `date_assign` (auto-set on first assignment), `date_end` (set when stage is folded), `allocated_hours`, `subtask_allocated_hours` (computed sum of children).
- `is_template` for reusable task skeletons; `recurring_task` + `recurrence_id` for repeating work; `personal_stage_id` lets each user keep their own kanban independent of the shared stage.

**Workflows**
- Task lifecycle: create → assign (auto-stamps `date_assign`) → move through stages → folded stage triggers `date_end`.
- Dependency gating: tasks can be blocked by others; UI surfaces this but doesn't hard-block status changes.
- Subtask rollup: parent `allocated_hours` separate from children; total computed.

**Dependencies on other Odoo addons** — `analytic`, `base_setup`, `mail`, `portal_rating`, `resource`, `web`, `web_tour`, `digest`.

**Notable features to consider stealing**
- Personal stages — each engineer keeps their own "to do / doing / waiting" lanes without messing up the shared project kanban. Huge UX win.
- Task dependencies as a many2many (not a separate edges table) — cheap to implement.
- Stage `fold` flag drives "this stage means done-ish" without hardcoding stage names.
- Task templates (`is_template`) for repeatable engineering workflows (e.g., "new structural calc package").

**Notable features to skip**
- Portal rating (clients rating tasks).
- Recurring tasks — engineering work is usually one-shot.
- Milestones as a separate model — could be a tag or a date field for a small shop.
- Multi-company project filtering.

---

## hr

**Purpose** — Central employee directory with org chart, work contact info, and the system-user linkage other HR modules build on.

**Key data model**
- `hr.employee.name`, `work_email`, `work_phone`, `job_title`.
- `user_id` (FK → `res.users`) — the bridge between an employee record and a login. Often null for contractors.
- `parent_id` = manager (recursive hierarchy); `coach_id` is a separate mentoring relationship.
- `department_id` for grouping.
- `resource_calendar_id` (working hours schedule — drives leave duration math and timesheet expectations).
- `employee_type_id` (employee / contractor / intern / etc).
- `contract_date_start` / `contract_date_end`.
- `work_location_id` (office / home / other).
- `bank_account_ids` for payroll.
- `active` boolean for soft-deletes.

**Workflows**
- No state machine — this is a master-data module. Onboarding/offboarding is implicit (toggle `active`, set contract dates).
- The `user_id` ↔ `employee_id` link is consulted by every other HR module to figure out "whose record is this."

**Dependencies on other Odoo addons** — `base_setup`, `digest`, `phone_validation`, `resource_mail`, `web_hierarchy`.

**Notable features to consider stealing**
- The user-vs-employee separation: not every employee needs a system login (contractors, field staff). Don't conflate auth with HR records.
- `resource_calendar_id` as a reusable "working hours" object — referenced by timesheets, leaves, and project scheduling.
- Manager-as-self-FK for an instant org chart with no extra table.

**Notable features to skip**
- `web_hierarchy` dependency (fancy org-chart widget — overkill for 5-15 people).
- Skills, certifications, departments-of-departments.
- Coach relationship as a separate FK — folds into manager for a small firm.
- Multi-company employee assignment.

---

## hr_timesheet

**Purpose** — Let employees log time against project tasks; rolls into analytic accounting and project cost.

**Key data model**
- Reuses `account.analytic.line` rather than introducing a new table — timesheets are just analytic lines with `project_id` set.
- `employee_id`, `user_id` (computed from employee), `date`, `unit_amount` (hours).
- `project_id` is **required** for timesheets (only projects with `allow_timesheets=True`).
- `task_id` optional; if set, must belong to the project.
- `name` = description, defaults to `/` if blank.
- `partner_id`, `department_id`, `manager_id`, `company_id` all derived from the task/project/employee.

**Workflows**
- No built-in approval state in this addon — entries are created and live. (Enterprise/Timesheet adds a validation layer; community version is open-edit with access-control gating.)
- Access rule: "you cannot access timesheets that are not yours" unless the user is in the approver group.
- Validation rules: no logging on private tasks, archived employees blocked, analytic account required, all related records must share `company_id`.

**Dependencies on other Odoo addons** — `hr`, `analytic`, `project`, `uom`.

**Notable features to consider stealing**
- **Piggybacking timesheets onto analytic lines** rather than a parallel table — single source of truth for "how was time/cost spent." For a Streamlit app this might mean: one `time_entries` table that doubles as the analytic ledger.
- Auto-derivation of partner/department/manager from upstream records — the user types task + hours, everything else fills in.
- Soft validation via constraints rather than a heavy state machine.

**Notable features to skip**
- Analytic accounting machinery if you're not doing project cost rollups in-platform (you might just export hours to QuickBooks for billing).
- UOM (unit of measure) abstraction — engineers log hours, full stop.
- Multi-company isolation rules.
- The "private task" carve-out — you don't have private tasks.

---

## hr_expense

**Purpose** — Capture employee expenses (receipts, mileage, etc.), route through manager approval, and post to the GL — optionally rebilling to a customer sale order.

**Key data model**
- `hr.expense` line items: `employee_id`, `product_id` (expense category), `date`, `quantity`, plus a tax-aware amount stack (`total_amount_currency`, `untaxed_amount`, `tax_amount`, `currency_rate`).
- `payment_mode`: `own_account` (employee paid, needs reimbursement) vs `company_account` (company card, no reimbursement owed).
- `vendor_id` for company-paid expenses; `account_id` for the expense GL line.
- `attachment_ids` for receipts; `duplicate_expense_ids` / `same_receipt_expense_ids` computed warnings.
- `analytic_distribution` JSON for splitting cost across projects.
- `account_move_id` links to the posted journal entry.
- Two state fields: `approval_state` (`submitted`/`approved`/`refused`) and a computed `state` that adds `draft`/`posted`/`in_payment`/`paid`.
- `existing_bill_id` lets you reconcile against an already-imported vendor bill.

**Workflows**
- **Draft → Submit → Approve → Post → Pay.** `action_submit()` notifies manager; `action_approve()` (manager) sets approval_state; `action_post()` (accountant) creates the `account.move`; reconciliation flips `state` to `paid`.
- `action_reset()` reverses posted moves and returns to draft.
- `action_refuse()` requires a reason, posts as comment.
- Optional auto-approve if no manager is assigned.

**Dependencies on other Odoo addons** — `account`, `web_tour`, `hr`.

**Notable features to consider stealing**
- Duplicate-receipt detection via attachment checksum — great way to catch double submissions.
- The own-account vs company-account split — same form, two different downstream accounting paths.
- Receipt attachment as a first-class field, not an afterthought.
- Reimbursable-to-customer linkage (`sales_order_id` in extensions) — relevant for engineering firms that re-bill travel.

**Notable features to skip**
- Multi-currency expense rate-of-day handling.
- Tax breakdown on expenses (US receipts already include tax in the total).
- The dual `approval_state` + computed `state` complexity — one state field is enough for a small firm.
- Auto-approve fallback when no manager is set — small firm always has a manager.

---

## hr_holidays

**Purpose** — Manage time-off requests, allocations (PTO balances), and approval workflow.

**Key data model**
- `hr.leave` request: `employee_id`, `holiday_status_id` / `work_entry_type_id` (leave type: vacation, sick, unpaid, etc.).
- `request_date_from` / `request_date_to` (user-facing date inputs) vs computed `date_from` / `date_to` (UTC datetimes used internally).
- `number_of_days`, `number_of_hours` (computed against `resource_calendar_id`).
- `state`: `confirm` (submitted) → `validate1` (first-level approved) → `validate` (final) → optionally `refuse` or `cancel`.
- `validation_type` on the leave-type config: `no_validation` / `manager` / `hr` / `both` (two-level: manager then HR).
- Allocation system (`hr.leave.allocation`, parallel model): grants PTO balance per employee per type; leave requests draw against it.

**Workflows**
- Employee submits → state `confirm` → manager (or HR) approves → state advances to `validate1` (if two-level) or `validate` (if single). Two-level requires HR to validate after manager.
- On final validation: a `resource.calendar.leaves` block is written (so other systems see the unavailability) and optionally a calendar meeting is created.
- Refuse / cancel paths available; `can_approve`, `can_validate`, `can_refuse`, `can_cancel` are computed per user.

**Dependencies on other Odoo addons** — `hr_work_entry`, `hr_calendar`, `resource`.

**Notable features to consider stealing**
- The allocation vs request split — balance lives on its own record, requests draw from it. Makes "how much PTO do I have left" a trivial query.
- Leave-type as a configurable record with its own validation flow (manager-only sick days, HR-approved bereavement, etc.).
- Writing approved leaves into `resource.calendar.leaves` so they automatically blank out timesheet/scheduling availability — great cross-module pattern.
- Mandatory-day constraints (block requests on critical dates).

**Notable features to skip**
- Two-level approval (`both` validation_type) — a 5-15 person firm doesn't have a manager + HR officer chain; one approver is enough.
- Public holiday calendar import per country.
- Allocation accrual rules (e.g., "1.5 days per month worked") — simpler to set an annual balance manually.
- Integration with payroll work entries (`hr_work_entry` dependency) — you don't run payroll in-platform.

---

## Cross-module integration notes for the Streamlit rebuild

- **sale → account**: `sale.order._create_invoices()` builds `account.move` records with `move_type='out_invoice'`, lines linked back via `sale_line_ids`. In a Streamlit port this becomes a single "Generate Invoice" button on the sale order that inserts an invoice row + line rows referencing the sale order.
- **project ↔ hr_timesheet**: timesheets are analytic lines tied to `project_id` + optional `task_id`. Consider unifying time_entries + analytic ledger into one table from day one.
- **hr_expense → account**: posting creates an `account.move` (`in_receipt` for employee-paid, vendor bill for company-paid). Same integration seam as sale→account, in reverse direction.
- **hr / hr_holidays / hr_timesheet**: all three lean on `resource_calendar_id` to know an employee's working hours. Build that calendar once and reuse it.
- **crm → sale**: not in this audit, but Odoo's pattern is "convert opportunity to quotation" which copies partner + estimated revenue into a new `sale.order` draft. Worth mirroring.
