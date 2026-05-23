# Session 3a — Scout Report

**Branch:** feature/projects-ui-uplift
**Author:** scout subagent (research-only)
**Date:** 2026-05-23

---

## 1. Current Projects page architecture

The page is **629 LOC** in a single file: `streamlit_app/pages/1_Projects.py`. There
is no per-view sub-module — every concern (auth, fetch, stats, create form, search,
filter tabs, per-project list, edit form, milestones, calc links, documents) is
inlined. Render flow:

```
streamlit_app/pages/1_Projects.py
  L19-21   Path bootstrap (parents[2] -> platform root onto sys.path)
  L23-45   Imports from config / db / modules.calculator.bridge / modules.documents
           / modules.projects.crud / streamlit_app.auth
  L50      st.set_page_config(layout="wide")
  L51      require_auth()                            <-- AUTH GATE
  L52      st.title("Projects")
  L54      conn = ensure_db()                        <-- DB handle, st.cache_resource
  L59-73   Hard-coded _STATUS_COLORS / _STATUS_ICONS dicts (page-local)
  L75-80   _MILESTONE_ICONS dict
  L83-85   _status_badge(status) helper (icon + Title-cased label)
  L91      stats = get_project_stats(conn)
  L94-100  5-column metric row: Total / Active / Prospects / On Hold / Completed
  L105-157 Create-project expander w/ st.form, calls create_project() and st.rerun()
  L165-175 SEARCH FORM (Phase B fix — wraps text_input in st.form so Enter commits;
           submit_button label "Search"; key="project_search_query")
  L180-190 Status filter tabs (All / Active / Prospect / On Hold / Completed / Archived)
           with _TAB_STATUS_MAP[idx] -> status string or None
  L192-628 for tab_idx, tab in enumerate(tabs):
            with tab:
                status_filter = _TAB_STATUS_MAP[tab_idx]
                # FETCH BRANCH:
                if search_query.strip():
                    all_results = search_projects(conn, search_query.strip())     # L198
                    projects = [p for p in all_results if p["status"]==status_filter]
                                  if status_filter else all_results
                else:
                    projects = list_projects(conn, status_filter=status_filter)   # L204
                # RENDER LOOP — one st.expander per project:
                for proj in projects:                                              # L211
                    pid = proj["id"]
                    with st.expander(f"{badge}  **{header}**"):                    # L218
                        # 5 INNER TABS — Details / Edit / Milestones / Calculations / Documents
                        detail_tab, edit_tab, milestone_tab, calc_tab, docs_tab \
                            = st.tabs([...])                                       # L220
                        with detail_tab:    ...   (L225-246, read-only markdown)
                        with edit_tab:      ...   (L249-356, big st.form w/ Save+Delete,
                                                   widget keys namespaced
                                                   `f"t{tab_idx}_p{pid}"` — see B24)
                        with milestone_tab: ...   (L359-441, list_milestones + Mark-Complete
                                                   + add-milestone st.form)
                        with calc_tab:      ...   (L443-559, get_calc_connection() RO bridge,
                                                   subprocess.Popen launcher, link form)
                        with docs_tab:      ...   (L562-628, list_documents +
                                                   SharePoint category grouping)
```

### Non-obvious coupling points

- **Search re-runs the whole tab loop on every rerun.** The fetch branch at L197-204
  is inside the `for tab_idx, tab in enumerate(tabs)` loop, so EVERY status tab
  performs its own DB query on every rerun, even ones not currently visible —
  `st.tabs()` always renders all tab contents. With 6 tabs that's 6 queries per
  rerun. Switching to aggrid won't change this unless the next subagent collapses
  the data fetch above the view-switcher.
- **`st.expander` is what the AppTest tests bind to.** The 3 search tests in
  `tests/test_projects_search.py` call `_expander_labels(at)` which scans
  `at.expander` for labels containing `"—"`. Replacing the expanders with an aggrid
  table breaks that helper — tests will need rewriting (see §7, §8).
- **Per-widget keys are namespaced by tab index AND project id.** Pattern is
  `key=f"en_{key_ns}"` where `key_ns = f"t{tab_idx}_p{pid}"`. This is enforced by
  `tests/test_smoke.py:test_no_duplicate_widget_keys_in_projects_page` (regex grep
  on the page source, line 130-140 of test_smoke.py). Any new aggrid grids that
  use per-row widget keys MUST keep this pattern, or the smoke test breaks.
- **`subprocess.Popen([str(CALC_EXE_PATH)])` at L457.** Launches the calculator
  exe. Survives the rerun model because it's fire-and-forget. Won't affect aggrid.
