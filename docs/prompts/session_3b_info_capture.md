# Session 3b — Project Information Capture

> **Refresh log**
>
> - **2026-05-23 (Juan, Home Desktop):** Session 3a (Projects UI uplift) merged to `main` as v3.4 (`bcc46b8`). Repo cleanup ran the same day — closed-session notes, scout reports, and stale launchers moved into `archive/` and `docs/archive/`. A Chrome smoke test on the live build identified five cosmetic / configuration issues — see [Known issues to fold in](#known-issues-to-fold-in) below. The 3b prompt body itself is unchanged from the original draft; only this preamble is new.

---

## Office-PC kickoff checklist

When you sit down at the office machine to start this session, run through this once:

1. `git fetch && git pull` on the Company Platform repo so the office checkout has v3.4 + the 2026-05-23 cleanup commit. The repo path on the office PC should mirror the home-desktop layout: `02_Information Technology/07_Company_Platform`.
2. Confirm the working tree is clean: `git status` should be empty, `git log --oneline -3` should show the cleanup commit on top of the v3.4 release tag.
3. Boot the platform once to verify the office PC has matching deps: double-click `Launch_6DE_Platform.bat` → wait for browser → confirm Dashboard loads and shows "ERP Platform v3.4" in the sidebar. If imports fail, `pip install -r requirements.txt` (the v3.4 deps closed out `streamlit-elements`, so a stale env may need cleanup — `pip uninstall streamlit-elements -y` is safe).
4. Open `docs/qa/session_3a_chrome_smoke.md` and skim the five known issues. They're all queued for **subagent 6 (ui-polish)** below — not a separate work item.
5. Open `06_Engineering/01_ Active Projects/Project_Tracker_2026.xlsx` once before you fire off the prompt — eyeball the Projects sheet header row (row 3) and any row with Priority/Action By/Next Action populated, so you have a real-world reference for the spec-writer's output to compare against.
6. Create the branch yourself, then paste the prompt: `git checkout -b feature/project-info-capture`.

That's the entire ritual. If any of those steps surprise you, **stop and resync** before running the autonomous prompt — Session 3b creates schema migrations, and you don't want them landing on a stale branch.

---

## Known issues to fold in

Five issues caught during the 2026-05-23 Chrome smoke test on v3.4 (see `docs/qa/session_3a_chrome_smoke.md` for full reproductions). All map to **subagent 6 (ui-polish)** — expand its scope to cover these alongside the new field columns:

1. **Table view — `<span>` HTML escaped into the Status column.** The status pill renderer is outputting raw `<sp...` text. Fix the cell renderer to allow HTML (or switch to a JsCode renderer that builds the pill DOM directly).
2. **Table view — column headers truncated** (`J..`, `S..`, `T..`). Set explicit `min_width` per column or use `autoSizeStrategy: fitGridWidth` with weights.
3. **Table view — AG Grid `#200` console errors** for `sideBar`, `rowGroupPanelShow`, `enableRowGroup`. Either strip the enterprise-only options from gridOptions or accept the warnings if there's a plan to upgrade. (Recommend strip — community AG Grid is fine for what we need.)
4. **Timeline view — Y-axis project labels truncated to 1-2 chars.** Widen the y-axis label area; consider `<job#> — <short_name>` format to keep labels compact.
5. **Home — Vega-Lite "Infinite extent" warnings** on empty charts. Short-circuit to "(no data)" placeholder when the source df is empty.

None of these block Session 3b functionally — they're cosmetic. But they're the kind of thing that's cheap to fix while subagent 6 is already in that file, and they make the 3a work feel finished.

---

**Goal:** Turn the Projects page from "list of records" into a project knowledge base. Capture the rich data the legacy `Project_Tracker_2026.xlsx` had (Priority, Action By, Next Action, % Complete, Contact, financials, Notes) — plus a real per-project Notes/Updates/Contacts story. Make the Projects detail view a single place to find everything about a project.

**Branch:** create `feature/project-info-capture` off the post-3a state.

**Pre-conditions:**
- Session 3a is merged (you need the activity panel + aggrid table to surface this new data).
- SharePoint Phase 2 is merged.
- Platform boots clean.

**Estimated time:** 8–12 hours autonomous.

---

## Copy-paste prompt for Claude Code

```
Session 3b — Project information capture. Add Priority, Action By, Next Action,
% Complete to the projects table. Build a per-project Notes/Updates/Contacts
data model. Optional legacy xlsx importer for backfill.

CONTEXT
- The legacy tracker at 06_Engineering/01_ Active Projects/Project_Tracker_2026.xlsx,
  sheet "Projects", rows 4+ (headers in row 3) has 22 columns. Read it before
  designing schema. Key columns to mirror:
    Project No, Project Status, Priority, Action By, Next Action, Date Opened,
    Target Close, % Complete, Age (Days), Contact, Company / Client, Scope,
    Contract Value ($), Amount Paid ($), Outstanding Balance ($), COGS, Profit,
    Notes.
  Of these, projects table already has: project number (job_number), status,
  name (≈Project Description), client, scope, dates. MISSING: Priority,
  Action By, Next Action, % Complete, Age (derivable), the financial summary,
  Notes (currently only a free-text field — needs structured note model below),
  Contact (currently no separate table).
- The CRM sheet (12 rows in the legacy xlsx) defines a contacts shape: Client ID,
  First Name, Last Name, Company, Email, Phone, Service Type, Account Value,
  Latest Project No., Notes. Use as a reference but don't blindly copy —
  multi-contact-per-project is the right model, not single-contact-per-project.
- Session 3a added an Activity tab that reads from activity_log. That table
  records SYSTEM events (created, status changed, document indexed). This
  session adds USER-authored content (notes, updates, comments) as separate
  tables. Don't conflate the two.

GOAL
Three new data surfaces in the projects domain:

A. project_notes — long-form per-project notes
   Schema: id, project_id, content (markdown), created_at, updated_at,
   author (default 'Juan' until Phase 5 multi-user).
   Multiple notes per project allowed. Render newest-first.
   Use case: ongoing thoughts, design decisions, weird gotchas. Not for
   ephemeral status updates — those go to project_updates below.

B. project_contacts — people involved in a project
   Schema: id, project_id, name, role (enum: client / contractor / architect /
   inspector / AHJ / subcontractor / other), email, phone, company, notes,
   created_at.
   Multiple contacts per project. Filter and sort in UI by role.
   The "Contact" column from legacy xlsx maps to the primary client contact
   row (role='client').

C. project_updates — timestamped status updates / permitting comments
   Schema: id, project_id, content (markdown), category (enum: status /
   permitting / client_communication / internal_note / billing), created_at,
   author. Newest-first feed.
   Use case: "Spoke with FDOT today, they want revisions on sheet C-3";
   "Invoice 260326-2 sent"; "Permit returned with comments — see notes".
   This is the chatter pane equivalent.

Plus four new fields on the projects table itself:
   - priority (enum: low / normal / high / urgent, default 'normal')
   - action_by (text, default null — name of person responsible for next action)
   - next_action (text, default null — short description of what's next)
   - percent_complete (int 0-100, default 0)

ORCHESTRATION — seven subagents, sequential.

1. spec-writer
   Read the legacy xlsx (sheet="Projects", header row 3). Sample 5 real rows.
   Read the existing projects table schema and the existing notes field's
   current usage (grep for project.notes references). Decide:
     - Do we keep the old `notes` field as a "summary" and add `project_notes`
       as the long-form table, or migrate old notes into project_notes?
     - Default decision: keep `notes` as a 1-line summary field, add
       project_notes for long-form. Migration is optional.
     - Status enum values: confirm we match the legacy xlsx values (Active /
       Prospect / On Hold / AHJ/Permitting / Completed / Cancelled / Archived).
       The current code may use a subset.
   Write docs/specs/3b_data_model.md with: full schema diffs, migration plan,
   open questions. STOP and surface for Juan to acknowledge before any DDL.

2. schema-builder
   Implement migrations for project_notes, project_contacts, project_updates
   + the four new project columns. Reuse the existing _ALTER_COLUMNS pattern
   from db/__init__.py (the same pattern SharePoint Phase 2 used). Add ORM
   models + service-layer CRUD. Unit tests covering: insert/update/delete,
   foreign-key cascade behavior, validation (priority must be in enum,
   percent_complete clamped 0-100).
   Commit: `feat(db): add project_notes, project_contacts, project_updates +
   priority/action_by/next_action/percent_complete on projects`.

3. service-builder
   Business logic:
     - Status transition validation (e.g., can't go from Archived → Active
       without unarchive flag). Define allowed transitions in a constant.
     - On every status change, emit an activity_log row.
     - On every project_updates insert, also emit an activity_log row
       summarizing it (so the Activity tab from 3a surfaces both system
       events AND user updates in one feed).
     - Age (Days) computed property: today - date_opened. Surface in UI but
       don't persist (derive on read).
   Unit tests for all transitions and computed properties.
   Commit: `feat(projects): status workflow, age derivation, user-update logging`.

4. ui-builder
   Update pages/1_Projects.py — add to each project's detail panel:
     - Existing Details tab now shows Priority pill, Action By, Next Action,
       % Complete bar in a top metadata row
     - New "Notes" tab: list of project_notes (markdown rendered), with
       "Add note" form at the top
     - New "Contacts" tab: filterable list, "Add contact" form, role pills
     - New "Updates" tab: chronological feed of project_updates, "Add update"
       form with category dropdown, filterable by category
   Tab order: Details · Notes · Contacts · Updates · Activity · Milestones ·
   Calculations · Documents · Edit. (Activity comes from 3a; new tabs slot in
   before it.)
   Forms must use the service layer, not raw SQL. Saves must emit activity_log
   events where appropriate.
   Commit: `feat(projects): notes/contacts/updates tabs in detail view`.

5. legacy-importer (OPTIONAL, dry-run by default)
   Build scripts/import_legacy_project_tracker.py:
     - Reads the legacy xlsx Projects sheet
     - For each row, finds the matching projects row by job_number
     - Proposes updates: fill missing priority/action_by/next_action/
       percent_complete from xlsx; create project_contacts row from the
       Contact column; preserve legacy Notes as a single project_updates
       entry with category='internal_note'
     - --dry-run prints proposed changes, makes no writes (default)
     - --commit applies them
     - --since YYYY-MM-DD only processes projects opened after that date
     - Idempotent: re-running --commit should produce no changes if already
       imported (use a flag in project_notes content like "imported from
       Project_Tracker_2026.xlsx on YYYY-MM-DD" to detect)
   Do NOT run --commit autonomously. Run --dry-run, surface output to Juan,
   stop. Juan decides whether to commit the import.
   Commit (with --dry-run only run): `feat(import): legacy xlsx tracker
   importer (dry-run validated)`.

6. ui-polish
   The aggrid table from Session 3a should now show priority pill, action_by,
   next_action, % complete bar as columns. Add filtering by priority. Add
   sort-by-age-descending. Add a "% complete" bar renderer using HTML in
   the cell.

   ALSO fold in the five 2026-05-23 Chrome smoke findings
   (docs/qa/session_3a_chrome_smoke.md):
     a. Fix the Table view status column — `<span>` HTML is being escaped
        instead of rendered. The same cellRenderer mechanism you'll use for
        the new priority pill should fix both at once.
     b. Set sensible min_width per column so headers don't truncate to "J.."
        / "S.." / "T..".
     c. Strip the enterprise-only gridOptions (sideBar, rowGroupPanelShow,
        enableRowGroup) that throw AG Grid #200 errors on the console —
        we don't have the enterprise build and don't plan to.
     d. Widen the Timeline view's y-axis label area so project names aren't
        clipped to 1-2 characters. Use a "<job#> — <name>" label format.
     e. Add empty-data guards on the Home dashboard charts so Vega-Lite
        doesn't log "Infinite extent" warnings when a series is empty.
   These are cosmetic, not blockers — but they're cheap to fix while you're
   already touching the renderer code.

   Commit: `feat(projects): expose new fields in aggrid table view + 3a polish`.

7. integration-verifier
   Full pytest suite. Boot platform. Smoke checklist:
     a. Open a project, add a note → verify it appears, activity_log row written
     b. Add a contact (role=architect) → verify it appears, role pill shown
     c. Add an update with category=permitting → verify it appears in Updates
        AND in the Activity feed (from 3a)
     d. Change a project status → verify status_changed activity_log row
     e. Set priority=urgent → verify pill in aggrid Table view
     f. Set percent_complete=50 → verify bar in aggrid
     g. Run scripts/import_legacy_project_tracker.py --dry-run → review output
        with Juan, don't commit
     h. Re-run the 2026-05-23 Chrome smoke checklist
        (docs/qa/session_3a_chrome_smoke.md) and confirm the five findings
        are resolved.
   Write docs/qa/session_3b_verification.md.

GUARDRAILS
- Status enum changes are migrations. If the spec-writer adds new status values
  (AHJ/Permitting, Cancelled), backfill is allowed but must preserve existing
  data. No silent value renaming.
- Do not delete the existing project.notes field. Keep it as a summary field.
- All UI writes go through the service layer. No raw SQL in pages/.
- The legacy importer must be idempotent and dry-run by default. NEVER run
  with --commit autonomously. Juan owns that decision.
- New tabs must not break the existing Documents tab from SharePoint Phase 2.
- If the legacy xlsx has rows whose job_number doesn't match any project,
  surface them as orphans in the importer output — don't auto-create.
- One feature = one commit. No squashing.

CHECKPOINTS
- After subagent 1 (spec-writer): surface data model + open questions. Wait
  for Juan before any DDL.
- After subagent 2 (schema-builder): migrations applied to a backup db,
  confirm rollback works, then proceed.
- After subagent 4 (ui-builder): demo new tabs with one note/contact/update
  per tab before continuing.
- After subagent 5 (legacy-importer dry-run): surface the dry-run output
  to Juan. Stop. Juan decides commit-or-not.
- After subagent 7 (verifier): final demo + handoff doc.

STOPPING POINT
After integration-verifier reports green. Do NOT roll into Session 3c
(SharePoint mirror). The mirror reads from this session's tables — it needs
this session's schema to exist, but the mirror logic itself is its own
session.

DELIVERABLES
- Three new tables in the schema
- Four new columns on projects
- Three new tabs in the project detail view
- scripts/import_legacy_project_tracker.py (dry-run validated only)
- docs/specs/3b_data_model.md, docs/qa/session_3b_verification.md
- Status workflow constants in a shared module
- The five 2026-05-23 Chrome smoke findings resolved (subagent 6)

Begin with subagent 1 (spec-writer). Read the legacy xlsx FIRST before
proposing schema — its column shape is the design input.
```

---

## Notes for Juan

- **The legacy xlsx is the design spec, not the source of truth.** Claude Code should read it to understand what fields you actually care about, but the new platform schema can deviate (e.g., multi-contact-per-project instead of single Contact column).
- **The importer is the riskiest piece.** That's why it's dry-run-only and explicitly gated on your approval. If something goes sideways, no DB writes happened. You can rerun the dry-run 100 times safely.
- **`project_updates` vs `activity_log` is a real distinction.** activity_log is system-generated (project_created, status_changed, document_indexed). project_updates is human-authored (the "I spoke with FDOT today" entries). The Activity tab from Session 3a unifies them in a feed, but the underlying tables are separate so the data stays clean.
- **Status enum expansion is a one-way door.** Once you add AHJ/Permitting as a valid status, you'll have rows with that value. Make sure the enum list in the spec doc is what you want before the migration runs.
- **Tabs are starting to multiply.** After 3b, the project detail view has 9 tabs (Details · Notes · Contacts · Updates · Activity · Milestones · Calculations · Documents · Edit). That's the upper bound of usable horizontal tabs. If you ever want more, switch to a sidebar nav or merge tabs.
- **The cleanup commit on 2026-05-23 archived a lot of closed-session noise.** If you need any of it, look under `archive/` (root scratch + old session notes) or `docs/archive/` (closed prompts, scouts, and verifications). Nothing was deleted from git history — `git log -- <old-path>` still finds prior commits.
