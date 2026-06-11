# Postgres cutover rehearsal — 2026-06-11 (local, Docker)

Full dress rehearsal of the persistent-DB cutover, run locally against
`docker-compose.dev.yml` Postgres 16 before touching any Azure resource.
This is the evidence base for `azure-postgres-cutover-runbook.md`.

## What was proven

1. **Schema + app code run on Postgres.** Full test suite:
   **544 passed / 0 failed** with `DB_BACKEND=postgres` (and 544/544 on
   SQLite — no regressions).
2. **Real data imports cleanly.** `scripts/import_legacy_xlsx.py --commit`
   against a same-day READ-ONLY copy of `Project_Tracker_2026.xlsx`:
   70 rows → **68 projects created**, 2 skipped (blank trailing rows),
   0 errors.
3. **Dollar totals match the tracker to the penny:**

   | Measure            | Tracker     | Postgres    |
   |--------------------|-------------|-------------|
   | Projects           | 68          | 68          |
   | Contract value     | $206,956.50 | $206,956.50 |
   | Amount paid        | $129,066.00 | $129,066.00 |
   | Outstanding        | $77,890.50  | $77,890.50  |

   Per-row spot checks (231101, 250430, 250820, 250923, 251007, 251008)
   all matched.
4. **Persistence proven.** `docker restart` of the database container —
   all 68 projects and totals intact afterwards. That restart is the local
   stand-in for the redeploy that used to wipe everything.

## Notes / known gaps

- Status distribution after import: 27 completed, 17 inspection,
  14 ahj_permitting, 6 revisions, 3 drafting, 1 active.
- The importer creates **projects only** — the `Company / Client` column is
  parsed but client records are not created (pre-existing importer behavior,
  same on SQLite). CRM/client linkage is a follow-up.
- Found and fixed a real importer bug during the rehearsal: it closed the
  shared cached DB connection between the classify and commit phases, which
  crashed `--commit` on any backend.