- **`get_calc_connection()` opens a read-only connection inside the calc_tab block
  and closes it inline at L559.** Not cached across reruns; cheap. Leave alone.
- **`docs_tab` at L562-628 reads `documents` via `list_documents(...)` and groups
  by category derived from `notes` JSON or the file_path's penultimate segment.**
  This is its own brittle area but out of scope for Session 3a.

---

## 2. Persistence layer surface

All mutating project operations MUST go through `modules/projects/crud.py`. The
table-view-builder's aggrid save callback MUST funnel through `update_project()`.

### File: `modules/projects/crud.py`

| Function | Signature | What it logs to `activity_log` | What it validates |
|---|---|---|---|
| `_now()` | `() -> str` | n/a | helper — UTC `%Y-%m-%d %H:%M:%S` |
| `_generate_job_number(conn)` | `(sqlite3.Connection) -> str` | n/a | reads count of today's projects; appends suffix |
| `_log_activity(conn, entity_type, entity_id, action, details=None)` | full row | INSERT INTO activity_log w/ `_now()` as created_at | always writes `'{}'` when details is None (NOT None) |
| `list_projects(conn, status_filter=None)` | returns list[sqlite3.Row] | (read-only) | SELECT joins clients table for `client_name` |
| `get_project(conn, project_id)` | returns sqlite3.Row \| None | (read-only) | SELECT joins clients table |
| `create_project(conn, **kwargs)` → `int` | `**kwargs` mapped 1:1 to projects columns | writes `("project", new_id, "created", kwargs)` AFTER conn.commit() of the INSERT | auto-generates `job_number` if missing; auto-builds `folder_path` from job_number+name; sets `created_at`/`updated_at` to `_now()` |
| `update_project(conn, project_id, **kwargs)` → `None` | partial column updates | writes `("project", project_id, "updated", kwargs)` (kwargs INCLUDES the auto-added `updated_at`) | NO validation — caller is responsible for status enum, date format |
| `delete_project(conn, project_id)` → `None` | n/a | writes `("project", project_id, "deleted")` BEFORE the DELETE (so the log row survives) | n/a — CASCADE handles related rows |
| `list_milestones(conn, project_id)` | returns list | (read-only) | ORDER BY sort_order, due_date |
| `create_milestone(conn, project_id, name, due_date=None)` → `int` | | writes `("milestone", ms_id, "created", {project_id, name})` | auto-assigns next sort_order |
| `update_milestone(conn, milestone_id, **kwargs)` → `None` | | writes `("milestone", ms_id, "updated", kwargs)` | no validation |
| `get_project_stats(conn)` | returns dict[str, int] | (read-only) | GROUP BY status |
| `search_projects(conn, query)` | returns list[sqlite3.Row] | (read-only) | LIKE-matches `name`, `address`, `job_number` (NOT `scope`, NOT `notes`, NOT `client_name`) |

### Other writers to `projects` rows

