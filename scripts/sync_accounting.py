"""Nightly sync: keep the 6DE platform DB current with the accounting workbook.

Computes a SHA-256 hash of the accounting Excel file, compares it against a
stored hash in db/.sync_state.json, and runs the import only when the file
has changed.  Designed to be triggered by Windows Task Scheduler.

Usage:
    python scripts/sync_accounting.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap — add platform root to sys.path so 'db' and 'config' resolve
# ---------------------------------------------------------------------------
PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db import ensure_db  # noqa: E402

import openpyxl  # noqa: E402

# Import the individual importer functions (not main — we orchestrate here)
from scripts.importers.import_accounting import (  # noqa: E402
    SOURCE as WORKBOOK_PATH,
    import_transactions,
    import_project_revenue,
    import_recurring_expenses,
    import_crm,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
STATE_FILE = PLATFORM_ROOT / "db" / ".sync_state.json"
LOG_FILE = PLATFORM_ROOT / "scripts" / "sync_accounting.log"

# ---------------------------------------------------------------------------
# Logging — dual output: file + console
# ---------------------------------------------------------------------------
logger = logging.getLogger("sync_accounting")
logger.setLevel(logging.INFO)

_fmt = logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s",
                         datefmt="%Y-%m-%d %H:%M:%S")

_fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_ch = logging.StreamHandler()
_ch.setFormatter(_fmt)
logger.addHandler(_ch)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _compute_hash(filepath: Path) -> str:
    """Return hex SHA-256 digest of the file contents."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_state() -> dict:
    """Load the previous sync state. Returns empty dict on first run."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not read state file (%s); treating as first run", exc)
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Core sync
# ---------------------------------------------------------------------------
def run_sync() -> None:
    logger.info("===== Accounting sync started =====")

    # --- Check workbook existence (OneDrive might be offline) ----------------
    if not WORKBOOK_PATH.exists():
        logger.warning("Workbook not found: %s", WORKBOOK_PATH)
        logger.warning("OneDrive may be offline or the file was moved. Exiting.")
        return

    # --- Hash comparison ------------------------------------------------------
    current_hash = _compute_hash(WORKBOOK_PATH)
    state = _load_state()
    previous_hash = state.get("last_hash")

    if current_hash == previous_hash:
        logger.info("No changes detected (hash unchanged). Nothing to do.")
        return

    if previous_hash is None:
        logger.info("First run — no previous hash. Performing full import.")
    else:
        logger.info("Workbook changed (hash differs). Running import.")

    # --- Open workbook and DB -------------------------------------------------
    wb = openpyxl.load_workbook(WORKBOOK_PATH, data_only=True, read_only=True)
    conn = ensure_db()

    row_counts: dict[str, int] = {}

    try:
        # Transactions ---------------------------------------------------------
        before_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        txn_stats = import_transactions(conn, wb)
        after_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        txn_inserted = after_txn - before_txn
        row_counts["transactions"] = after_txn
        logger.info("Transactions:       %d inserted, %d skipped",
                     txn_inserted, txn_stats["skipped"])

        # Tag newly-inserted transactions whose source is still NULL.
        # The DEFAULT 'excel_sync' covers new rows, but this is a safety net
        # in case any were inserted without the default being applied.
        conn.execute(
            "UPDATE transactions SET source = 'excel_sync' WHERE source IS NULL"
        )
        conn.commit()

        # Project Revenue ------------------------------------------------------
        rev_stats = import_project_revenue(conn, wb)
        row_counts["project_revenue"] = conn.execute(
            "SELECT COUNT(*) FROM project_revenue"
        ).fetchone()[0]
        logger.info("Project Revenue:    %d inserted, %d updated, %d skipped",
                     rev_stats["inserted"], rev_stats["updated"],
                     rev_stats["skipped"])

        # Recurring Expenses ---------------------------------------------------
        recur_stats = import_recurring_expenses(conn, wb)
        row_counts["recurring_expenses"] = conn.execute(
            "SELECT COUNT(*) FROM recurring_expenses"
        ).fetchone()[0]
        logger.info("Recurring Expenses: %d inserted, %d updated, %d skipped",
                     recur_stats["inserted"], recur_stats["updated"],
                     recur_stats["skipped"])

        # CRM ------------------------------------------------------------------
        crm_stats = import_crm(conn, wb)
        row_counts["clients"] = conn.execute(
            "SELECT COUNT(*) FROM clients"
        ).fetchone()[0]
        logger.info("CRM (clients):      %d inserted, %d updated, %d skipped",
                     crm_stats["inserted"], crm_stats["updated"],
                     crm_stats["skipped"])

    except Exception:
        logger.exception("Import failed with an unexpected error")
        raise
    finally:
        wb.close()
        conn.close()

    # --- Persist state --------------------------------------------------------
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _save_state({
        "last_hash": current_hash,
        "last_sync": now_iso,
        "last_row_counts": row_counts,
    })
    logger.info("State saved. Sync complete at %s", now_iso)
    logger.info("===== Accounting sync finished =====")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        run_sync()
    except Exception:
        logger.exception("Fatal error — sync aborted")
        sys.exit(1)

    # Print scheduler setup instructions
    script_path = Path(__file__).resolve()
    print()
    print("# -----------------------------------------------------------------")
    print("# To schedule nightly at 10 PM via Windows Task Scheduler:")
    print(f'# schtasks /create /tn "6DE_Accounting_Sync" /tr "python {script_path}" /sc daily /st 22:00')
    print("# -----------------------------------------------------------------")


if __name__ == "__main__":
    main()
