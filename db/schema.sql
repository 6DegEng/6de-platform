-- 6th Degree Engineering — Company Platform Schema
-- SQLite database: platform.db

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ============================================================
-- CLIENTS
-- ============================================================
CREATE TABLE IF NOT EXISTS clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    company         TEXT,
    email           TEXT,
    phone           TEXT,
    address         TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECTS
-- ============================================================
CREATE TABLE IF NOT EXISTS projects (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_number      TEXT    NOT NULL UNIQUE,          -- YYMMDD format
    name            TEXT    NOT NULL,
    client_id       INTEGER REFERENCES clients(id),
    address         TEXT,
    city            TEXT    DEFAULT 'Miami',
    county          TEXT    DEFAULT 'Miami-Dade',
    state           TEXT    DEFAULT 'FL',
    status          TEXT    NOT NULL DEFAULT 'active'
                    CHECK (status IN (
                        'prospect','active','drafting','ahj_permitting',
                        'inspection','revisions','on_hold',
                        'completed','cancelled','archived'
                    )),
    scope           TEXT,                              -- brief description
    start_date      TEXT,
    target_end_date TEXT,
    actual_end_date TEXT,
    folder_path     TEXT,                              -- relative path under Active Projects
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECT MILESTONES
-- ============================================================
CREATE TABLE IF NOT EXISTS milestones (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            TEXT    NOT NULL,
    due_date        TEXT,
    completed_date  TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','in_progress','completed','skipped')),
    sort_order      INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROPOSALS
-- ============================================================
CREATE TABLE IF NOT EXISTS proposals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    proposal_number TEXT    NOT NULL,                   -- e.g. "Proposal - Roofing Recert"
    scope_text      TEXT,
    fee_amount      REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','sent','accepted','declined','revised')),
    sent_date       TEXT,
    accepted_date   TEXT,
    file_path       TEXT,                              -- path to .docx/.pdf
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INVOICES
-- ============================================================
CREATE TABLE IF NOT EXISTS invoices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    invoice_number  TEXT    NOT NULL UNIQUE,            -- YYMMDD-# format
    description     TEXT,
    amount          REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','sent','paid','overdue','void')),
    issue_date      TEXT    NOT NULL,
    due_date        TEXT,
    paid_date       TEXT,
    paid_amount     REAL    DEFAULT 0,
    payment_method  TEXT,
    file_path       TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PERMITS
-- ============================================================
CREATE TABLE IF NOT EXISTS permits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    permit_number   TEXT,                              -- county permit number
    folio_number    TEXT,                              -- property folio
    permit_type     TEXT    NOT NULL
                    CHECK (permit_type IN (
                        'building','roofing','electrical','mechanical','plumbing',
                        'recertification','demolition','other'
                    )),
    address         TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending','submitted','in_review','approved','issued',
                        'expired','failed_inspection','closed','extension_requested'
                    )),
    submitted_date  TEXT,
    approved_date   TEXT,
    expiration_date TEXT,
    inspection_date TEXT,
    jurisdiction    TEXT    DEFAULT 'Miami-Dade County RER',
    inspector_name  TEXT,
    case_number     TEXT,                              -- for code enforcement / CCA
    cca_deadline    TEXT,                              -- Compliance Consent Agreement deadline
    extension_deadline TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- CONTACTS (county officials, attorneys, inspectors, etc.)
-- ============================================================
CREATE TABLE IF NOT EXISTS contacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    title           TEXT,
    organization    TEXT,
    department      TEXT,
    email           TEXT,
    phone           TEXT,
    role_type       TEXT    CHECK (role_type IN (
                        'county_official','inspector','attorney','contractor',
                        'architect','consultant','other'
                    )),
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- ACTIVITY LOG (cross-module audit trail)
-- ============================================================
CREATE TABLE IF NOT EXISTS activity_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT    NOT NULL,                   -- 'project','invoice','permit', etc.
    entity_id       INTEGER NOT NULL,
    action          TEXT    NOT NULL,                   -- 'created','updated','status_change', etc.
    details         TEXT,                               -- JSON blob with change details
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- EMPLOYEES
-- ============================================================
CREATE TABLE IF NOT EXISTS employees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL,
    email           TEXT,
    phone           TEXT,
    role            TEXT    NOT NULL
                    CHECK (role IN (
                        'principal','expert_consultant','professional_engineer',
                        'field_inspector','engineering_technician','cad_drafter','admin'
                    )),
    is_active       INTEGER NOT NULL DEFAULT 1,
    hire_date       TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- FEE SCHEDULE (versioned role-based rates)
