"""Orchestrator: run all importers in dependency order and print reconciliation.

Order:
  1. import_project_tracker — establishes projects + clients first
  2. import_accounting      — FKs depend on projects existing

Prints a reconciliation summary showing how many transactions matched
to a project vs. orphaned.
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db import ensure_db  # noqa: E402


def main():
    separator = "=" * 60

    # ------------------------------------------------------------------
    # Step 1: Import Project Tracker (projects, proposals, CRM contacts)
    # ------------------------------------------------------------------
    print(separator)
    print("STEP 1: Importing Project Tracker")
    print(separator)
    try:
        from scripts.importers.import_project_tracker import main as run_project_tracker
        run_project_tracker()
    except Exception as e:
        print(f"ERROR in project tracker import: {e}")
        # Continue to step 2 even if step 1 has issues
        import traceback
        traceback.print_exc()

    print()

    # ------------------------------------------------------------------
    # Step 2: Import Accounting (transactions, revenue, recurring, CRM)
    # ------------------------------------------------------------------
    print(separator)
    print("STEP 2: Importing Accounting")
    print(separator)
    try:
        from scripts.importers.import_accounting import main as run_accounting
        run_accounting()
    except Exception as e:
        print(f"ERROR in accounting import: {e}")
        import traceback
        traceback.print_exc()

    print()

    # ------------------------------------------------------------------
    # Step 3: Reconciliation Summary
    # ------------------------------------------------------------------
    print(separator)
    print("RECONCILIATION")
    print(separator)

    conn = ensure_db()
    try:
        total_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        matched_txn = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE project_id IS NOT NULL"
        ).fetchone()[0]
        orphaned_txn = total_txn - matched_txn

        total_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        total_clients = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        total_proposals = conn.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
        total_revenue = conn.execute("SELECT COUNT(*) FROM project_revenue").fetchone()[0]
        total_recurring = conn.execute("SELECT COUNT(*) FROM recurring_expenses").fetchone()[0]

        print(f"Projects in DB:              {total_projects}")
        print(f"Clients in DB:               {total_clients}")
        print(f"Proposals in DB:             {total_proposals}")
        print(f"Project revenue snapshots:   {total_revenue}")
        print(f"Recurring expenses:          {total_recurring}")
        print()
        print(f"Transactions total:          {total_txn}")
        print(f"  Matched to a project:      {matched_txn}")
        print(f"  Orphaned (no project):     {orphaned_txn}")
        if total_txn > 0:
            pct = round(matched_txn / total_txn * 100, 1)
            print(f"  Match rate:                {pct}%")

        # Show project status breakdown
        print()
        print("Project status breakdown:")
        for row in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM projects GROUP BY status ORDER BY cnt DESC"
        ):
            print(f"  {row['status']:15s} {row['cnt']}")

    finally:
        conn.close()

    print()
    print(separator)
    print("IMPORT COMPLETE")
    print(separator)


if __name__ == "__main__":
    main()
