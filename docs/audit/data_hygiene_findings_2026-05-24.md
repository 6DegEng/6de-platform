# Data Hygiene Findings — 2026-05-24

Cross-references: `platform_ux_audit_2026-05-24.md` sections 1.5, 1.7, 1.10, 2.5, 2.6.

---

## Fix #1: NaN-safe activity log serialization

**Problem:** `json.dumps(details)` in multiple `_log_activity` helpers passes
`float('nan')` values through unchanged. The JSON spec forbids NaN but
Python's `json.dumps` silently emits the non-standard `NaN` token. Downstream,
the Home dashboard and Activity panel display `contract_value: NaN` literally.

**Root cause:** `update_project()` (and similar CRUD update functions) pass the
raw `kwargs` dict to `_log_activity`. When Streamlit `number_input` returns
`float('nan')` (e.g., user clears a numeric field), that value flows straight
into the details JSON.

**Files affected:**
- `db/__init__.py` line 241 — `log_activity()` central helper
- `modules/projects/crud.py` line 52 — `_log_activity()` local helper
- `modules/calculator/bridge.py` line 58 — `_log_activity()` local helper
- `modules/crm/crud.py` line 77
- `modules/invoicing/crud.py` line 40
- `modules/permits/crud.py` line 67
- `modules/billing/crud.py` line 35
- `modules/bids/crud.py` line 56
- `modules/documents/crud.py` line 33
- `modules/timekeeping/crud.py` line 77
- `modules/subconsultants/crud.py` line 61

**Fix:** Create `modules/activity_utils.py` with `sanitize_details(details)`
that walks the dict and replaces `float('nan')` / `float('inf')` with `None`.
Patch the central `db.log_activity()` and the most-used local `_log_activity`
in `modules/projects/crud.py`. Other modules call the central helper or their
local copies; central fix covers most paths; the project-crud local one covers
the highest-traffic code path.

**Test plan:** `tests/test_activity_nan_safe.py` — pass a dict with `NaN`,
`inf`, `-inf`, nested NaN; verify output JSON contains `null` not `NaN`.

---

## Fix #2: Human-readable activity formatter for Home dashboard

**Problem:** Home page Recent Activity section (lines 365-382) renders raw
`entity_type`, `action`, and `details` JSON. Users see entries like:
`Updated Project #11 -- {"contract_value": NaN, "updated_at": "..."}`.

**Files affected:**
- `streamlit_app/Home.py` lines 365-382 — Recent Activity renderer
- `modules/projects/activity.py` — existing `summarize_activity()` for project-
  scoped views (Activity tab)

**Fix:** Create `modules/activity_formatter.py` with `format_activity(row) -> str`
that handles all entity types (project, invoice, permit, calc_link, opportunity,
milestone, bid, client, etc.) and produces human-readable one-liners like:
"Project #11: contract value updated (May 23, 3:40 PM)".
Replace the raw rendering in Home.py with calls to this formatter.

**Test plan:** Unit tests in `tests/test_activity_nan_safe.py` (same file) for
the formatter covering each entity type.

---

## Fix #3: Calc-engine fixture filter

**Problem:** `read_calc_projects()` returns all rows from the calc engine's
`projects` table, including test/fixture entries like "S26 LIVE smoke". These
appear in the Calculator dropdown and Browse view, confusing users.

**Files affected:**
- `modules/calculator/bridge.py` line 62 — `read_calc_projects()`
- `streamlit_app/pages/8_Calculator.py` lines 66, 102 — two call sites
- `streamlit_app/pages/1_Projects.py` line 584 — one call site

**Fix:** Add `hide_fixtures: bool = True` param to `read_calc_projects()`.
When True, append WHERE clauses filtering out project names matching common
fixture patterns (`S26%`, `%smoke%`, `%fixture%`, `%test%` — case-insensitive).
All three call sites pass the default. Add a "Show test/fixture data" toggle
on the Calculator page that sets `hide_fixtures=False`.

**Test plan:** Manual verification via curl against running app; ensure
dropdown no longer shows fixture entries by default.

---

## Fix #4: CRM "No client" literal + "Other" type default

**Problem:** CRM Pipeline tab renders `"No client"` as a literal label when
`client_name` is NULL. The string "No client" appears in the opportunity header
expander, misleading users into thinking it's an actual client name.

Additionally, the service_line dropdown defaults to index 0 ("structural")
when the opportunity has no service_line set — this is not a data problem but
the "Other" type display concern is that newly created opportunities default
to "other" service_line without explicit user selection.

**Files affected:**
- `streamlit_app/pages/4_CRM.py` line 334 — `client_label = opp["client_name"] or "No client"`

**Fix:** Replace `"No client"` with an em-dash (`"—"`) for display.
When `client_name` is None, show the dash character consistently with the
rest of the platform's empty-field pattern.

**Test plan:** Manual verification on CRM page; verify NULL clients render
as dash, not "No client".
