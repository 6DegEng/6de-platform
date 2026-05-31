"""Report / backfill NaN-or-NULL project ``contract_value`` rows.

Context (data-integrity bug, 2026-05-31): blank/garbage contract values were
imported as NaN (or left NULL). NaN poisons ``SUM(contract_value)`` and renders
as "$nan" in Recent Activity. The write path is now NaN-safe, but rows imported
before the fix may still hold NaN/NULL.

DEFAULT MODE = DRY-RUN. It only REPORTS:
  * how many projects have NaN/NULL contract_value, and their ids/job numbers
  * what the legacy Project_Tracker xlsx says for each (if the file is reachable)

``--commit`` WOULD write the legacy value (scrubbed via nan_to_none) back to the
DB. It is intentionally left for Juan to run deliberately after reviewing the
dry-run; this script never writes by default.

Usage:
    python scripts/backfill_contract_value.py            # dry-run report
    python scripts/backfill_contract_value.py --commit   # (Juan only)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db import ensure_db  # noqa: E402
from modules.activity_utils import nan_to_none  # noqa: E402


def _is_nan(v) -> bool:
    return isinstance(v, float) and math.isnan(v)


def find_bad_rows(conn) -> list[dict]:
    """Projects whose contract_value is NULL or NaN.

    SQLite stores NaN as a real that fails the ``= ?`` test, so we pull all rows
    and classify in Python to catch both NULL and NaN.
    """
    rows = conn.execute(
        "SELECT id, job_number, name, contract_value FROM projects ORDER BY id"
    ).fetchall()
    return [
        {"id": r["id"], "job_number": r["job_number"], "name": r["name"],
         "contract_value": r["contract_value"]}
        for r in rows
        if r["contract_value"] is None or _is_nan(r["contract_value"])
    ]


def _legacy_values() -> dict[str, float]:
    """Map job_number -> contract_value from the legacy tracker, if reachable.

    Best-effort: returns {} when the xlsx or pandas isn't available so the
    dry-run still reports DB-side counts.
    """
    try:
        import config  # noqa
        from scripts.importers.import_project_tracker import LEGACY_XLSX  # type: ignore
        path = Path(LEGACY_XLSX)
    except Exception:
        path = (
            Path.home() / "OneDrive - 6th Degree Engineering"
            / "Documents - 6th Degree Engineering" / "06_Engineering"
            / "01_ Active Projects" / "Project_Tracker_2026.xlsx"
        )
    if not path.exists():
        return {}
    try:
        import pandas as pd
        df = pd.read_excel(path, sheet_name="Projects", header=2)
    except Exception:
        return {}
    out: dict[str, float] = {}
    for _, row in df.iterrows():
        job = str(row.get("Job #", "") or "").strip()
        val = nan_to_none(row.get("Contract Value"))
        if job and isinstance(val, (int, float)):
            out[job] = float(val)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--commit", action="store_true",
                    help="Write legacy values back (Juan only; default is dry-run).")
    args = ap.parse_args()

    conn = ensure_db()
    bad = find_bad_rows(conn)
    legacy = _legacy_values()

    print("  Contract-value backfill -", "COMMIT" if args.commit else "DRY-RUN")
    print(f"  Projects with NaN/NULL contract_value: {len(bad)}")
    print(f"  Affected ids: {[r['id'] for r in bad]}")
    if not legacy:
        print("  Legacy xlsx NOT reachable — reporting DB-side counts only.")
    usable = 0
    for r in bad:
        lv = legacy.get(str(r["job_number"]))
        usable += lv is not None
        shown = f"{lv:,.2f}" if lv is not None else "(no legacy value)"
        print(f"  # {r['id']:>3}  job={r['job_number']}  legacy={shown}  {r['name']}")
    print(f"  Rows with a usable legacy value: {usable}")

    if not args.commit:
        print("  DRY-RUN - no changes written. Run with --commit to persist (Juan only).")
        return 0

    written = 0
    for r in bad:
        lv = legacy.get(str(r["job_number"]))
        if lv is not None:
            conn.execute("UPDATE projects SET contract_value = ? WHERE id = ?",
                         (float(lv), r["id"]))
            written += 1
    conn.commit()
    print(f"  COMMITTED {written} backfilled contract_value rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