-- ============================================================
CREATE TABLE IF NOT EXISTS fee_schedule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    role            TEXT    NOT NULL,
    hourly_rate     REAL    NOT NULL,
    effective_date  TEXT    NOT NULL,
    end_date        TEXT,
    description     TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(role, effective_date)
);

-- ============================================================
-- TIME ENTRIES
-- ============================================================
CREATE TABLE IF NOT EXISTS time_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id     INTEGER NOT NULL REFERENCES employees(id),
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    entry_date      TEXT    NOT NULL,
    hours           REAL    NOT NULL CHECK (hours > 0),
    role            TEXT    NOT NULL,
    rate            REAL    NOT NULL,
    multiplier      REAL    NOT NULL DEFAULT 1.0,
    billable        INTEGER NOT NULL DEFAULT 1,
    description     TEXT,
    invoice_id      INTEGER REFERENCES invoices(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- EXPENSES
-- ============================================================
CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    employee_id     INTEGER REFERENCES employees(id),
    expense_date    TEXT    NOT NULL,
    category        TEXT    NOT NULL
                    CHECK (category IN (
                        'travel','mileage','materials','filing_fees',
                        'printing','software','equipment','subcontractor','other'
                    )),
    description     TEXT,
    amount          REAL    NOT NULL CHECK (amount >= 0),
    markup_pct      REAL    NOT NULL DEFAULT 15.0,
    reimbursable    INTEGER NOT NULL DEFAULT 1,
    receipt_path    TEXT,
    invoice_id      INTEGER REFERENCES invoices(id),
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- OPPORTUNITIES (CRM pipeline)
-- ============================================================
CREATE TABLE IF NOT EXISTS opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id       INTEGER REFERENCES clients(id),
    project_id      INTEGER REFERENCES projects(id),
    name            TEXT    NOT NULL,
    service_line    TEXT
                    CHECK (service_line IN (
                        'structural','civil','sirs','forensics','pools',
                        'recertification','threshold','government','other'
                    )),
    stage           TEXT    NOT NULL DEFAULT 'lead'
                    CHECK (stage IN (
                        'lead','qualifying','proposal_sent','negotiating',
                        'won','lost','dormant'
                    )),
    estimated_value REAL    DEFAULT 0,
    probability     INTEGER DEFAULT 50 CHECK (probability BETWEEN 0 AND 100),
    source          TEXT
                    CHECK (source IN (
                        'referral','repeat','website','bid_portal',
                        'cold_outreach','conference','other'
                    )),
    close_date      TEXT,
    contact_name    TEXT,
    contact_email   TEXT,
    contact_phone   TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- INVOICE LINE ITEMS
-- ============================================================
CREATE TABLE IF NOT EXISTS invoice_line_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id      INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_type       TEXT    NOT NULL
                    CHECK (line_type IN ('time','expense','fixed_fee','adjustment')),
    description     TEXT,
    quantity        REAL    DEFAULT 1,
    unit_rate       REAL    DEFAULT 0,
    amount          REAL    NOT NULL DEFAULT 0,
    time_entry_id   INTEGER REFERENCES time_entries(id),
    expense_id      INTEGER REFERENCES expenses(id),
    sort_order      INTEGER DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PAYMENT SCHEDULES
-- ============================================================
CREATE TABLE IF NOT EXISTS payment_schedules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    description     TEXT    NOT NULL,
    percentage      REAL    NOT NULL CHECK (percentage > 0 AND percentage <= 100),
    amount          REAL,
    due_trigger     TEXT
                    CHECK (due_trigger IN (
                        'on_acceptance','on_submission','on_completion',
                        'net_30','net_60','custom_date'
                    )),
    due_date        TEXT,
    invoice_id      INTEGER REFERENCES invoices(id),
    status          TEXT    NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','invoiced','paid')),
    sort_order      INTEGER DEFAULT 0,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- BID OPPORTUNITIES (government RFQ/RFP tracking)
-- ============================================================
CREATE TABLE IF NOT EXISTS bid_opportunities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id  INTEGER REFERENCES opportunities(id),
    portal          TEXT    NOT NULL
                    CHECK (portal IN (
                        'MFMP','DemandStar','BidNet','Sam.gov','county_direct','other'
                    )),
    solicitation_number TEXT,
    title           TEXT    NOT NULL,
    agency          TEXT,
    submission_deadline TEXT,
    question_deadline   TEXT,
    pre_bid_date    TEXT,
    estimated_value REAL,
    status          TEXT    NOT NULL DEFAULT 'monitoring'
                    CHECK (status IN (
                        'monitoring','go','no_go','preparing','submitted',
                        'won','lost','cancelled','protest'
                    )),
    go_no_go_date   TEXT,
    go_no_go_notes  TEXT,
    compliance_items TEXT,
    file_path       TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- SUBCONSULTANTS
-- ============================================================
CREATE TABLE IF NOT EXISTS subconsultants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name    TEXT    NOT NULL,
    contact_name    TEXT,
    email           TEXT,
    phone           TEXT,
    specialty       TEXT,
    rate_card       TEXT,
    w9_on_file      INTEGER DEFAULT 0,
    insurance_expiry TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id),
    subconsultant_id INTEGER NOT NULL REFERENCES subconsultants(id),
    po_number       TEXT    NOT NULL UNIQUE,
    description     TEXT,
    amount          REAL    NOT NULL DEFAULT 0,
    markup_pct      REAL    NOT NULL DEFAULT 15.0,
    status          TEXT    NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft','issued','partially_invoiced','complete','cancelled')),
    issued_date     TEXT,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- DOCUMENTS (file references linked to any entity)
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT    NOT NULL,
    entity_id       INTEGER NOT NULL,
    doc_type        TEXT    NOT NULL
                    CHECK (doc_type IN (
                        'proposal','invoice','calc_pdf','permit_drawing',
                        'correspondence','photo','contract','report','other'
                    )),
    file_name       TEXT    NOT NULL,
    file_path       TEXT    NOT NULL,
    version         INTEGER DEFAULT 1,
    notes           TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- CALC PROJECT LINKS (bridge ERP ↔ calc engine)
