# Session 3b — Project Information Capture: Verification

**Date:** 2026-05-23
**Branch:** `feature/project-info-capture`
**Base:** `eda0d34` (v3.4 post-cleanup); HEAD: `556e035`
**Status:** Subagents 1–7 complete; documented here for handoff.

## Summary

Session 3b expanded the Projects domain from "list of records" into a project
knowledge base. Three new tables (`project_notes`, `project_contacts`,
`project_updates`), four enforced fields on `projects` (priority, action_by,
next_action, percent_complete), an expanded status enum (5 → 10 values), and
three new tabs in the project detail view. Dry-run legacy xlsx importer
delivered as well.

## Deliverables — per subagent

### 1. spec-writer → `docs/specs/3b_data_model.md` (commit `83f2946`)
- Reads legacy `Project_Tracker_2026.xlsx` (sheet "Projects", 65 rows).
- Maps the 22 legacy columns to platform fields; flags new vs existing.
- Proposes 10-value status enum with hex colors.
- Defines `STATUS_TRANSITIONS` workflow.

### 2. schema-builder (commit `24235a8`)
- New tables: `project_notes`, `project_contacts`, `project_updates` with
  CASCADE FKs to `projects(id)` + indexes on `project_id`.
- `projects.status` CHECK constraint rebuilt via `_rebuild_projects_check_constraint`
  (gated behind `_meta.projects_status_expanded` so it only runs once).
- New statuses: `drafting`, `ahj_permitting`, `inspection`, `revisions`, `cancelled`.
- `_ALTER_COLUMNS` already had `priority`, `action_by`, `next_action`,
  `percent_complete`, `contact_name` — no migration required for those.

### 3. service-builder (commit `7c6122f`)
- `modules/projects/workflow.py`: `STATUS_TRANSITIONS`, `PRIORITY_VALUES`,
  `PRIORITY_LABELS`, `PRIORITY_COLORS`, percent-complete clamp helper.
- `modules/projects/crud.py:update_project`: status transition validation,
  unarchive flag, `status_changed` activity_log row distinct from generic
  `updated`.
- `modules/projects/activity.py`: recognizes `user_update`, `note_added`,
  `note_deleted`, `contact_added`, `contact_removed`, `update_deleted`,
  `mirror_uploaded` (added 2026-05-23 follow-up).
- Age (days) computed as a read-time derivation from `start_date`.

### 4. ui-builder (commit `6c864de`)
- `streamlit_app/pages/1_Projects.py` detail panel tabs now:
  `Details · Notes · Contacts · Updates · Activity · Milestones · Calculations · Documents · Edit`
- Top metadata row: Priority pill, % Complete bar, Action By, Next Action.
- "Add note", "Add contact", "Add update" forms in their respective tabs.
- All writes go through `modules/projects/{notes,contacts,updates}.py` —
  no raw SQL in pages.

### 5. legacy-importer (commit `1e00bff`)
- `scripts/import_legacy_xlsx.py` with `--dry-run` (default), `--commit`,
  `--since YYYY-MM-DD`.
- Column-map config + validation report.
- Idempotent: re-runs surface zero changes when data already imported.
- `docs/import/legacy_status_map.md` documents the legacy → platform value
  conversion (status + priority).
- **Not run with `--commit`** — Juan retains that decision.

### 6. ui-polish — table view extensions (commits `62e960f`, `fe4be3e`, `ac8db27`, `b2a8543`)
- Priority column (pill renderer), % Complete column (bar renderer),
  Action By, Next Action columns added to AgGrid.
