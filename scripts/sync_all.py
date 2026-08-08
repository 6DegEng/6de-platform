"""One-way sync: OneDrive workbooks -> platform database.

Juan works in Excel; the platform mirrors it. This orchestrator is what makes
"keep it in sync" a non-event instead of a manual debugging session.

Direction is ONE-WAY and non-negotiable: workbooks are the source of truth and
this never writes back to them. It does not even open them for write — each
source is copied to a temp file first, so a running Excel instance is never
locked out and a half-saved workbook can never be parsed mid-write.

Per source, in order:
  1. Resolve the workbook path (CLI arg -> env var -> OneDrive under ~).
  2. Hash-gate: skip entirely if the file has not changed since the last run.
  3. Snapshot: copy to a temp file and parse the copy, never the live file.
  4. Reconcile (dry-run): compute what WOULD be written and check it against
     the workbook's own control total.
  5. Commit ONLY if reconciliation is exact. A mismatch skips the write and
     flags the run — never a partial import.
  6. Record freshness in the database and append a JSONL run record.

Reconciliation gating the write is the core safety property. Everything else
(hash gate, snapshot) is about not being disruptive; this is about not being
wrong. `--force-commit` exists as a documented escape hatch for the operator
who has looked at a mismatch and decided it is acceptable.

Usage:
    python scripts/sync_all.py                  # dry-run everything (safe)
    python scripts/sync_all.py --commit         # write only what reconciles
    python scripts/sync_all.py --source tracker # one source
    python scripts/sync_all.py --force          # ignore the hash gate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import contextlib
import shutil
import sys
import tempfile
import traceback
from datetime import datetime, timezone
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

import openpyxl  # noqa: E402

from db import ensure_db  # noqa: E402
from scripts.importers import import_accounting as acc  # noqa: E402
from scripts.importers import import_permits as permits  # noqa: E402
from scripts.importers import import_project_tracker as trk  # noqa: E402

STATE_FILE = PLATFORM_ROOT / "db" / ".sync_state.json"
RUN_LOG = PLATFORM_ROOT / "db" / "sync_runs.jsonl"

# Freshness lives in the DB, not just in the local state file: the sync runs on
# Juan's PC but the app runs in Azure, so the app can only show "data as of X"
# if X is written where the app can read it.
META_PREFIX = "sync"


def _bridge_opportunities(conn, _payload) -> dict:
    """Turn freshly-imported proposals into CRM opportunities.

    Signature matches the other importers (conn, payload) so it can sit in the
    same list; the workbook is not needed because the bridge reads the rows the
    proposal import just wrote.
    """
    from db import bridge_proposals_to_opportunities

    return bridge_proposals_to_opportunities(conn)


# ---------------------------------------------------------------------------
# Source registry
# ---------------------------------------------------------------------------
class Source:
    """One workbook and the functions that reconcile and import it.

    ``importers`` run in order inside a single transaction; each takes
    (conn, workbook) and returns a stats dict.
    """

    def __init__(self, key, label, resolve, reconcile, importers, control,
                 kind="workbook"):
        self.key = key
        self.label = label
        self.resolve = resolve
        self.reconcile = reconcile
        self.importers = importers
        self.control = control  # plain-English description of the check
        # "workbook" sources are copied and parsed with openpyxl; "folder"
        # sources (the permit register) are walked in place. Both are
        # read-only; the snapshot exists to avoid locking a file Juan has open,
        # and a directory walk never opens anything for write.
        self.kind = kind

    def prepare(self, payload):
        """What the importers actually consume.

        Workbook importers take the openpyxl workbook straight through. The
        permit importer takes the parsed folder scan, so the walk happens once
        here rather than inside every importer.
        """
        if self.kind == "folder":
            return permits.scan_projects(payload)
        return payload

    def describe_reconciliation(self, rec: dict) -> str:
        if self.key == "permits":
            return (
                f"{rec['folders']} project folders, {rec['discovered']} permit "
                f"numbers found in {rec['with_permits']} of them"
            )
        if self.key == "accounting":
            base = (
                f"{rec['importable']} rows, net {rec['net']:,.2f} vs "
                f"workbook cashflow {rec['cashflow_net']}"
            )
            if not rec.get("nothing_lost", True):
                parts = []
                if rec.get("rejected_rows"):
                    kinds = ", ".join(
                        f"{k!r}x{n}" for k, n in rec["rejected_account_types"].items()
                    )
                    parts.append(
                        f"{rec['rejected_rows']} rows worth {rec['rejected_net']:,.2f} "
                        f"rejected by CHECK(account_type) [{kinds}]"
                    )
                if rec.get("collapsed_rows"):
                    parts.append(
                        f"{rec['collapsed_rows']} repeated rows collapsed by "
                        f"UNIQUE(txn_date, amount, description)"
                    )
                gap = rec["net"] - rec["storable_net"]
                base += (f"; WOULD LOSE {gap:,.2f} - " + "; ".join(parts))
            return base
        return (
            f"{rec['importable']} projects, contracts {rec['contract_total']:,.2f}, "
            f"{rec['unreadable_money']} unreadable money cells"
        )


SOURCES = {
    "accounting": Source(
        key="accounting",
        label="Accounting workbook",
        resolve=acc.resolve_source,
        reconcile=acc.reconcile_transactions,
        importers=[
            ("transactions", acc.import_transactions),
            ("recurring_expenses", acc.import_recurring_expenses),
            ("project_revenue", acc.import_project_revenue),
            ("crm", acc.import_crm),
        ],
        control="Transactions net must equal the Cashflow sheet TOTAL to the cent",
    ),
    "tracker": Source(
        key="tracker",
        label="Project tracker",
        resolve=trk.resolve_source,
        reconcile=trk.reconcile_projects,
        importers=[
            ("projects", trk.import_projects),
            ("proposals", trk.import_proposals),
            ("crm", trk.import_crm),
            # Runs LAST, after proposals exist. Without this a sync imports 91
            # proposals and leaves the CRM pipeline reading $0, because the
            # bridge otherwise only fires inside ensure_db() at app startup —
            # and that is cached per container, so opportunities would not
            # appear until Azure happened to restart. That is the "$0 pipeline
            # / 0 opportunities" in ROADMAP §1.1.
            ("opportunities", _bridge_opportunities),
        ],
        control="every project row must yield a readable contract value",
    ),
    "permits": Source(
        key="permits",
        label="Permit register (project folders)",
        resolve=permits.resolve_projects_root,
        reconcile=permits.reconcile_permits,
        importers=[("permits", permits.import_permits)],
        control="the active-projects folder must contain project folders",
        kind="folder",
    ),
}


# Run order matters and is NOT alphabetical: permits link to projects by job
# number, so the tracker must populate `projects` first or every permit lands
# with no parent and is dropped. (Alphabetical order did exactly that on
# 2026-08-08 — 52 folders, 0 permits written; the post-write check caught it.)
SOURCE_ORDER = ("tracker", "accounting", "permits")


# ---------------------------------------------------------------------------
# State + logging
# ---------------------------------------------------------------------------
def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_hash(path: Path) -> str:
    """Content hash for a file, or a cheap tree fingerprint for a folder.

    Hashing every byte under a project tree would take minutes; names + sizes +
    mtimes change whenever a permit document lands, which is the only signal
    the folder walk cares about.
    """
    h = hashlib.sha256()
    if path.is_dir():
        for entry in sorted(path.rglob("*")):
            try:
                stat = entry.stat()
                h.update(f"{entry.relative_to(path)}|{stat.st_size}|"
                         f"{int(stat.st_mtime)}\n".encode())
            except OSError:
                continue  # vanished mid-walk (OneDrive sync) — ignore
        return h.hexdigest()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # A corrupt state file must not stop a sync — worst case we re-import,
        # and every importer is idempotent.
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def append_run_log(record: dict) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def record_freshness(conn, source_key: str, record: dict) -> None:
    """Store last-run facts in _meta so the app can show 'Data as of ...'."""
    from db import _ensure_meta_table

    _ensure_meta_table(conn)
    for field in ("status", "at", "detail"):
        conn.execute(
            "INSERT INTO _meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (f"{META_PREFIX}:{source_key}:{field}", str(record.get(field, ""))),
        )
    conn.commit()


def read_freshness(conn) -> dict:
    """What the app shows. Returns {source: {status, at, detail}}."""
    out: dict[str, dict] = {}
    try:
        rows = conn.execute(
            "SELECT key, value FROM _meta WHERE key LIKE ?",
            (f"{META_PREFIX}:%",),
        ).fetchall()
    except Exception:  # noqa: BLE001 — never let a missing table break a page
        return out
    for row in rows:
        parts = str(row["key"]).split(":")
        if len(parts) != 3:
            continue
        out.setdefault(parts[1], {})[parts[2]] = row["value"]
    return out


def verify_landed(source: Source, conn, rec: dict) -> tuple[bool, str]:
    """Compare what is IN the database against the workbook's control total.

    Reconciliation predicts; this confirms. They are deliberately independent —
    a bug in the prediction is exactly what this is here to catch.
    """
    if source.key == "permits":
        row = conn.execute("SELECT COUNT(*) AS n FROM permits").fetchone()
        # No money to reconcile — the check is that the register is not empty
        # after a run that claimed to find permits.
        ok = row["n"] > 0 or rec["discovered"] == 0
        return ok, f"db holds {row['n']} permits ({rec['discovered']} numbers found)"

    if source.key == "accounting":
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total "
            "FROM transactions"
        ).fetchone()
        stored = round(float(row["total"]), 2)
        expected = rec["net"]
        ok = stored == expected
        return ok, (f"db holds {row['n']} transactions totalling {stored:,.2f} "
                    f"vs workbook {expected:,.2f}")

    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(contract_value), 0) AS total "
        "FROM projects"
    ).fetchone()
    stored = round(float(row["total"]), 2)
    expected = rec["contract_total"]
    # Projects accumulate across sources (some predate the tracker), so the
    # stored total is allowed to EXCEED the workbook - it must never fall short.
    ok = stored >= expected - 0.01
    return ok, (f"db holds {row['n']} projects totalling {stored:,.2f} "
                f"vs workbook {expected:,.2f}")


# ---------------------------------------------------------------------------
# The sync itself
# ---------------------------------------------------------------------------
def sync_source(source: Source, conn, *, commit: bool, force: bool,
                force_commit: bool, log=print) -> dict:
    """Run one source end to end. Returns the run record (also logged)."""
    record = {
        "source": source.key,
        "at": _now(),
        "status": "unknown",
        "committed": False,
        "detail": "",
    }

    path = source.resolve()
    if not path.exists():
        record.update(status="missing",
                      detail=f"workbook not found: {path}")
        log(f"[{source.key}] SKIP - not found: {path}")
        return record

    state = load_state()
    prior = state.get(source.key, {}).get("hash")
    current = file_hash(path)
    record["hash"] = current

    if current == prior and not force:
        record.update(status="unchanged", detail="workbook unchanged since last run")
        log(f"[{source.key}] unchanged - nothing to do")
        return record

    # Snapshot: parse a copy so a live Excel session is never locked or
    # half-read. openpyxl would otherwise hold the real file open. Folder
    # sources are walked in place — a read-only walk locks nothing.
    with contextlib.ExitStack() as stack:
        if source.kind == "folder":
            payload = path
            wb = None
        else:
            tmp = stack.enter_context(tempfile.TemporaryDirectory())
            snapshot = Path(tmp) / path.name
            shutil.copy2(path, snapshot)
            wb = openpyxl.load_workbook(snapshot, data_only=True, read_only=True)
            payload = wb
        try:
            rec = source.reconcile(payload)
            record["reconciliation"] = rec
            summary = source.describe_reconciliation(rec)
            record["detail"] = summary

            if not rec.get("matches"):
                if not force_commit:
                    record["status"] = "mismatch"
                    log(f"[{source.key}] MISMATCH - {summary}")
                    log(f"           control: {source.control}")
                    log("           refusing to write. Nothing was changed.")
                    return record
                # Overridden deliberately. Make it impossible to miss in the
                # console AND in the run log, so a forced import is never
                # mistaken later for a clean one.
                record["forced"] = True
                log(f"[{source.key}] MISMATCH OVERRIDDEN by --force-commit - {summary}")
                log(f"           control that failed: {source.control}")
            else:
                log(f"[{source.key}] reconciled OK - {summary}")

            if not commit:
                record["status"] = "dry-run"
                log(f"[{source.key}] dry-run only; re-run with --commit to write")
                return record

            stats = {}
            for name, fn in source.importers:
                stats[name] = fn(conn, source.prepare(payload))
                log(f"           {name}: {stats[name]}")
            conn.commit()

            # Second net: check what actually LANDED, not what we predicted.
            # The importers commit internally, so this cannot roll back — but
            # it turns "silently wrong numbers on the dashboard" into a loud
            # failure, and it deliberately does NOT advance the hash gate, so
            # the next run retries instead of assuming success.
            ok, detail = verify_landed(source, conn, rec)
            record["verification"] = detail
            if not ok:
                record.update(status="verify-failed", committed=False)
                log(f"[{source.key}] POST-WRITE CHECK FAILED - {detail}")
                log("           data is in the database but does NOT match the "
                    "workbook. Investigate before trusting these numbers.")
                return record
            log(f"[{source.key}] post-write check OK - {detail}")
            record.update(
                status="committed-forced" if record.get("forced") else "committed",
                committed=True, stats=stats,
            )
        except Exception as exc:  # noqa: BLE001
            conn.rollback()
            record.update(status="error", detail=f"{type(exc).__name__}: {exc}")
            record["traceback"] = traceback.format_exc(limit=5)
            log(f"[{source.key}] ERROR - {exc}")
            return record
        finally:
            if wb is not None:
                wb.close()

    # Only advance the hash after a successful COMMIT. Advancing it after a
    # dry-run would make the next run think the file was already imported.
    if record["committed"]:
        state.setdefault(source.key, {})["hash"] = current
        state[source.key]["last_commit"] = record["at"]
        save_state(state)

    return record


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--commit", action="store_true",
                   help="Write to the DB. Without this it is a read-only dry-run.")
    p.add_argument("--source", choices=list(SOURCE_ORDER),
                   help="Only sync this source (default: all).")
    p.add_argument("--force", action="store_true",
                   help="Ignore the hash gate and re-read even if unchanged.")
    p.add_argument("--force-commit", action="store_true",
                   help="Commit even if reconciliation fails. Escape hatch for an "
                        "operator who has reviewed the mismatch; logged as such.")
    args = p.parse_args(argv)

    keys = [args.source] if args.source else list(SOURCE_ORDER)
    conn = ensure_db()
    records = []
    try:
        for key in keys:
            rec = sync_source(
                SOURCES[key], conn,
                commit=args.commit or args.force_commit,
                force=args.force,
                force_commit=args.force_commit,
            )
            records.append(rec)
            append_run_log(rec)
            try:
                record_freshness(conn, key, rec)
            except Exception as exc:  # noqa: BLE001
                # Freshness is reporting, not the job — never fail a good
                # import because the status line could not be written.
                print(f"[{key}] warning: could not record freshness: {exc}")
    finally:
        conn.close()

    print("\n=== summary ===")
    for rec in records:
        print(f"  {rec['source']:12} {rec['status']:11} {rec['detail']}")
    if not args.commit and any(r["status"] == "dry-run" for r in records):
        print("\nDry-run only. Re-run with --commit to write these changes.")

    bad = {"error", "mismatch"}
    return 1 if any(r["status"] in bad for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
