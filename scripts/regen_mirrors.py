"""Regenerate SharePoint mirror files (_AUTO_project_summary.md + _AUTO_portfolio_overview.xlsx).

Default mode is --dry-run (renders, computes sha256, reports what would change
without uploading). Use --commit to actually upload.

Usage:
    python scripts/regen_mirrors.py --all              # dry-run all projects + portfolio
    python scripts/regen_mirrors.py --all --commit     # actually upload
    python scripts/regen_mirrors.py --project 12       # single project
    python scripts/regen_mirrors.py --portfolio-only   # portfolio xlsx only

Activity log entries are written only when --commit is supplied. When
MSGRAPH_CLIENT_ID / MSGRAPH_TENANT_ID are unset, the sync writes to
db/.snapshots/ locally instead of SharePoint (still ``--commit`` to actually write).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make `modules.*` importable when run directly.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from db import ensure_db  # noqa: E402
from modules.mirror.sync import (  # noqa: E402
    sync_all,
    sync_portfolio_xlsx,
    sync_project_markdown,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Regenerate SharePoint mirror snapshots.")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--all", action="store_true", help="Sync every project + portfolio xlsx")
    target.add_argument("--project", type=int, metavar="ID", help="Sync one project's markdown by id")
    target.add_argument("--portfolio-only", action="store_true", help="Sync the portfolio xlsx only")
    p.add_argument("--commit", action="store_true", help="Actually upload (default is dry-run)")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return p


def _print_result(label: str, result: dict) -> None:
    status = result.get("status", "?")
    sha = (result.get("sha256") or "")[:12]
    path = result.get("path") or ""
    print(f"  {label}: status={status} sha256={sha} path={path}")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
    )
    log = logging.getLogger("regen_mirrors")

    conn = ensure_db()

    mode = "COMMIT" if args.commit else "DRY-RUN"
    log.info("Regen mirrors :: mode=%s", mode)

    if args.project is not None:
        if args.commit:
            r = sync_project_markdown(conn, args.project)
            _print_result(f"project {args.project}", r)
        else:
            from modules.mirror.sync import (
                _fetch_project_with_client_name,  # type: ignore[attr-defined]
            )
            row = _fetch_project_with_client_name(conn, args.project)
            if row is None:
                print(f"  project {args.project}: MISSING")
                return 1
            print(f"  project {args.project}: would render + upload {row['job_number']}")
        return 0

    if args.portfolio_only:
        if args.commit:
            r = sync_portfolio_xlsx(conn)
            _print_result("portfolio", r)
        else:
            print("  portfolio: would render + upload (dry-run)")
        return 0

    # --all
    if args.commit:
        result = sync_all(conn)
        counts = result["project_counts"]
        print(
            f"Done. projects: uploaded={counts.get('uploaded', 0)} "
            f"local={counts.get('local', 0)} unchanged={counts.get('unchanged', 0)} "
            f"missing={counts.get('missing', 0)}"
        )
        if result.get("portfolio"):
            _print_result("portfolio", result["portfolio"])
        if result["errors"]:
            print(f"\nErrors ({len(result['errors'])}):")
            for e in result["errors"]:
                print(f"  - {e}")
            return 2
    else:
        rows = conn.execute("SELECT id, job_number, name FROM projects").fetchall()
        print(f"  would sync {len(rows)} project markdowns + portfolio xlsx")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
