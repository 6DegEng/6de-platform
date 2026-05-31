# Session 3c — SharePoint Mirror: Verification

**Date:** 2026-05-23
**Branch:** `feature/project-info-capture` (3c not split to its own branch yet)
**HEAD:** `556e035`
**Status:** Subagents 1–4 + 6 complete. Subagent 5 (auto-trigger) and the live SharePoint smoke (subagent 7 step a–f) **deferred** — see "Open items".

## Summary

The `_AUTO_project_summary.md` per-project markdown and
`_AUTO_portfolio_overview.xlsx` portfolio snapshot generators are in place,
backed by deterministic renderers and a sha256 short-circuiting upload layer.
A manual "Regenerate snapshots" button on the home sidebar and a
`scripts/regen_mirrors.py` CLI cover the on-demand path. **Auto-trigger on
mutation is not yet wired** — every regen today is initiated by Juan.

## Deliverables — per subagent

### 1. spec-writer
- No standalone spec doc was published; the prompt body and inline module
  docstrings in `modules/mirror/markdown.py`, `xlsx.py`, `sync.py` carry the
  contract. (Recommend back-filling `docs/specs/3c_mirror_design.md` if a
  future session needs the design rationale isolated.)

### 2. markdown-generator → `modules/mirror/markdown.py`
- Pure function: `render_project_summary(project, *, contacts, updates, notes, documents, today) -> str`.
- LF-only line endings, sorted contacts/updates/notes for determinism.
- Banner + footer with day-granular date for stable sha256.
- Sections: Overview, Dates, Financials, Contacts (table), Recent Updates
  (last 10), Notes, Documents (count per category).

### 3. xlsx-generator → `modules/mirror/xlsx.py`
- Pure function: `render_portfolio_overview(projects, *, base_url, platform_version, today) -> bytes`.
- 22-column header row mirroring legacy `Project_Tracker_2026.xlsx`.
- Conditional formatting: status fill, priority fill, % complete data bar,
  outstanding+completed red text.
- A1 bold-red banner.
- Second sheet `Generated` with metadata + project count.
- Byte-identical across renders for same input (verified by
  `test_byte_identical_across_renders`).

### 4. uploader → `modules/mirror/sync.py`
- `sync_project_markdown(conn, project_id, *, client, today, state, save, log_activity)`
- `sync_portfolio_xlsx(conn, *, client, today, base_url, platform_version, state, save, log_activity)`
- `sync_all(conn, *, client, today, include_portfolio)`
- sha256 short-circuit via `db/.mirror_state.json`.
- Stub mode falls back to `db/.snapshots/` for offline-readable artifacts.
- Activity log row written on every upload (`action='mirror_uploaded'`).

### 5. trigger-wirer — **PARTIALLY COMPLETE**
- Manual button on the home sidebar ("Regenerate snapshots") → calls
  `sync_all(ensure_db())`. Shows spinner + result counts.
- `scripts/regen_mirrors.py` CLI with `--all` / `--project ID` /
  `--portfolio-only` / `--commit` / `--dry-run` (dry-run is default).
- **NOT YET BUILT:** on-mutation trigger (project / notes / contacts /
  updates inserts enqueue a debounced regen). See "Open items".

### 6. idempotency-prover → `tests/test_mirror_*.py`
- `test_byte_identical_across_renders` (markdown + xlsx)
- `test_lf_line_endings_only`
- `test_contacts_sorted_deterministically`
- `test_second_sync_unchanged_short_circuits` (no upload on rerun)
- `test_sync_all_unchanged_on_second_run`
- 36 tests across the three mirror modules, all green.

### 7. integration-verifier — **OFFLINE PORTION DONE; LIVE PORTION DEFERRED**
- Offline pytest suite passes (see below).
- Live SharePoint smoke (steps a–f in the prompt) deferred — pending the
  next live run against the production tenant.

## Test results

```
$ python -m pytest tests/test_mirror_markdown.py tests/test_mirror_xlsx.py tests/test_mirror_sync.py -v
36 passed in 1.34s

$ python -m pytest -q
356 passed in 12.65s
```

## Activity log integration

The mirror layer writes `activity_log` rows with `action='mirror_uploaded'`.
`modules/projects/activity.py:_project_summary` recognizes the action and
renders `Mirror uploaded (_AUTO_project_summary.md)` /
`Mirror unchanged (_AUTO_project_summary.md)` (added 2026-05-23 follow-up).
Portfolio-scope writes use `entity_type='portfolio', entity_id=0` as the
NOT-NULL-FK sentinel.

## Open items (deferred)

### 1. On-mutation auto-trigger (subagent 5 remainder)

The prompt specifies a 60-second debouncer + background thread that calls
`sync_project_markdown` when projects / notes / contacts / updates change.
Not yet implemented. Risks to weigh before building:

- Streamlit reruns recreate the import graph per session — naive globals
  won't survive. Either use a module-level singleton guarded by a lock or
  spin a single daemon thread at launcher import time.
- OneDrive sync churn against `db/.mirror_state.json` from concurrent
  writers can corrupt JSON; needs file-locking or a single-writer
  enforcement.
- Live MSGraph calls from a background thread share the auth event loop
  set up in `modules/documents/sharepoint.py` — see Phase 2c "persistent
  event loop" note (`CHANGELOG.md` Session 2c).

Until this lands, regen is on-demand only (sidebar button or CLI).

### 2. Live SharePoint smoke checklist (subagent 7 part 2)

The prompt's checklist a–f (manual button writes file → confirm in OneDrive
web → edit a project → wait 60s → confirm change → run CLI dry-run →
confirm idempotent on second run) requires the live tenant. Run during the
next browser session with `.env` populated.

### 3. Optional spec doc

`docs/specs/3c_mirror_design.md` was called for in the prompt but skipped.
The renderers' docstrings carry the contract; a standalone doc would help
if Session 3c branches to its own feature branch later.