- `lifecycle_bucket` computed column with group-by toggle.
- Status renderer rewritten as JsCode so HTML pills render instead of being
  escaped (fixes 3a Chrome smoke finding #1).
- Centralized status/priority palettes in `modules/status_colors.py` with
  WCAG-AA contrast gate (`tests/test_status_colors.py`).
- Saved Views feature (`modules/views/crud.py`, `tests/test_saved_views.py`)
  with bulk update bar + density toggle + column persistence.

### 7. integration-verifier (this doc)
- Smoke checklist below.

## 3a Chrome smoke findings — status

| # | Finding | Status | Where |
|---|---------|--------|-------|
| 1 | `<span>` HTML escaped in Status cell | **FIXED** | `project_grid.py:_build_status_renderer` (JsCode) |
| 2 | Table column headers truncated | **FIXED** | `min_width` set per column in `_build_grid_options` |
| 3 | AG Grid `#200` enterprise-module errors | **OPEN — needs decision** | `sideBar`, `rowGroupPanelShow`, `enableRowGroup` still present; `enable_enterprise_modules=False`. See "Open items" below. |
| 4 | Timeline y-axis labels truncated to 1-2 chars | **FIXED** | `automargin=True` on yaxis (2026-05-23 follow-up) |
| 5 | Home Vega-Lite "Infinite extent" warnings | **FIXED** | `if df["Count"].sum() > 0` guard on both chart blocks |
| 6 | Flaky `test_list_project_activity_paginates` (utcnow) | **FIXED** | `datetime.utcnow()` → `datetime.now(timezone.utc)` (commit `11b52d3`) |

## Test results

```
$ python -m pytest -q
356 passed in 12.65s
```

Breakdown of tests added during Session 3b:

| Test file | Test count | Scope |
|---|---|---|
| `test_project_notes_contacts_updates.py` | covers CRUD + activity_log emission for the three new tables |
| `test_project_workflow.py` | status transition validation, priority/percent helpers |
| `test_projects_inline_edit.py` | AgGrid save handler routes-through, rejects-invalid, no-change-noop |
| `test_projects_activity.py` | activity feed includes notes/contacts/updates, mirror_uploaded |
| `test_import_legacy.py` | legacy xlsx dry-run + status mapping + idempotency |
| `test_saved_views.py` | views CRUD + persistence |
| `test_project_grid_bulk.py` | bulk update bar |
| `test_status_colors.py` | WCAG-AA contrast for status/priority palette |

## Manual smoke (deferred to live browser walkthrough)

These checks are documented for the next browser session, since they
require a running Streamlit instance:

- [ ] Open a project → add a note → confirm it appears in Notes tab + Activity feed
- [ ] Add a contact (role=architect) → confirm role pill renders
- [ ] Add an update with category=permitting → confirm appears in Updates feed + Activity feed
- [ ] Change a project status → confirm `status_changed` row in Activity feed
- [ ] Set priority=urgent + percent_complete=50 → confirm pill + bar in AgGrid table view
- [ ] Run `python scripts/import_legacy_xlsx.py --dry-run` → review output

## Open items (deferred)

1. **AG Grid #200 enterprise-module errors (smoke #3).** `project_grid.py`
   uses `sideBar`, `rowGroupPanelShow`, `enableRowGroup`, `rowGroup` —
   community AG Grid logs `#200` for each on render. Two paths:
   - **(a) Strip the options** and lose the bucket-grouping feature shipped
     in commit `ac8db27`.
   - **(b) Set `enable_enterprise_modules=True`** in the `AgGrid()` call to
     load the enterprise JS. No license = non-blocking watermark in dev;
     deployment to a paid environment removes it.
   Decision needed from Juan.

2. **Disk-vs-DB audit results** (`scripts/audit_completed_projects.py`,
   `scripts/audit_disk_only_projects.py`, run 2026-05-23):
   - 19 completed projects (was 12 in `session_2c_blocked.md`) still have
     folders under `01_ Active Projects/`. Manual move to `00_Archive/`.
   - 3 orphan folders not in DB: `260304 - Buena Vista`, `260409 - 1390 S
     Ocean Blvd`, `260413 - 3107 PGA Blvd`. Backfill via legacy importer or
     archive.
   - 77 "ghost" DB rows with no folder — most are `prospect` rows that
     never had a folder created (expected); the `260304*` subprojects A-Y
     are tracked as discrete DB rows under one umbrella folder.

3. **31 unclassified subfolder names** in backfill scanner —
   `Reports`, `From Client`, `03_From Client`, `05_Reports`, etc.
   `modules/documents/sharepoint.py:classify_category` heuristic gap.
