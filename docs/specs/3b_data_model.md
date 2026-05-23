# Session 3b — Data Model Specification

**Date:** 2026-05-23
**Branch:** `feature/project-info-capture`
**Base:** main @ `eda0d34` (v3.4 + cleanup)

## 1. Legacy xlsx analysis

Source: `06_Engineering/01_ Active Projects/Project_Tracker_2026.xlsx`, sheet "Projects" (headers row 3, 65 data rows).

### Columns already mapped to the platform

| xlsx Column | Platform Column | Notes |
|---|---|---|
| Project No | `projects.job_number` | YYMMDD integer in xlsx, TEXT in platform |
| Project Description / Address | `projects.name` + `projects.address` | Combined in xlsx, split in platform |
| Project Status | `projects.status` | **Enum mismatch** — see section 3 |
| Date Opened | `projects.start_date` | |
| Target Close | `projects.target_end_date` | |
| Company / Client | `clients.name` via `projects.client_id` | |
| Scope of Work | `projects.scope` | |
| Contract Value ($) | `projects.contract_value` | Already in `_ALTER_COLUMNS` |
| Amount Paid ($) | `projects.amount_paid` | Already in `_ALTER_COLUMNS` |
| Outstanding Balance ($) | `projects.outstanding_balance` | Already in `_ALTER_COLUMNS` |
| COGS | `projects.cogs` | Already in `_ALTER_COLUMNS` |
| Profit | `projects.profit` | Already in `_ALTER_COLUMNS` |
| % Complete | `projects.percent_complete` | Already in `_ALTER_COLUMNS` (REAL DEFAULT 0) |
| Priority | `projects.priority` | Already in `_ALTER_COLUMNS` (TEXT) |
| Action By | `projects.action_by` | Already in `_ALTER_COLUMNS` (TEXT) |
| Next Action | `projects.next_action` | Already in `_ALTER_COLUMNS` (TEXT) |
| Contact | `projects.contact_name` | Already in `_ALTER_COLUMNS` (TEXT) |

### Columns NOT yet mapped

| xlsx Column | Disposition |
|---|---|
| Folder | Skip — always "Open" in xlsx, not needed |
| Age (Days) | Derive as computed property: `today - start_date` |
| Notes | Already exists as `projects.notes` (free text). Keep as summary. Long-form notes go to `project_notes` table. |
| Process No. | Miami-Dade permit ID (e.g., `BD26001199001`). Already mapped to `permits.permit_number` in the permits module. No new column needed. |

## 2. New tables

### 2a. `project_notes` — long-form per-project notes

```sql
CREATE TABLE IF NOT EXISTS project_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,   -- markdown
    author      TEXT    NOT NULL DEFAULT 'Juan',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_project_notes_project ON project_notes(project_id);
```

**Use case:** Ongoing thoughts, design decisions, weird gotchas. Not ephemeral status updates.

### 2b. `project_contacts` — people involved per project

```sql
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
CREATE INDEX IF NOT EXISTS idx_project_contacts_project ON project_contacts(project_id);
```

**Relationship to existing `contacts` table:** The existing `contacts` table stores county officials, attorneys, inspectors — people who span multiple projects. `project_contacts` stores the per-project stakeholder roster (this project's client contact, this project's GC, etc.). No FK between them for now; that's a Phase 5 concern.

### 2c. `project_updates` — timestamped status feed

```sql
CREATE TABLE IF NOT EXISTS project_updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    content     TEXT    NOT NULL,   -- markdown
    category    TEXT    NOT NULL DEFAULT 'status'
                CHECK (category IN (
                    'status','permitting','client_communication',
                    'internal_note','billing'
                )),
    author      TEXT    NOT NULL DEFAULT 'Juan',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_project_updates_project ON project_updates(project_id);
```

**Use case:** "Spoke with FDOT today, they want revisions on sheet C-3"; "Invoice 260326-2 sent." The chatter pane.

**Relationship to `activity_log`:** `activity_log` is system-generated (project_created, status_changed, document_indexed). `project_updates` is human-authored. On every `project_updates` INSERT, also emit an `activity_log` row (action=`'user_update'`, details=`{"update_id": <id>, "category": "<cat>"}`) so the Activity tab from 3a surfaces both in one feed.

## 3. Status enum expansion

### Current platform values (CHECK constraint in schema.sql:34-35)

```
prospect | active | on_hold | completed | archived
```

### Legacy xlsx values

```
AHJ/Permitting | Completed | Drafting | Inspection | Revisions
```

### Proposed expanded enum

| Value | Label | Color | Source |
|---|---|---|---|
| `prospect` | Prospect | `#F7B500` (amber) | existing |
| `active` | Active | `#1FBA66` (green) | existing |
| `on_hold` | On Hold | `#A85FFF` (purple) | existing |
| `drafting` | Drafting | `#3B82F6` (blue) | new — from xlsx |
| `ahj_permitting` | AHJ/Permitting | `#F59E0B` (yellow) | new — from xlsx |
| `inspection` | Inspection | `#06B6D4` (cyan) | new — from xlsx |
| `revisions` | Revisions | `#EF4444` (red) | new — from xlsx |
| `completed` | Completed | `#9CA3AF` (gray) | existing |
| `cancelled` | Cancelled | `#6B7280` (dark gray) | new — per prompt |
| `archived` | Archived | `#374151` (charcoal) | existing |

### Migration approach

SQLite does not support `ALTER TABLE ... ALTER CONSTRAINT`. The migration will:

