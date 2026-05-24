# Data Definitions

**Purpose:** Pin down what each named metric on the platform actually computes,
so two cards with similar names can't silently disagree. Written 2026-05-13
after Phase 0 verification found a $93,133 vs. $0 discrepancy between
Home.Income_YTD and Financials.Revenue_YTD with no UI explanation.

**Convention going forward:**
- Metric names that reference money are explicit about **cash basis** vs. **invoice basis**.
- Any metric on a card has a `help=` tooltip pointing back here.
- When two metrics compute the same concept differently, only one keeps the original name; the other is renamed or removed.

---

## 1. Cash Inflows YTD *(was: "Income YTD" on Home)*

**Source:** `transactions` table — the bank/CSV import via `import_accounting`.

**Definition (basis: cash, year-to-date):**
```sql
SELECT COALESCE(SUM(amount), 0)
FROM transactions
WHERE amount > 0
  AND strftime('%Y', date) = strftime('%Y', 'now');
```

**Where shown:** Home dashboard "Cash Inflows YTD" card.

**What it tells you:** *How much money actually landed in the bank account
this calendar year.* Includes client invoice payments, retainers,
reimbursements, refunds, and any other positive bank-feed entry.

**What it is NOT:** invoiced revenue. A $50K invoice sent in December but not
paid until January is invoiced revenue this year, cash inflow next year.

---

## 2. Cash Outflows YTD *(was: "Expenses YTD" on Home)*

**Source:** `transactions` table.

**Definition (basis: cash, year-to-date):**
```sql
SELECT ABS(COALESCE(SUM(amount), 0))
FROM transactions
WHERE amount < 0
  AND strftime('%Y', date) = strftime('%Y', 'now');
```

**Where shown:** Home dashboard "Cash Outflows YTD" card.

**What it tells you:** *Total money that left the bank account this calendar
year.* Rent, software, subcontractors, taxes, owner draws — everything.

---

## 3. Net Cashflow YTD

**Source:** `transactions` table.

**Definition:** `Cash Inflows YTD - Cash Outflows YTD` (signed; can be negative).

**Where shown:** Home dashboard "Net Cashflow YTD" card.

---

## 4. Invoiced Revenue YTD *(was: "Revenue YTD" on Financials)*

**Source:** `invoices` table.

**Definition (basis: invoice / accrual, year-to-date):**
```sql
SELECT COALESCE(SUM(paid_amount), 0)
FROM invoices
WHERE status = 'paid' AND paid_date >= <start-of-year>;
```

**Where shown:** Financials page "Invoiced Revenue YTD" card.

**What it tells you:** *Money recognized as revenue against issued invoices,
collected.* Driven by the invoice lifecycle, not the bank feed.

**Why this is $0 right now:** the `invoices` table is empty. ROADMAP item D
(Phase 6 — Money Flow) ships the first invoice lifecycle. Until then this
card is correctly $0; the platform doesn't have invoices to recognize.

**Why this differs from "Cash Inflows YTD":** they are different bases. Cash
Inflows ($93,133 today) includes every positive bank transaction; Invoiced
Revenue ($0 today) only counts money tied to invoices the platform issued.
Once Phase 6 ships and invoices flow through the platform, the two numbers
will converge but never equal — paid invoices = part of cash inflows; bank
deposits not tied to invoices (reimbursements, refunds, retainer draws,
non-AR income) will keep them distinct.

---

## 5. Outstanding (Invoices)

**Source:** `invoices` table.

**Definition:**
```sql
SELECT COALESCE(SUM(amount - COALESCE(paid_amount, 0)), 0)
FROM invoices
WHERE status IN ('sent', 'overdue');
```

**Where shown:** Home dashboard "Outstanding Revenue" card + Financials page.

---

## 6. Contracted Backlog *(was: "Outstanding (Projects)")*

**Source:** `projects` table — the `outstanding_balance` column populated by
the project tracker import.

**Definition:**
```sql
SELECT COALESCE(SUM(outstanding_balance), 0)
FROM projects;
```

**Where shown:** Home dashboard "Contracted Backlog" card.

**What it tells you:** *Total contracted work that has not yet been invoiced.*
This is the project-contract-residual — the difference between what's been
contracted and what's been billed. Renamed from "Outstanding" (2026-05-24)
to disambiguate from Outstanding AR on the Billing and Financials pages.