-- ============================================================
CREATE TABLE IF NOT EXISTS calc_project_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    erp_project_id  INTEGER NOT NULL REFERENCES projects(id),
    calc_project_id INTEGER NOT NULL,
    structure_type  TEXT,
    scope_summary   TEXT,
    status          TEXT    DEFAULT 'active'
                    CHECK (status IN ('active','completed','archived')),
    linked_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECT NOTES (long-form per-project notes)
-- ============================================================
CREATE TABLE IF NOT EXISTS project_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,
    author      TEXT    NOT NULL DEFAULT 'Juan',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECT CONTACTS (per-project stakeholder roster)
-- ============================================================
CREATE TABLE IF NOT EXISTS project_contacts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT    NOT NULL,
    role        TEXT    NOT NULL DEFAULT 'other'
                CHECK (role IN (
                    'client','contractor','architect','inspector',
                    'ahj','subcontractor','other'
                )),
    email       TEXT,
    phone       TEXT,
    company     TEXT,
    notes       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- PROJECT UPDATES (timestamped status feed)
-- ============================================================
CREATE TABLE IF NOT EXISTS project_updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'status'
                CHECK (category IN (
                    'status','permitting','client_communication',
                    'internal_note','billing'
                )),
    author      TEXT    NOT NULL DEFAULT 'Juan',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- SAVED VIEWS (user-defined grid configurations)
-- ============================================================
CREATE TABLE IF NOT EXISTS saved_views (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id   TEXT    NOT NULL DEFAULT 'default',
    name            TEXT    NOT NULL,
    scope           TEXT    NOT NULL DEFAULT 'private'
                    CHECK (scope IN ('private', 'shared')),
    filters_json    TEXT,                               -- JSON: status, priority, etc.
    columns_json    TEXT,                               -- JSON: visible columns + order
    sort_json       TEXT,                               -- JSON: sort field + direction
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(owner_user_id, name)
);

