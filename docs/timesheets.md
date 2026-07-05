# Timesheets — Excel-system parity

The firm's timekeeping source of truth used to be one hand-filled Excel
workbook per employee per week
(`03_Human Resources\NN_<Employee>\02_Timesheets\Timesheet_<Monday>_to_<Sunday>.xlsx`).
This feature makes the platform a drop-in replacement without breaking
anything downstream.

## What parity means

- **Internal (non-billable) time** is first-class: the `internal_codes`
  table carries the firm's 18 internal codes (001001 Admin/Accounting …
  004003 Technology/Website). A time entry books **either** a project
  (`project_id`, billable) **or** an internal code (`internal_code`,
  never billable) — a database CHECK enforces exactly one.
- **Rates** stay snapshot-per-entry at the standard rate; OT is the
  1.5x `multiplier`, exactly like the Excel "OT?" flag.
- **Capacity** comes from `resource_calendars` (default 40 h/week per
  employee) and shows up in the utilization report so utilization can be
  read against available hours, like the Excel Time_Analysis sheet did.

## What the export guarantees (Master_Time_Log compatibility)

`modules/timekeeping/export_xlsx.py` (the Weekly tab's "Download
Timesheet.xlsx" button) produces a workbook that the downstream
Master_Time_Log builder can consume unchanged:

- Sheet **Time_Log** keeps the exact legacy layout: title rows 1–2,
  headers on **row 5** (`Date | Project # | Client / Project Name |
  Task Description | Role | OT? | Hours | Rate ($/hr) | Line Total ($) |
  Mileage`), entries from **row 6**.
- All cells are **literal values, no formulas**. `Date` is a real date
  cell; `Project #` is the job number or internal code; `Role` is the
  display label ("Professional Engineer", not the enum); `OT?` is
  `Y`/`N`; `Rate ($/hr)` is the effective rate (std rate x multiplier,
  e.g. 472.50 for Principal OT); `Line Total ($)` = hours x rate x
  multiplier. The builder's row rule — keep rows having both Date and
  Hours — holds.
- Sheets **Fee_Rates** (display labels + std/OT rates from
  `fee_schedule`), **Internal_Codes** (from the table) and
  **Weekly_Summary** (B2 = Monday date, hours + revenue by role) are
  included for human readers.
- Filename: `Timesheet_<Monday>_to_<Sunday>.xlsx` (ISO dates).

`Mileage` is exported empty — the platform tracks mileage as an expense,
not per time-entry.

## Import procedure (legacy files -> platform)

```
# preview (writes nothing — DRY-RUN is the default):
python scripts/import_timesheets_xlsx.py --hr-dir "<...>\03_Human Resources"

# persist:
python scripts/import_timesheets_xlsx.py --hr-dir "<...>" --commit
```

- Scans `*/02_Timesheets/Timesheet_<date>_to_<date>.xlsx` (template and
  oddly named files are ignored and listed).
- Employee = folder name minus the `NN_` prefix, matched against
  `employees.name` (tolerant of middle initials: "Juan Castillo" matches
  "Juan C. Castillo"). Unknown employees are reported as failures, never
  auto-created.
- Project # -> `projects.job_number`, else `internal_codes.code`;
  unknown values fail validation row-by-row with a reason.
- Role display label -> enum; `OT? = Y` -> multiplier 1.5; the stored
  rate is the file's Rate column divided by the multiplier, so
  rate x multiplier reproduces the file exactly.
- **Idempotent**: a row is skipped when an identical entry already
  exists (employee, date, project/internal code, hours, description) —
  re-running the importer creates nothing new.
- The summary compares the files' Line Total sum against the computed
  sum so any drift is visible immediately.

## Intentionally NOT reproduced

- **Time_Analysis** and **Management_Quadrant** sheets — these are
  in-workbook Excel conveniences (charts of the same data, an Eisenhower
  matrix scratchpad), not data. The platform's Weekly view and
  utilization report replace Time_Analysis; the quadrant sheet has no
  platform equivalent by design.
- Formulas in general: the export is literal values only, which is what
  the Master_Time_Log builder reads anyway.