1. Update `schema.sql` with the expanded CHECK constraint (covers fresh installs).
2. Add a `_rebuild_projects_check_constraint()` function in `db/__init__.py` that:
   - Creates `projects_new` with the expanded CHECK
   - Copies all rows from `projects` to `projects_new`
   - Drops `projects`
   - Renames `projects_new` to `projects`
   - Rebuilds indexes and re-applies `_ALTER_COLUMNS` for the projects table
3. Gate this behind a `_meta` key (`projects_status_expanded`) so it only runs once.
4. Run inside a transaction with a backup-first approach.

**Risk:** CASCADE foreign keys (milestones, proposals, invoices, permits, etc.) reference `projects(id)`. SQLite's `PRAGMA foreign_keys=ON` enforces referential integrity on the renamed table, but the rebuild pattern preserves IDs so FKs stay valid. The `_ALTER_COLUMNS` columns must be re-added after the rebuild since the new table is created from `schema.sql` base DDL.

### xlsx-to-platform status mapping (for legacy importer)

| xlsx Status | Platform Status |
|---|---|
| AHJ/Permitting | `ahj_permitting` |
| Completed | `completed` |
| Drafting | `drafting` |
| Inspection | `inspection` |
| Revisions | `revisions` |

## 4. Existing column decisions

### `projects.notes` — keep as summary field

The existing `notes` TEXT column stays. It serves as a one-line summary (like a project tagline). Long-form notes go to `project_notes`. The legacy importer will preserve xlsx Notes as a `project_updates` entry with `category='internal_note'`.

### `projects.priority` — enforce enum at application level

The column already exists as `TEXT` with no CHECK constraint (via `_ALTER_COLUMNS`). Enforce valid values in the service layer:

```python
PRIORITY_VALUES = ('low', 'normal', 'high', 'urgent')
```

The legacy xlsx uses: On Hold, High, Medium, Low. Mapping:
- "On Hold" → `normal` (On Hold is a project status, not a priority; map to default)
- "High" → `high`
- "Medium" → `normal`
- "Low" → `low`

### `projects.percent_complete` — normalize to 0-100 integer

The column exists as `REAL DEFAULT 0`. The legacy xlsx stores mixed types (`"100%"`, `"75%"`, `0.5`, `1`). Normalize: parse to 0-100 integer. Clamp in service layer.

### Age (Days) — computed property, not persisted

```python
def get_project_age(project) -> int | None:
    if not project['start_date']:
        return None
    return (date.today() - date.fromisoformat(project['start_date'])).days
```

## 5. Status workflow

### Allowed transitions

```python
STATUS_TRANSITIONS = {
    'prospect':       {'active', 'cancelled', 'archived'},
    'active':         {'drafting', 'on_hold', 'ahj_permitting', 'inspection', 'revisions', 'completed', 'cancelled'},
    'drafting':       {'active', 'on_hold', 'ahj_permitting', 'revisions', 'cancelled'},
    'ahj_permitting': {'active', 'drafting', 'revisions', 'inspection', 'on_hold', 'cancelled'},
    'inspection':     {'active', 'revisions', 'completed', 'on_hold', 'cancelled'},
    'revisions':      {'active', 'drafting', 'ahj_permitting', 'inspection', 'on_hold', 'cancelled'},
    'on_hold':        {'active', 'prospect', 'drafting', 'ahj_permitting', 'cancelled'},
    'completed':      {'archived', 'active'},
    'cancelled':      {'archived', 'prospect'},
    'archived':       set(),  # must use explicit unarchive (→ active with flag)
}
```

**Unarchive:** `archived` → `active` requires explicit `unarchive=True` flag to prevent accidental reactivation.

### On every status change

1. Validate transition is allowed.
2. Write the `update_project()` as usual.
3. Emit an `activity_log` row with `action='status_changed'` (distinct from generic `updated`) and `details={"from": old_status, "to": new_status}`.

## 6. Open questions for Juan

1. **Status enum values:** The proposed 10 statuses above cover both the existing platform values and the legacy xlsx values. Does this list look right? Any to add or remove? In particular:
   - The xlsx had no "Prospect" — should we keep it?
   - Should "Drafting" be a status or is that just "Active" in practice?

2. **Priority "On Hold" in legacy xlsx:** The xlsx uses "On Hold" as a priority value (distinct from the project status "On Hold"). I'm mapping it to `normal` since On Hold is better represented as a status. Correct?

3. **Transition rules:** The workflow above is permissive (most statuses can reach most others). Should any transitions be locked down further?

4. **Archived unarchive:** Do you want `archived → active` to require confirmation, or is any status change from Archived blocked outright?

## 7. Summary of changes

| Area | Change | Migration? |
|---|---|---|
| `project_notes` table | New table + index | DDL in schema.sql |
| `project_contacts` table | New table + index | DDL in schema.sql |
| `project_updates` table | New table + index | DDL in schema.sql |
| `projects.status` CHECK | Expand from 5 to 10 values | Table rebuild migration |
| `projects.priority` | Already exists (TEXT) | No migration — enforce in Python |
| `projects.action_by` | Already exists (TEXT) | No migration |
| `projects.next_action` | Already exists (TEXT) | No migration |
| `projects.percent_complete` | Already exists (REAL) | No migration |
| `status_pills.py` | Add 5 new statuses + colors | Code change |
| `projects/crud.py` | Status workflow validation | Code change |
| `projects/activity.py` | Recognize `user_update` action | Code change |
| `1_Projects.py` | 3 new tabs (Notes/Contacts/Updates), metadata row in Details | Code change |
| `project_grid.py` | 4 new columns in aggrid | Code change |

## 8. Tab order (post-3b)

```
Details · Notes · Contacts · Updates · Activity · Milestones · Calculations · Documents · Edit
```

Edit moves to last position. Activity stays after Updates so the unified feed (system events + user updates) is adjacent to the user-authored Updates tab.