- `modules/crm/crud.py:convert_opportunity_to_project()` (around L194-242 — uses
  raw SQL INSERT but DOES call `_log_activity(conn, "project", project_id, "created", {...})`
  with `source: "opportunity"`. This is the only OTHER path that creates project rows
  via the platform UI. The table-view-builder can ignore it — Session 3a doesn't
  touch CRM.

- `scripts/importers/import_project_tracker.py:226-301` writes raw INSERT/UPDATE
  to projects WITHOUT calling `_log_activity` per-project. It DOES write one
  summary `("importer", 0, "imported", {...})` at the end of the run (L484-497).
  Out of scope for Session 3a but worth knowing: importer-created projects have
  NO `entity_type='project'` activity rows.

### Service-layer guidance for table-view-builder

- For inline-edit save: build the changeset dict, call
  `update_project(conn, pid, **changes)`. It already calls `_log_activity` and
  commits twice (once for the UPDATE, once for the log row).
- For status changes via Kanban: same — `update_project(conn, pid, status=new_status)`.
- For row deletion: `delete_project(conn, pid)`. Per the prompt guardrails, the
  aggrid grid config MUST disable row deletion — but if a separate delete UI is
  added, route through this function.

---

## 3. activity_log shape

### Schema (db/schema.sql:158-165)

```sql
CREATE TABLE IF NOT EXISTS activity_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type     TEXT    NOT NULL,            -- 'project','invoice','permit', etc.
    entity_id       INTEGER NOT NULL,
    action          TEXT    NOT NULL,            -- 'created','updated','status_change', etc.
    details         TEXT,                        -- JSON blob with change details (NULL allowed)
    created_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_activity_entity ON activity_log(entity_type, entity_id);  -- L426
```

### Payload shape — IS `details` always valid JSON?

**No.** There is a known inconsistency across writers:

| Writer module | Empty-details behavior |
|---|---|
| `db.log_activity` | writes `'{}'` (json.dumps(details or {})) |
| `modules/projects/crud.py:_log_activity` | writes `'{}'` |
| `modules/permits/crud.py:_log_activity` | writes `'{}'` |
| `modules/crm/crud.py:_log_activity` | writes `'{}'` |
| `modules/bids/crud.py:_log_activity` | writes `'{}'` |
| `modules/subconsultants/crud.py:_log_activity` | writes `'{}'` |
| `modules/calculator/bridge.py:_log_activity` | writes `'{}'` |
| `modules/documents/crud.py:_log_activity` | writes `'{}'` |
| `modules/documents/sharepoint.py` (record_upload) | writes JSON dict (never empty in practice) |
| `modules/billing/crud.py:_log_activity` | writes `None` when details is empty (json.dumps OR None) |
| `modules/timekeeping/crud.py:_log_activity` | writes `None` when details is empty |
| `modules/invoicing/crud.py:_log_activity` | writes `None` when details is empty |

For the **per-project activity panel** specifically (filter `entity_type='project'`),
only `modules/projects/crud.py` and `modules/crm/crud.py:convert_opportunity_to_project`
write rows. Both write a JSON dict (`'{}'` or richer). Practically the project-scoped
panel will not encounter NULL details — but the renderer should still defensively
`json.loads(row["details"] or "{}")` so it doesn't crash on a future writer that
follows the billing pattern.

### Known event types for `entity_type='project'`

| Action | Source | Typical details payload |
|---|---|---|
| `created` | `modules/projects/crud.py:123` (called from page L155 "Create Project") | dict of all kwargs passed to `create_project()` — typically `{name, status, city, county, state, job_number, address?, scope?, start_date?, target_end_date?, notes?, folder_path, created_at, updated_at}` |
| `created` | `modules/crm/crud.py:233` (convert opportunity to project) | `{"source": "opportunity", "opportunity_id": int, "job_number": str}` |
| `updated` | `modules/projects/crud.py:142` (called from page L331 inline Save Changes) | dict of just the changed fields PLUS auto-added `updated_at`. From the existing edit form (L308-329) typical fields: `name`, `status`, `address`, `city`, `county`, `scope`, `notes`, `start_date`, `target_end_date`, `actual_end_date` |
| `deleted` | `modules/projects/crud.py:148` (called from page L349 confirm-delete) | `'{}'` (empty payload — only entity_id/action) |

There is **NO** `status_change` or `status_changed` event today — status changes
are bundled into a `updated` action with `{"status": "...new..."}` in the details.
The prompt mentions `status_changed` as a "known event type" but that's
aspirational language from Session 3b's planning. The activity-panel-builder
should recognize a status-change as: `action == "updated"` AND `"status" in details`.

For milestone activity, `entity_type='milestone'` not `project`. If we want the
project activity panel to include milestone events, the query needs a UNION:
```
SELECT * FROM activity_log
WHERE (entity_type='project' AND entity_id=?)
   OR (entity_type='milestone' AND json_extract(details, '$.project_id')=?)
ORDER BY created_at DESC
```
(Milestone create details include `project_id`; milestone updates do NOT — they
just have the milestone's own kwargs.) **Not requested by the prompt**, but worth
surfacing for the activity-panel-builder.

---

## 4. Status enum source of truth

The 5 status values `('prospect','active','on_hold','completed','archived')` are
hardcoded in **at least 7 places**:

1. `db/schema.sql:34-35` — `CHECK (status IN ('prospect','active','on_hold','completed','archived'))` — **canonical source**, enforced by SQLite
2. `streamlit_app/pages/1_Projects.py:59-65` — `_STATUS_COLORS` dict (page-local)
3. `streamlit_app/pages/1_Projects.py:67-73` — `_STATUS_ICONS` dict (page-local)
4. `streamlit_app/pages/1_Projects.py:121` — create-form selectbox options
5. `streamlit_app/pages/1_Projects.py:183-190` — `_TAB_STATUS_MAP` for filter tabs
6. `streamlit_app/pages/1_Projects.py:265-267` — edit-form selectbox options
7. `streamlit_app/components/formatters.py:152-159` — `_STATUS_COLORS["project"]` for the shared `status_badge()` helper
8. `streamlit_app/Home.py:442` — `status_order` for the dashboard chart
9. `scripts/importers/import_project_tracker.py:106-129` — normalizes inbound xlsx values to the enum
10. `streamlit_app/pages/3_Permits.py:210` — `WHERE status IN ('active', 'prospect', 'on_hold')` to filter available projects

**Risk:** if Session 3b adds a new status (e.g. `paused`), every one of these
needs touching. The view-switcher-builder should consider extracting an
authoritative `PROJECT_STATUSES` tuple into the same shared module that holds
the new color pills, but the prompt explicitly says "If status colors are already
defined somewhere, use those" — `streamlit_app/components/formatters.py:_STATUS_COLORS["project"]`
already exists but with a DIFFERENT palette from what the prompt asks for (see §6).

---

## 5. Existing st.session_state keys

Codebase-wide audit (every `st.session_state` access):

| Key | File:Line | Set by | Purpose |
|---|---|---|---|
| `authenticator` | `streamlit_app/auth.py:55,57,63` | auth module | cached `stauth.Authenticate` instance |
| `authentication_status` | `streamlit_app/auth.py:76,79` | `streamlit_authenticator` library | login state (None / False / True) |
| `username` | `streamlit_app/auth.py:92` | `streamlit_authenticator` library | logged-in username |
| `name` | (implicit from `streamlit_authenticator`) | library | display name |
| `last_audit_report` | `streamlit_app/pages/8_Calculator.py:308,310` | calc page | calc auditor report cache |
| `project_search_query` | `streamlit_app/pages/1_Projects.py:172` | widget key on `st.text_input` | search box value — survives reruns automatically via the widget key |
| `confirm_delete_{pid}` | `streamlit_app/pages/1_Projects.py:338,341,350,355` | inline assignment | per-project delete confirmation flag |

There are also many **widget keys** that Streamlit auto-stores in session_state
but the page never reads back — examples from `1_Projects.py`:
- `f"en_{key_ns}"`, `f"ea_{key_ns}"`, `f"ec_{key_ns}"`, etc. (edit form fields)
- `f"esd_{key_ns}"`, `f"ete_{key_ns}"`, `f"eae_{key_ns}"`, `f"eno_{key_ns}"`
- `f"ms_done_{ms_id}_{tab_idx}"`, `f"ms_toggle_{ms_id}_{tab_idx}"`
- `f"open_calc_{pid}_{tab_idx}"`, `f"calc_sel_{pid}_{tab_idx}"`

### Proposed `ui:projects:*` namespace

The proposed namespace from the prompt (`ui:projects:view`, `ui:projects:expanded`,
etc.) does NOT collide with any existing keys. **Safe to adopt.** Recommended keys:

| Proposed key | Type | Default | Purpose |
|---|---|---|---|
| `ui:projects:view` | `Literal["Table","Kanban","Timeline","Calendar"]` | `"Table"` | which of the 4 views is active |
| `ui:projects:expanded` | `set[int]` | `set()` | which project IDs are currently expanded in any per-row detail panel |
| `ui:projects:search_query` | `str` | `""` | search box value (could remain `project_search_query` for backward compat with the Phase B fix and the regression test at `tests/test_projects_search.py:138`) |
| `ui:projects:status_filter` | `Optional[str]` | `None` | currently-selected status tab (Kanban view doesn't need this, but Table+Timeline+Calendar do) |

**Note on `project_search_query`:** the Phase B regression test asserts the
literal label `"Search projects"` and checks `form_id` is non-empty
(`tests/test_projects_search.py:182-218`). The key name itself is not asserted by
the test, so renaming to `ui:projects:search_query` is technically safe. But to
avoid invalidating Juan's saved search across the deploy, it's cleaner to keep
`project_search_query` as the widget key and just MIRROR into
`ui:projects:search_query` if the namespace must be uniform.

`authenticator` / `authentication_status` / `username` are owned by
`streamlit_authenticator` — do not touch.

---

## 6. Color constants

### Existing palette — `streamlit_app/components/formatters.py:152-208`

```python
_STATUS_COLORS["project"] = {
    "prospect":  "#6c757d",   # gray
    "active":    "#198754",   # green
    "on_hold":   "#fd7e14",   # orange
    "completed": "#0d6efd",   # blue
    "archived":  "#adb5bd",   # light gray
}
```

Plus a `status_badge()` HTML helper at L211-225 that wraps the status string in a
`<span>` with the matching background color.

### Prompt-requested palette (session_3a_ui_uplift.md:54-56)

```python
PROJECT_STATUS_COLORS = {
    "active":    "#1FBA66",   # green (different green!)
    "prospect":  "#F7B500",   # amber (different — currently gray)
    "on_hold":   "#A85FFF",   # purple (different — currently orange)
    "completed": "#9CA3AF",   # gray (different — currently blue)
    "archived":  "#374151",   # dark gray (different — currently light gray)
}
```

### Decision needed

**Every color is different.** The page-local dicts in `1_Projects.py:59-73`
(`_STATUS_COLORS` / `_STATUS_ICONS`) are also different — they use Streamlit's
named colors (`"green"`, `"orange"`, etc.) for the existing badge.

The view-switcher-builder must choose one of:
1. **Adopt the prompt's palette globally** — update `formatters.py:_STATUS_COLORS["project"]`
   and ditch the page-local dicts. Aligns with the prompt and unifies the codebase.
   Risk: Home.py and any other consumer of `status_badge(..., entity_type="project")`
   will get the new colors. Unlikely to break anything but the dashboard chart's
   semantics shift.
2. **Add a new module** (`streamlit_app/components/status_pills.py` per prompt
   deliverable line) with ONLY the Projects palette. Leave `formatters.py` alone.
   Risk: now two palettes for projects exist in the codebase.
3. **Override per-page.** Worst of both.

**Scout recommendation:** Option 1 — adopt globally. The current
`formatters.py` palette wasn't picked for any reason that's documented; the new
palette is what the user wants. The status badge on Home.py is not called for
projects today (Home.py uses `pbs` for `bar_chart`, not `status_badge`), so the
blast radius is small.

The prompt also says: "If status colors are already defined somewhere in the
codebase ... use those. Otherwise pick the values from this prompt and put them
in a shared module." Given the existing palette doesn't match the prompt's
explicit color codes, the prompt's own override takes priority — Juan picked
those colors for a reason.

---

## 7. Test coverage relevant to this session

### Files to keep passing

- `tests/conftest.py` — fixture `db` builds a fresh DB from `db.init_db()`. No
  changes needed. Builders should use this fixture for any new service-layer tests.
- `tests/test_smoke.py` — passes today. The `test_no_duplicate_widget_keys_in_projects_page`
  test (L130-140) scans `streamlit_app/pages/1_Projects.py` source for keys of
  the form `key=f"{prefix}_{pid}"` and FAILS if any are not namespaced by
  `tab_idx`. The aggrid replacement obsoletes the per-row keys, so this test
  might end up passing trivially with zero matches — that's fine — but if any
  new per-row widgets land (e.g. for the activity tab), they MUST keep the
  `t{tab_idx}_p{pid}` pattern OR the regex needs updating.
- `tests/test_projects_search.py` — **all 6 tests live here**:
  1. `test_search_projects_returns_only_match` (CRUD layer) — unaffected
  2. `test_list_projects_returns_everything_without_filter` (CRUD layer) — unaffected
  3. `test_search_with_status_filter_on_completed_tab` (CRUD layer) — unaffected
  4. `test_apptest_default_view_shows_all_projects` (UI) — uses
     `_expander_labels(at)` → assumes expanders. **Will break with aggrid.**
  5. `test_apptest_search_filters_to_single_project` (UI) — same. **Will break.**
  6. `test_apptest_search_with_no_matches_shows_empty_state` (UI) — same. **Will break.**
  7. `test_search_input_is_inside_form_with_explicit_submit` (structural) —
     asserts the search text_input has a non-empty `form_id` AND the form has a
     `form_submit_button`. **Survives** as long as the search form wrapping
     pattern stays.

### Mitigation plan for the 3 broken tests

The integration-verifier will need to either:
- Rewrite `_expander_labels()` to look for project rows in the aggrid output
  (challenging — aggrid renders to an iframe, AppTest can't see DOM directly), OR
- Add an aggrid-agnostic structural hook: e.g. for each rendered project, ALSO
  emit a `st.markdown(f"<!-- project-row id={pid} job={job_number} -->")` HTML
  comment that AppTest CAN see via `at.markdown`, OR
- Rewrite the tests to query a session_state slot the table-view-builder
  populates with the currently-rendered project IDs (cleanest), e.g.
  `st.session_state["ui:projects:_test_visible_ids"] = [p["id"] for p in projects]`.

**Scout recommendation:** option 3. Cleanest, doesn't require fragile DOM
inspection, and the test still meaningfully asserts "after typing search foo,
the list of visible projects is filtered". The 3 UI tests should be ported to
read that slot. Document the rename in `tests/test_projects_search.py` so future
readers don't think the expander tests were silently dropped.

### Files not relevant to this session

- `tests/test_sharepoint.py` — Phase 2 work. Doesn't touch projects UI.
- `tests/test_scan_existing_project_docs.py` — documents importer. Independent.

---

## 8. Risks and unknowns

1. **`pages/1_Projects.py` does NOT bypass the service layer for any mutation.**
   Every write goes through `create_project`/`update_project`/`delete_project`/
   `create_milestone`/`update_milestone` in `modules/projects/crud.py`, OR
   through `link_calc_to_erp` in `modules.calculator.bridge`. The aggrid save
   callback can confidently use `update_project()` — there's nothing else to
   migrate. *Verified.*

2. **Every rerun re-fetches projects 6× (once per tab).** The status-filter tabs
   at L181 are all rendered every rerun; the data fetch at L197-204 runs inside
   each. The Phase B form-wrapped search adds another rerun on every Enter press.
   Aggrid will do its own rerun on every cell edit. **Cumulative cost matters
   at ~100+ projects** — recommend the view-switcher-builder fetches projects
   ONCE at the top of the page, then filters in memory per view. The existing
   pattern is unsuitable; don't preserve it.

3. **`st.rerun()` calls in the current page: 8 of them** (L157, 333, 352, 356,
   388, 410, 441, 552). They live inside form-submit and button-click handlers
   — every one fires after a service-layer write. **Interaction with aggrid:**
   `st_aggrid.AgGrid()` returns an `AgGridReturn` object whose `data` /
   `selected_rows` are computed during the rerun that the user's edit triggered.
   If the save handler calls `st.rerun()` (which is the existing pattern for
   the edit form), the grid will re-mount, and any in-flight edit gets discarded.
   **Mitigation:** the save handler for aggrid must NOT call `st.rerun()`. The
   grid will redraw naturally on the next user action; the save just commits to
   the DB and shows a toast. The other 7 rerun calls (delete, milestones, calc
   link) are fine since they live in different tabs / forms.

4. **Auth gate emits to session_state via `streamlit_authenticator`:**
   `authentication_status`, `username`, `name` (display name), plus the cached
   `authenticator` object under key `authenticator`. **None of these collide
   with `ui:projects:*`.** Verified by codebase grep.

5. **`activity_log.details` IS NOT always valid JSON.** Three writers
   (billing/timekeeping/invoicing crud) write `None` when details is empty.
   The other 8 writers always write `'{}'` or richer JSON. For the
   **per-project** activity panel only, details is always JSON in practice
   (project rows are written only by `modules/projects/crud.py` and
   `modules/crm/crud.py`), but the activity-panel-builder should still
   defensively handle NULL: `json.loads(row["details"] or "{}")`.

6. **Are there projects with NULL status?** **No.** Schema declares
   `status TEXT NOT NULL DEFAULT 'active' CHECK (status IN (...))`. SQLite
   enforces both NOT NULL and the enum. The kanban builder can safely assume
   every project has one of the 5 enum values. (Still — `_STATUS_COLORS.get(status, "#fallback")`
   is cheap insurance against schema drift.)

7. **`search_projects()` searches `name`, `address`, `job_number` ONLY.** Case-INSENSITIVE
   (SQLite LIKE is case-insensitive on ASCII by default). It does NOT search:
   `scope`, `notes`, `client_name`, `city`, `county`, `state`. The "Search by
   name, address, or job number ..." placeholder accurately reflects the
   behavior (`pages/1_Projects.py:170`). If aggrid's built-in quick-filter is
   enabled on the Table view, it will search across ALL visible columns — that
   subtly EXTENDS the search semantics beyond what `search_projects()` does.
   Probably a feature, not a bug, but worth documenting.

8. **3 AppTest tests assume expander DOM.** Already discussed in §7. **Hard
   block** for integration-verifier if not addressed mid-session by either the
   table-view-builder or the integration-verifier.

9. **DB already has the "Session 3b" columns.** Schema migration in
   `db/__init__.py:_ALTER_COLUMNS` (L38-62) already added `priority`, `action_by`,
   `next_action`, `percent_complete`, `contract_value`, `amount_paid`,
   `outstanding_balance`, `cogs`, `profit`, `lead_source`, `contact_name`,
   `contact_phone`, `service_line`, `budget_amount` to the projects table.
   **They exist as NULL columns today.** The prompt explicitly says Session 3a
   should NOT surface them in the UI ("don't add those columns NOW — Session 3b
   owns the new data model"), but the table-view-builder should know they're
   selectable from `list_projects()` rows if needed for, e.g., a Kanban card
   that wants to show `priority` as a side-bar tag. **Safest path: hide them
   entirely in 3a and let 3b uncover them.**

10. **Streamlit version is `>=1.47,<2` (requirements.txt:1).** `st_aggrid` 1.0+
    supports Streamlit ≥1.30. No compatibility blocker.

11. **`st.cache_resource` decorates `ensure_db` at `db/__init__.py:400`.** The
    DB connection is per-session, cached across reruns within a session. Aggrid
    edits won't cause connection churn. Good.

12. **The Phase B fix WRAPS the search input in `st.form`.** If the
    view-switcher-builder moves the search input INTO a per-view sidebar (e.g.
    inside aggrid's quick-filter), `tests/test_projects_search.py:test_search_input_is_inside_form_with_explicit_submit`
    will FAIL. The structural assertion expects exactly 1 `st.text_input` with
    label `"Search projects"` and `form_id != ""`. **Keep the existing
    `st.form("project_search_form")` wrapper at L165-175**; don't replace it
    with aggrid's quick-filter.

13. **`subprocess.Popen` inside the calc tab launcher (L457) is OS-conditional.**
    `CALC_EXE_PATH` defaults to a `.exe` path. On non-Windows the click silently
    works (Popen succeeds even with bad path on some systems) — but this is
    pre-existing and out of scope.

14. **Per-row widget keys MUST stay namespaced by tab_idx.** Test smoke L130-140
    will fail otherwise. Aggrid does NOT use per-row widget keys (each cell is
    its own JS-managed object), so the new pattern naturally complies. Watch
    out for any auxiliary buttons (e.g. "Open Activity" button next to a row)
    — those need the `t{view}_p{pid}` namespacing pattern.

15. **`get_calc_connection()` returns `None` if `common.db` is absent.** Already
    handled in the page (L514, L523). Aggrid replacement of the per-project
    list will only render the Calc tab inside an expanded project row, so this
    isn't disturbed.

16. **Click semantics for "expand project to see tabs" must survive view
    switches.** The prompt's `ui:projects:expanded` set is fine for Table view
    (click a row → show detail tabs below the grid, or in a modal). Kanban
    cards may need their own click behavior. Timeline bars too. The view-switcher-builder
    should standardize: every view emits a callback `open_project(pid)` that
    flips a session_state slot `ui:projects:focus` to `pid`, and the detail
    tabs always render below the active view bound to that focus. Avoids having
    4 different open-state semantics.

---

## 9. Recommendations for downstream subagents

### For dependency-installer (subagent 2)
- `streamlit-aggrid >= 1.0` is the canonical choice. Confirmed not in requirements.txt.
- `streamlit-elements` is more flexible but its drag-and-drop is fiddly under
  Streamlit's rerun model. If the kanban-builder needs DnD, evaluate
  `streamlit-sortables` first — it has a tighter API surface.
- Plotly is **NOT** in requirements.txt today. If the timeline builder picks
  Plotly Gantt over `streamlit-timeline`, plotly must be added.
- Smoke-import test should verify the package imports cleanly under Python 3.11
  (the assumed dev env) and Streamlit 1.47+.

### For view-switcher-builder (subagent 3)
- Move the project fetch to ONCE per render at the top of the page, BEFORE the
  view switcher. All 4 views consume the same list. Filter / group in memory.
- Define `ui:projects:view` with default `"Table"`. Use `st.radio` with
  `horizontal=True` and `label_visibility="collapsed"` for the switcher; bind to
  `st.session_state["ui:projects:view"]`.
- Define `ui:projects:focus: Optional[int]` early. All four views call
  `open_project(pid)` to flip it; the detail tab area below the view renders
  bound to that one pid.
- Create a shared module (per prompt deliverable line: `common/ui/status_pills.py`
  or `streamlit_app/components/status_pills.py`) with:
  - `PROJECT_STATUSES: Tuple[str, ...]` (single source of truth — pulls from schema
    enum once, not hardcoded per usage)
  - `PROJECT_STATUS_COLORS: Dict[str, str]` (prompt's palette)
  - `def render_status_pill(status: str) -> str` returning the HTML span

### For table-view-builder (subagent 4)
- Use `modules/projects/crud.py:update_project(conn, pid, **changes)` for the
  aggrid save callback. It already writes `activity_log` and commits. **Do NOT
  call `st.rerun()` in the save handler** — aggrid handles its own redraw, and
  a forced rerun discards any in-flight edit (see Risk #3).
- Wire the row-edit callback to compare new vs old row dicts to compute the
  changeset (the existing edit form does this at L308-329 — same pattern).
- DISABLE row deletion in the grid config per prompt guardrails. If a delete
  button is added separately, route through `delete_project()`.
- Status edits via the dropdown cell editor: validate against the
  `PROJECT_STATUSES` tuple before calling `update_project`. The CHECK constraint
  will raise on invalid values, but catching it in Python yields a nicer toast.
- Aggrid's quick-filter searches ALL visible columns. The existing
  `search_projects()` only searches name/address/job_number. Consider EITHER
  hiding aggrid's quick-filter and routing through `search_projects()` for
  consistency, OR enabling quick-filter as a "broader search in this view only"
  feature (document the asymmetry).

### For kanban-and-timeline-builder (subagent 5)
- Kanban columns: pull `PROJECT_STATUSES` from the shared module — DON'T
  hardcode. If `archived` projects shouldn't show on the board by default,
  expose a toggle.
- Click-to-change-status fallback: route through
  `update_project(conn, pid, status=new_status)`. The activity_log entry will
  show as `action='updated'` with `{"status": "new_value", "updated_at": ...}`
  — the activity-panel-builder needs to recognize this as a status change (see
  §3 above — there is no `status_change` action type).
- Timeline view's bar = `start_date` → `target_end_date`. Both can be NULL.
  Define a fallback (`created_at` → `target_end_date` if start_date NULL?
  Or hide the project from Timeline if start_date NULL? Surface choice to Juan).

### For activity-panel-builder (subagent 6)
- Query: `SELECT * FROM activity_log WHERE entity_type='project' AND entity_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?`
  with pagination of 25 per page.
- Defensively parse details: `details_dict = json.loads(row["details"] or "{}")`.
- Human-readable summaries for known patterns:
  - `action='created'` + `details has source='opportunity'` → "Converted from opportunity #{opportunity_id}"
  - `action='created'` (no source) → "Project created with name '{name}'"
  - `action='updated'` + `'status' in details` → "Status changed to {status}"
  - `action='updated'` (other keys) → "Updated: {comma-joined keys}"
  - `action='deleted'` → "Project deleted" (note: still queryable because the
    log row survives the CASCADE — see §2 row for `delete_project`)
- Fallback for unknown actions: render the action verb and the raw JSON in a
  `st.code(json.dumps(details_dict, indent=2), language='json')` block.
- Consider also showing milestone events (entity_type='milestone' filtered by
  `details.project_id == this_pid`) — out of scope per the prompt but very
  cheap and high-value.

### For integration-verifier (subagent 7)
- The 3 expander-DOM tests in `tests/test_projects_search.py` will break.
  Coordinate with the table-view-builder to either expose
  `st.session_state["ui:projects:_test_visible_ids"]` (preferred) OR rewrite the
  tests against whatever aggrid hook is feasible.
- Add a new test that the per-project activity panel renders without error
  against the seeded test DB (the conftest fixture `db` is sufficient).
- Smoke-screenshot each of the 4 views as listed in the prompt's verifier
  block (a-g). Save to `docs/qa/3a_smoke/` if not gitignored.
- The Phase B regression must still hold:
  `test_search_input_is_inside_form_with_explicit_submit` must pass — confirm
  the search form wrapper at L165-175 (or wherever it lives post-refactor)
  preserves `form_id` non-empty.

### For all subagents
- **Do not call `st.rerun()` from inside an aggrid callback** — it eats in-flight edits.
- **Do not change `db/schema.sql`** — Session 3b territory.
- **Do not bypass the service layer** for any project mutation.
- **Keep the per-row widget key namespace pattern** (`t{view_or_tab_idx}_p{pid}`)
  for any new auxiliary buttons — smoke test enforces it.

---

## 10. Files referenced

Read in full:
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\streamlit_app\pages\1_Projects.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\streamlit_app\Home.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\streamlit_app\auth.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\streamlit_app\components\formatters.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\modules\projects\__init__.py` (empty)
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\modules\projects\crud.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\db\schema.sql`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\db\__init__.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\config.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\tests\test_projects_search.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\tests\conftest.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\tests\test_smoke.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\requirements.txt`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\docs\prompts\session_3a_ui_uplift.md`

Read selectively (for grep / cross-reference):
- `modules\crm\crud.py` (L200-242 for opportunity→project conversion path)
- `modules\dashboard\queries.py` (L120-180 for activity_log query pattern)
- `modules\documents\crud.py` (L1-80 for list_documents signature)
- `modules\billing\crud.py`, `modules\timekeeping\crud.py`, `modules\invoicing\crud.py`,
  `modules\permits\crud.py`, `modules\bids\crud.py`, `modules\subconsultants\crud.py`,
  `modules\calculator\bridge.py`, `modules\documents\sharepoint.py`
  (all greppped for activity_log INSERT patterns)
- `scripts\importers\import_project_tracker.py` (L226-301, L478-501 for write paths)
- `docs\specs\sharepoint_session_2c.md` (L1-30 for spec layout convention)

Files NOT read (intentionally — out of scope per prompt):
- `streamlit_app\pages\2_Billing.py` ... `9_Accounting.py` (other pages)
- `modules\calculator\bridge.py` in full (out of scope; the Projects page consumes its public API)
- All audit / changelog markdown beyond what was greppped
