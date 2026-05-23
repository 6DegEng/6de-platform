# Session 3a — Projects Page UI Uplift (Monday-style)

**Goal:** Make the Projects page feel like a Monday board. View switcher, color-coded status, inline editing, per-project activity panel, persistent state. Pilot module — if this lands well, the same pattern gets applied to CRM, Bids, Permits in later sessions.

**Branch:** create `feature/projects-ui-uplift` off `main` (or off whatever's current). Do NOT continue on `feature/sharepoint-phase-2` — SharePoint work should land first.

**Pre-conditions:**
- SharePoint Phase 2 has merged or is in a state you don't mind diverging from.
- Streamlit platform boots without errors.
- `pages/1_Projects.py` exists and renders the current project list.

**Estimated time:** 4–6 hours autonomous.

---

## Copy-paste prompt for Claude Code

```
Session 3a — Projects page UI uplift, Monday-style. Pilot module for a pattern
we'll later apply to CRM/Bids/Permits.

CONTEXT
- The Projects page (pages/1_Projects.py) currently renders project list as
  vertically stacked expanders. Each expanded project shows tabs: Details, Edit,
  Milestones, Calculations, Documents.
- Status field on projects: active / prospect / on_hold / completed / archived.
- A real `activity_log` table is already populated by other modules — it logs
  events with type, entity_type, entity_id, payload (JSON), created_at.
- The legacy xlsx that birthed this platform (
  06_Engineering/01_ Active Projects/Project_Tracker_2026.xlsx, sheet "Projects")
  used 22 columns including Priority (⏸ On Hold, etc.), Action By, Next Action,
  % Complete, Age (Days), Contact, Contract Value, Outstanding Balance.
  Don't add those columns NOW — Session 3b owns the new data model. Just keep
  the eventual shape in mind so this UI doesn't have to be re-architected when
  those fields appear.

GOAL
Six concrete changes to pages/1_Projects.py:

1. View switcher at top: Table · Kanban · Timeline · Calendar
   - Table = streamlit-aggrid grid, inline editable for safe fields
     (name, address, scope, notes), filterable, sortable, groupable by status
   - Kanban = columns by status (active / prospect / on_hold / completed),
     project cards drag-and-droppable between columns if streamlit-kanban-board
     or streamlit-elements supports it; otherwise click-to-change-status as
     fallback. If drag-and-drop is rough, ship click-to-change and file a TODO.
   - Timeline = horizontal bar per project from Date Opened → Target Close,
     grouped by status. Use streamlit-timeline OR a custom Plotly Gantt.
   - Calendar = month grid showing project milestones (target close, start).
     Use streamlit-calendar OR custom HTML. If neither is clean, ship a simple
     date-sorted list with a "Calendar (preview)" label.

2. Color-coded status pills
   - Replace the text status with a colored pill. Use HTML in st.markdown:
     active=#1FBA66 green, prospect=#F7B500 amber, on_hold=#A85FFF purple,
     completed=#9CA3AF gray, archived=#374151 dark. Apply in every view.

3. Inline editing via streamlit-aggrid (Table view only)
   - Safe-to-edit columns: name, address, scope, notes, status, priority.
   - On row save, write through to the projects table via the existing
     persistence layer (NOT raw SQL). All saves emit an activity_log row.
   - Validate status against the enum; reject invalid values with toast.

4. Per-project activity panel
   - When a project expander opens, add a 6th tab: "Activity" (after Documents).
   - Renders activity_log rows where entity_type='project' AND entity_id=this_id,
     newest first, paginated 25 per page.
   - Each row: timestamp + event type + human-readable summary (parse payload
     for known event types: project_created, status_changed, document_indexed,
     etc.). Unknown event types fall back to raw payload JSON in a code block.

5. Persistent UI state
   - Use st.session_state to remember:
       * selected view (Table/Kanban/Timeline/Calendar) across reruns
       * which projects are expanded (set of project IDs)
       * search box value (so Phase B fix isn't undone)
       * Active tab filter selection
   - Keys must be namespaced: ui:projects:view, ui:projects:expanded, etc.
   - Surviving full browser reload requires localStorage shim — DO NOT add that
     now. session_state across rerun is enough for this session.

6. Real search filter
   - Phase B should have fixed it already. Verify the fix held. If the search
     box still doesn't filter, fix it again — same regression test approach.

ORCHESTRATION — seven subagents, sequential pipeline.

1. scout
   Read pages/1_Projects.py, common/db.py (or wherever persistence lives),
   modules/projects/* (services, models). Read existing st.session_state usage.
   Read tests/ for project-related tests. Output: docs/specs/3a_scout.md with
   a current-state diagram + a list of risks (what could break, what's coupled).
   No code changes.

2. dependency-installer
   Add to requirements.txt and `pip install`:
     - streamlit-aggrid >= 1.0
     - streamlit-elements >= 0.1
     - streamlit-kanban-board OR streamlit-sortables (whichever has better
       drag-and-drop; spec-writer chose; document the choice in the spec)
     - streamlit-calendar OR plotly (already a dep? check first)
   Verify install with a 5-line smoke import script. Commit as
   `chore(deps): add UI uplift dependencies`.

3. view-switcher-builder
   Implement the 4-view switcher AND the persistent st.session_state for view
   choice. Each view starts as a minimal stub: Table shows the existing list,
   the other three show "Coming up next" placeholders. This lands the wiring
   first so later builders can swap stubs for real implementations.
   Commit: `feat(projects): four-view switcher scaffold`.

4. table-view-builder
   Replace the existing project list rendering with streamlit-aggrid. Inline
   editing on safe columns, status pills as cell renderers, grouping by status
   (collapsible groups), filter row, sort by column header. Wire row-save to
   the existing project update service — DO NOT bypass the service layer.
   Commit: `feat(projects): aggrid table view with inline editing`.

5. kanban-and-timeline-builder
   Implement Kanban view (status columns, cards, drag-and-drop or click-to-change
   fallback) and Timeline view (Gantt-style per-project bars from Date Opened
   to Target Close). Calendar view is allowed to be a preview/placeholder if
   time is short — surface that in the commit message.
   Two commits: `feat(projects): kanban view` and `feat(projects): timeline view`.

6. activity-panel-builder
   Add the "Activity" tab as the 6th tab on the project detail view. Query
   activity_log where entity_type='project' AND entity_id=this_id, paginate,
   render with human-readable summaries for known event types. Falls back to
   raw payload for unknown types.
   Commit: `feat(projects): per-project activity panel`.

7. integration-verifier
   Run `pytest -xvs`. Boot the platform via launcher.py. Smoke test:
     a. Open Projects page, confirm view switcher shows 4 options
     b. Switch to Kanban — confirm columns render with correct status colors
     c. Switch to Timeline — confirm bars render
     d. Back to Table — edit a project's name inline, confirm save, confirm
        activity_log row was written
     e. Expand any project, click Activity tab, confirm log entries render
     f. Type a job number in the search — confirm list filters (Phase B fix held)
     g. Switch views, refresh page, confirm session_state survives the rerun
   Take screenshots of each view and save to docs/qa/3a_smoke/*.png.
   Write docs/qa/session_3a_verification.md with results + any deferred TODOs.
   Do NOT commit screenshots if the docs/qa folder is gitignored — check first.

GUARDRAILS
- One feature = one commit. No squashing the whole session into a single fat
  commit.
- Do not change the database schema. This is purely a UI session. Adding
  Priority/% Complete/etc. is Session 3b.
- Do not touch the SharePoint module or .env handling — that work just shipped.
- streamlit-aggrid CAN do dangerous things (delete rows, mass edit). Disable
  row deletion in the grid config. Mass paste OK but every modified row still
  flows through the service layer.
- If a third-party component has a bug that costs >30 minutes to work around,
  STOP and ship the affected view as a preview placeholder. Don't burn time
  fighting a brittle library.
- Color palette must be consistent. If status colors are already defined
  somewhere in the codebase (config.py, a constants module, CSS), use those.
  Otherwise pick the values from this prompt and put them in a shared module.
- Test coverage for the service-layer wiring (any new persistence calls must
  have unit tests). UI rendering doesn't need tests.

CHECKPOINTS (interactive, per Q14 phase-gate)
- After subagent 1 (scout): surface the current-state diagram and risks. Wait
  for Juan to acknowledge before any code is written.
- After subagent 2 (deps): if any chosen dependency is unmaintained (last commit
  > 18 months) or has known security advisories, STOP and surface the alternatives.
- After subagent 4 (table view): demo the new Table view before continuing.
  Juan validates it feels right before more views land.
- After subagent 7 (verifier): final demo + handoff doc.

STOPPING POINT
After integration-verifier reports green AND the smoke checklist is complete.
Do NOT roll into Session 3b. Notes/Contacts/Updates are a separate workstream.
Surface the deferred TODOs (calendar polish, drag-and-drop if it didn't land,
mobile responsiveness) at the bottom of the verification doc — Juan decides
whether to file as follow-up tickets.

DELIVERABLES
- pages/1_Projects.py with four-view switcher
- requirements.txt updated
- New helper module (likely common/ui/status_pills.py) for the pill renderer
- docs/specs/3a_scout.md, docs/qa/session_3a_verification.md
- Screenshots if the docs/qa folder is gittracked appropriately
- A "what's deferred" section in the verification doc

Begin with subagent 1 (scout).
```

---

## Notes for Juan

- **Why the dependency-installer is a separate phase:** if one of the picked libraries is dead or buggy, you want to know BEFORE the view-switcher-builder commits to it. The scout-then-install-then-build sequence catches that early.
- **Kanban drag-and-drop is the wildcard.** Streamlit's rerun model fights real drag-and-drop. If it lands clean, great. If it doesn't, the click-to-change-status fallback is fine and ships the same outcome (project moves to new column). The fallback is not a regression — it's a perfectly valid interaction pattern.
- **Calendar is allowed to be a preview.** If `streamlit-calendar` is clean, use it. If not, ship a placeholder. Calendar is the least valuable of the four views for a 1-person consultancy where you mostly care about "what's hot right now" (Kanban) and "where's the timeline pressure" (Timeline).
- **Activity panel is the sneaky high-value piece.** You already write to `activity_log` everywhere. Surfacing that per-project is roughly free and transforms the platform from "static data" to "remembered history". Don't let this get cut for time.
- **No database changes here.** Resist the urge to add Priority or % Complete in this session — those are Session 3b's territory. Mixing concerns will balloon the session and ship neither thing well.