CREATE INDEX IF NOT EXISTS idx_saved_views_owner ON saved_views(owner_user_id);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_job ON projects(job_number);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE INDEX IF NOT EXISTS idx_invoices_project ON invoices(project_id);
CREATE INDEX IF NOT EXISTS idx_permits_status ON permits(status);
CREATE INDEX IF NOT EXISTS idx_permits_project ON permits(project_id);
CREATE INDEX IF NOT EXISTS idx_permits_expiration ON permits(expiration_date);
CREATE INDEX IF NOT EXISTS idx_milestones_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_entity ON activity_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_fee_schedule_role ON fee_schedule(role, effective_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_project ON time_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_time_entries_employee ON time_entries(employee_id);
CREATE INDEX IF NOT EXISTS idx_time_entries_date ON time_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_time_entries_invoice ON time_entries(invoice_id);
CREATE INDEX IF NOT EXISTS idx_expenses_project ON expenses(project_id);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_opportunities_stage ON opportunities(stage);
CREATE INDEX IF NOT EXISTS idx_opportunities_client ON opportunities(client_id);
CREATE INDEX IF NOT EXISTS idx_line_items_invoice ON invoice_line_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_payment_schedule_project ON payment_schedules(project_id);
CREATE INDEX IF NOT EXISTS idx_bids_deadline ON bid_opportunities(submission_deadline);
CREATE INDEX IF NOT EXISTS idx_bids_status ON bid_opportunities(status);
CREATE INDEX IF NOT EXISTS idx_po_project ON purchase_orders(project_id);
CREATE INDEX IF NOT EXISTS idx_documents_entity ON documents(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_calc_links_erp ON calc_project_links(erp_project_id);
CREATE INDEX IF NOT EXISTS idx_project_notes_project ON project_notes(project_id);
CREATE INDEX IF NOT EXISTS idx_project_contacts_project ON project_contacts(project_id);
CREATE INDEX IF NOT EXISTS idx_project_updates_project ON project_updates(project_id);

-- ============================================================
-- VIEWS
-- ============================================================

CREATE VIEW IF NOT EXISTS v_weekly_timesheet AS
SELECT
    e.name AS employee_name,
    te.entry_date,
    strftime('%W', te.entry_date) AS week_number,
    strftime('%Y', te.entry_date) AS year,
    p.job_number,
    p.name AS project_name,
    te.role,
    te.hours,
    te.rate,
    te.multiplier,
    ROUND(te.hours * te.rate * te.multiplier, 2) AS line_total,
    te.billable,
    te.description
FROM time_entries te
JOIN employees e ON e.id = te.employee_id
JOIN projects p ON p.id = te.project_id
ORDER BY te.entry_date DESC, e.name;

CREATE VIEW IF NOT EXISTS v_ar_aging AS
SELECT
    i.id,
    i.invoice_number,
    p.job_number,
    p.name AS project_name,
    c.name AS client_name,
    i.amount,
    i.paid_amount,
    (i.amount - COALESCE(i.paid_amount, 0)) AS balance_due,
    i.issue_date,
    i.due_date,
    CAST(julianday('now') - julianday(i.due_date) AS INTEGER) AS days_past_due,
    CASE
        WHEN julianday('now') - julianday(i.due_date) <= 0 THEN 'current'
        WHEN julianday('now') - julianday(i.due_date) <= 30 THEN '1-30'
        WHEN julianday('now') - julianday(i.due_date) <= 60 THEN '31-60'
        WHEN julianday('now') - julianday(i.due_date) <= 90 THEN '61-90'
        ELSE '90+'
    END AS aging_bucket
FROM invoices i
JOIN projects p ON p.id = i.project_id
LEFT JOIN clients c ON c.id = p.client_id
WHERE i.status IN ('sent', 'overdue')
ORDER BY days_past_due DESC;

CREATE VIEW IF NOT EXISTS v_pipeline_forecast AS
SELECT
    o.stage,
    o.service_line,
    COUNT(*) AS count,
    SUM(o.estimated_value) AS total_value,
    SUM(o.estimated_value * o.probability / 100.0) AS weighted_value
FROM opportunities o
WHERE o.stage NOT IN ('lost', 'dormant')
GROUP BY o.stage, o.service_line;

CREATE VIEW IF NOT EXISTS v_project_profitability AS
SELECT
    p.id AS project_id,
    p.job_number,
    p.name,
    COALESCE(t.total_labor, 0) AS total_labor_cost,
    COALESCE(e.total_expenses, 0) AS total_expenses,
    COALESCE(inv.total_invoiced, 0) AS total_invoiced,
    COALESCE(inv.total_paid, 0) AS total_paid,
    COALESCE(inv.total_invoiced, 0) - COALESCE(t.total_labor, 0) - COALESCE(e.total_expenses, 0)
        AS net_margin
FROM projects p
LEFT JOIN (
    SELECT project_id, ROUND(SUM(hours * rate * multiplier), 2) AS total_labor
    FROM time_entries GROUP BY project_id
) t ON t.project_id = p.id
LEFT JOIN (
    SELECT project_id, ROUND(SUM(amount * (1 + markup_pct / 100.0)), 2) AS total_expenses
    FROM expenses WHERE reimbursable = 1 GROUP BY project_id
) e ON e.project_id = p.id
LEFT JOIN (
    SELECT project_id,
           SUM(amount) AS total_invoiced,
           SUM(COALESCE(paid_amount, 0)) AS total_paid
    FROM invoices GROUP BY project_id
) inv ON inv.project_id = p.id;

-- ============================================================
-- TRANSACTIONS (accounting ledger)
-- ============================================================
CREATE TABLE IF NOT EXISTS transactions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date        TEXT    NOT NULL,
    account         TEXT,
    account_type    TEXT    CHECK (account_type IN ('Debit','Credit')),
    description     TEXT,
    amount          REAL    NOT NULL,
    balance         REAL,
    expense_category TEXT,
    txn_type        TEXT,
    project_id      INTEGER REFERENCES projects(id),
    month           INTEGER,
    source_row      INTEGER,
    imported_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (txn_date, amount, description)
);

CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_transactions_project ON transactions(project_id);
CREATE INDEX IF NOT EXISTS idx_transactions_category ON transactions(expense_category);

-- ============================================================
-- RECURRING EXPENSES
-- ============================================================
CREATE TABLE IF NOT EXISTS recurring_expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor          TEXT    NOT NULL,
    category        TEXT,
    monthly_amount  REAL    NOT NULL,
    frequency       TEXT    DEFAULT 'monthly',
    next_due_date   TEXT,
    active          INTEGER DEFAULT 1,
    notes           TEXT
);