**Relationship to Outstanding (Invoices):** these will diverge until Phase 6
issues invoices for each project's balance. Today the Projects column is
populated from the Excel tracker (Juan's manual tracking); the Invoices
column is $0 (no invoices issued). After Phase 6, "Contracted Backlog"
becomes derived from the invoice ledger and the two converge.

---

## 7. Overdue Invoices

**Source:** `invoices` table.

**Definition:**
```sql
SELECT COALESCE(SUM(amount - COALESCE(paid_amount, 0)), 0)
FROM invoices
WHERE status = 'overdue';
```

**Where shown:** Home dashboard "Overdue Invoices" card + Financials.

**Note:** "overdue" is a status applied by an automation when `due_date <
today` for an unpaid invoice. ROADMAP item A (Phase 4 — Engineering Moat,
automations engine) adds the rule that flips `sent` → `overdue`.

---

## 8. Unbilled Work

**Source:** `time_entries` + `expenses` tables.

**Definition:**
```sql
-- Time component
SELECT COALESCE(SUM(hours * rate * multiplier), 0)
FROM time_entries
WHERE invoice_id IS NULL AND billable = 1;

-- Expense component (with markup)
SELECT COALESCE(SUM(amount * (1 + markup_pct / 100.0)), 0)
FROM expenses
WHERE invoice_id IS NULL AND reimbursable = 1;

-- Card shows the sum.
```

**Where shown:** Home dashboard "Unbilled Work" + Financials "Unbilled T&E".

**Note:** $0 today because `time_entries` and `expenses` are both empty.
Will populate once Timekeeping starts being used (now unblocked by B7 fix).

---

## 9. Pipeline Forecast (weighted)

**Source:** `opportunities` table.

**Definition:**
```sql
SELECT COALESCE(SUM(estimated_value * probability / 100.0), 0)
FROM opportunities
WHERE stage NOT IN ('lost', 'dormant', 'won');
```

**Where shown:** Home dashboard "Pipeline Forecast" card.

**Note:** $157,800 today, populated by the B5/I3 bridge that creates one
opportunity per imported proposal.

---

## 10. Monthly Burn

**Source:** `recurring_expenses` table.

**Definition:**
```sql
SELECT COALESCE(SUM(monthly_amount), 0)
FROM recurring_expenses
WHERE active = 1;
```

**Where shown:** Home dashboard "Monthly Burn" card.

---

## Maintenance

- When adding a new money metric, add it here with a SQL block. Two metrics
  computing the same concept different ways = the worst-of-both. Pick one
  name, one definition; the other goes away or renames.
- When renaming a metric in the UI, update this doc the same commit.
- Every metric card should pass a `help=` tooltip with one sentence; this doc
  is the long-form version.

---

## 11. Calc-Engine Project List (filtered)

**Source:** `projects` table in the calc-engine `common.db` (read-only bridge).

**Default behavior (hide_fixtures=True):**
```sql
SELECT ... FROM projects
WHERE LOWER(project_name) NOT LIKE 's26%'
  AND LOWER(project_name) NOT LIKE '%smoke%'
  AND LOWER(project_name) NOT LIKE '%fixture%'
  AND LOWER(project_name) NOT LIKE '%test%'
ORDER BY project_id DESC
```

**Where shown:** Calculator page (Link / Browse tabs), Projects page (Link
Calculator Project form).

**Why filtered:** The upstream calc engine's `common.db` contains test and
smoke-test entries (e.g., "S26 LIVE smoke") used during development. These
pollute the dropdown and confuse users. The filter is applied by default;
a "Show test/fixture data" toggle on the Calculator page disables it when
needed for debugging.

**Added:** 2026-05-24, Session 3c data-hygiene pass.

---

## Phase 0 follow-ups for the Financials page

- Rename `Revenue YTD` → `Invoiced Revenue YTD` (matches Home's "Cash Inflows YTD" pattern). **Done 2026-05-13.**
- Add `help=` tooltips on Financials KPI cards pointing back to this doc. **Done 2026-05-13.**
- Phase 6 (Money Flow) needs to reconcile "Outstanding (Projects)" vs. "Outstanding Revenue" by deriving the projects-level number from the invoice ledger.
