# Integrations Roadmap

First three integrations planned for a future session. No code exists
for these yet — this file tracks the intent so the roadmap lives in-repo.

## 1. QuickBooks Invoice Export

Push finalized invoices from the platform to QuickBooks Online via the
QBO API. Trigger: invoice status transitions to `sent`. Maps: project
name, client, line items, payment terms.

## 2. Email on Phase = Delivered

Send a notification email when a project hits a delivery milestone
(e.g. permit package submitted, report delivered). Trigger: milestone
status → `completed` where milestone name matches a delivery pattern.

## 3. Slack on Phase = Comments

Post to a project-specific or general Slack channel when a new
`project_update` is created with category `client_communication` or
`internal_note`. Useful for keeping the team aware of client-facing
activity without checking the platform.