-- ============================================================
-- PROJECT REVENUE (snapshot from accounting)
-- ============================================================
CREATE TABLE IF NOT EXISTS project_revenue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER REFERENCES projects(id),
    service         TEXT,
    amount_paid     REAL,
    cogs            REAL,
    profit          REAL,
    snapshot_date   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ============================================================
-- CASHFLOW VIEW
-- ============================================================
CREATE VIEW IF NOT EXISTS v_cashflow_monthly AS
SELECT
    strftime('%Y-%m', txn_date) AS month,
    SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END)  AS income,
    SUM(CASE WHEN amount < 0 THEN amount ELSE 0 END)  AS outflow,
    SUM(amount)                                        AS net
FROM transactions
GROUP BY strftime('%Y-%m', txn_date);

-- ============================================================
-- CATEGORIZATION RULES (transaction auto-categorization engine)
-- ============================================================
CREATE TABLE IF NOT EXISTS categorization_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT    NOT NULL UNIQUE,
    category    TEXT    NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 100,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_catrules_priority ON categorization_rules(priority);

-- ============================================================
-- SEED DATA: 2026 Fee Schedule
-- ============================================================
INSERT OR IGNORE INTO fee_schedule (role, hourly_rate, effective_date, description)
VALUES
    ('principal',              315.00, '2026-01-01', 'Principal'),
    ('expert_consultant',      260.00, '2026-01-01', 'Expert Consulting'),
    ('professional_engineer',  190.00, '2026-01-01', 'Professional Engineer'),
    ('field_inspector',        125.00, '2026-01-01', 'Field Inspector'),
    ('engineering_technician', 110.00, '2026-01-01', 'Engineering Technician'),
    ('cad_drafter',             80.00, '2026-01-01', 'CAD Drafter'),
    ('admin',                   65.00, '2026-01-01', 'Administrative/Clerical');

-- ============================================================
-- Calc Package Auditor — required checks per structure type
-- ============================================================
CREATE TABLE IF NOT EXISTS calc_required_checks (
    id INTEGER PRIMARY KEY,
    structure_type TEXT NOT NULL,
    check_label TEXT NOT NULL,
    code_ref TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'required',
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(structure_type, check_label)
);

-- ============================================================
-- ALTER TABLE extensions (idempotent via try/catch in Python)
-- These columns were added after the initial schema release.
-- SQLite does not support IF NOT EXISTS for ALTER TABLE,
-- so the Python init code wraps each in a try/except.
-- ============================================================
-- clients: ytd_revenue
-- projects: service_line, budget_amount, contract_value, amount_paid,
--           outstanding_balance, cogs, profit, percent_complete,
--           priority, action_by, next_action, lead_source
