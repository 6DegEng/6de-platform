# Integrations Roadmap

First three integrations planned for a future session. No code exists
for these yet — this file tracks the intent so the roadmap lives in-repo.

## 1. QuickBooks Invoice Export

Push finalized invoices from the platform to QuickBooks Online via the
QBO API. Trigger: invoice status transitions to `sent`. Maps: project
name, client, line items, payment terms.

**Status — Phase 0 (CSV) implemented 2026-05-29.** `modules/integrations/quickbooks.py`
exports finalized invoices (`sent`/`paid`/`overdue`) to a QuickBooks Online
import CSV — one row per line item, summary row for invoices without line
items, customer resolved from client company → client name → project label.
Pure data transform, no credentials; gated behind the `ENABLE_QBO_EXPORT`
feature flag in `config.py`. Covered by `tests/test_qbo_export.py` (9 tests).
**Next slice:** live QBO API push (OAuth2, invoice create) + Accounting-page
"Export to QuickBooks" button wired to the flag.

## 2. Email on Phase = Delivered

Send a notification email when a project hits a delivery milestone
(e.g. permit package submitted, report delivered). Trigger: milestone
status → `completed` where milestone name matches a delivery pattern.

## 3. Slack on Phase = Comments

Post to a project-specific or general Slack channel when a new
`project_update` is created with category `client_communication` or
`internal_note`. Useful for keeping the team aware of client-facing
activity without checking the platform.
