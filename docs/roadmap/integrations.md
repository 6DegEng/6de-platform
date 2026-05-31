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

**Status — Phase 0 (composition) implemented 2026-05-30.**
`modules/integrations/delivery_email.py`: `is_delivery_milestone(name)` matches
a curated `DELIVERY_PATTERNS` list (conservative, so internal milestones don't
fire); `compose_delivery_email(conn, milestone_id)` builds recipient/subject/
body for a *completed* delivery milestone (returns `None` otherwise), resolving
the client email with a graceful fallback; `find_completed_delivery_milestones()`
is the future-sweep helper. **No SMTP/Graph send** — composition only, gated by
the `ENABLE_DELIVERY_EMAIL` flag. Covered by `tests/test_delivery_email.py`
(17 tests). **Next slice:** wire the actual send (Outlook SMTP or Graph) + a
milestone-completion hook, behind the flag.

## 3. Slack on Phase = Comments

Post to a project-specific or general Slack channel when a new
`project_update` is created with category `client_communication` or
`internal_note`. Useful for keeping the team aware of client-facing
activity without checking the platform.

**Status — Phase 0 (composition) implemented 2026-05-31.**
`modules/integrations/slack.py`: `should_notify(category)` (only
`client_communication` / `internal_note` notify); `compose_slack_message(conn,
update_id)` builds a Block Kit payload (header + section + context) + text
fallback for a notifiable update (returns `None` otherwise);
`find_notifiable_updates()` is the future-sweep helper. **No webhook POST** —
composition only, gated by `ENABLE_SLACK_NOTIFY`. Covered by
`tests/test_slack_notify.py` (11 tests). **Next slice:** wire a real incoming
webhook + a project-update hook, behind the flag.
