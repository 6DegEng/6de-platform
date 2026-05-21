# 260205 — 4655 SW 74th Ave: Investigation

**Date:** 2026-05-21
**Phase:** A (read-only investigation per Session 2b bug-fix sprint plan)
**Verdict:** **(a) Project exists, search bug masked it**

---

## What was reported

Juan tested the shipped Documents tab and reported:
> "Project 260205 — 4655 SW 74th Ave does not appear in the Projects list at
> all under any status tab."

Suspicion: project may have been orphaned during import, job number wrong, or
the project never created.

## Evidence (all read-only)

### Database state

```
id=22  job=260205  status=completed  name='4655 SW 74th Ave'  address='4655 SW 74th Ave'  client_name='Alfred Gomez'
```

Direct query against `projects` table confirms the row exists, is healthy,
and is linked to client `Alfred Gomez`.

### list_projects() returns it correctly

Direct call to `modules.projects.crud.list_projects(conn, "completed")`
returns 20 completed projects including 260205 (position 6 in the
`ORDER BY job_number DESC` ordering).

Direct call to `list_projects(conn)` (no filter) returns all 118 projects;
`[r for r in rows if r["job_number"] == "260205"]` returns the row.

**The data layer is healthy.** Nothing about 260205 is masked by the
LEFT JOIN on `clients` or by the status filter.

### OneDrive folder state

The folder `06_Engineering\01_ Active Projects\260205 - 4655 SW 74th Ave\`
exists. (`Test-Path` returns `True`.) Initial wildcard query came back empty
due to a PowerShell output-rendering quirk; a direct literal path test and a
broader `^26` regex listing both confirmed presence.

### Backfilled documents

The scanner indexed 471 documents for project 22 (= 260205):
- **Drawings:** 467
- **Billing:** 4 (PP Proposal + Proposal files in `Accounting/` subfolder)

Sample paths confirm the leading-space convention is preserved:
```
06_Engineering/01_ Active Projects/260205 - 4655 SW 74th Ave/Accounting/PP Proposal - 4655 SW 74th Ave.pdf
06_Engineering/01_ Active Projects/260205 - 4655 SW 74th Ave/Site Photos/20260209_095528(0).jpg
```

Scanner never logged 260205 as skipped or unclassified — it processed
successfully.

## Why Juan didn't see it

Verdict **(a)**: project exists. The reported absence is best explained by
**Phase B's search filter bug** rather than a data issue:

- 260205 is `status='completed'`, so it appears only under the **All** and
  **Completed** tabs — not under Active, Prospect, On Hold, or Archived.
  Four of the six tabs are correctly excluding it.
- If Juan typed `260205` into the broken search box at the top of `/Projects`,
  the search bug (per his report: "submit fires but the project list is NOT
  filtered — all projects remain visible") makes the projects render *as if
  no search was applied*. On the All tab that means 118 projects; on the
  Completed tab, 20 projects. Easy to miss one row by eye.
- Once Phase B fixes the search and `260205` actually filters the list to
  the single matching row, 260205 will be visible.

## Side observations (not action items for this sprint)

1. **Stale folder placement.** 260205 is `completed` in the DB but its folder
   still lives in `01_ Active Projects/`. Other completed projects with active
   folders include: 231101 (Hillsboro LT Pool), 250820 (1665 Isles Cir),
   250923 (9720 E Hibiscus St), 260127 (Alphaville Villas), 260128 (6450 SW
   82nd St), 260129 (5201 SW 76th Ave), 260204 (511 Upland Rd), 260225 (8295
   NW 93rd St), 260312 (124 NE 26th Dr), 260326 (1041 NW 16th St), 260420
   (2003 N. Miami Ave), 260434 (900 NW 178th Terrace). Convention question
   for Juan: should completed projects' OneDrive folders be moved to a
   `02_Completed Projects/` (or similar) location at completion time?
   Independent of Phase B/C; not blocking.

2. **Three projects on disk, missing from DB** (per backfill scanner):
   - `260304 - Buena Vista`
   - `260409 - 1390 S Ocean Blvd`
   - `260413 - 3107 PGA Blvd`

   These have OneDrive folders but no row in `projects`. Likely active jobs
   started after the last importer run. Backfill skipped them correctly
   (can't link a document to a nonexistent project). Worth a one-shot import
   to capture them; track as a follow-up.

## Action

- **Phase B proceeds as planned.** When the search filter is fixed and tested,
  re-verify that `260205` in the search box narrows the project list to one row.
- **No DB write or folder move needed in Phase A.**

## Status

- Phase A: **complete**.
- Verdict: **(a) project exists, no action needed beyond Phase B.**
