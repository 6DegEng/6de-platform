"""Importer financial synthesis (feat/importer-financial-synthesis).

The tracker carries Contract Value / Amount Paid / Outstanding Balance per
project but no invoice records, so Financials/AR showed $0 after import.
With --synthesize-financials the importer creates at most two invoices per
project (<job>-L1 paid, <job>-L2 outstanding); with --create-clients it
find-or-creates client records from Company/Contact and links them.

Both flags default OFF — the base import behavior is byte-identical.
All tests run against the throwaway test DB fixture; nothing here can
touch production (commit_rows receives the fixture connection).
"""
from __future__ import annotations

import sys
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from scripts.import_legacy_xlsx import (  # noqa: E402
    Outcome,
    client_identity,
    commit_rows,
    ensure_client,
    synthesize_invoices,
)


# ---------------------------------------------------------------------------
# synthesize_invoices — pure function
# ---------------------------------------------------------------------------
class TestSynthesizeInvoices:
    def test_paid_and_outstanding_make_two_invoices(self):
        row = {
            "job_number": "260101", "start_date": "2026-01-15",
            "amount_paid": 7500.0, "outstanding_balance": 2500.0,
        }
        invs = synthesize_invoices(row)
        assert [i["invoice_number"] for i in invs] == ["260101-L1", "260101-L2"]
        paid, outstanding = invs
        assert paid["status"] == "paid"
        assert paid["amount"] == paid["paid_amount"] == 7500.0
        assert paid["issue_date"] == paid["paid_date"] == "2026-01-15"
        assert outstanding["status"] == "sent"
        assert outstanding["amount"] == 2500.0
        assert outstanding["paid_amount"] == 0

    def test_totals_match_tracker_to_the_penny(self):
        row = {
            "job_number": "260304", "start_date": "2026-03-04",
            "amount_paid": 129066.00, "outstanding_balance": 77890.50,
        }
        invs = synthesize_invoices(row)
        assert sum(i["amount"] for i in invs) == 129066.00 + 77890.50

    def test_zero_dollars_make_no_invoices(self):
        assert synthesize_invoices({"job_number": "260101"}) == []
        assert synthesize_invoices(
            {"job_number": "260101", "amount_paid": 0, "outstanding_balance": 0}
        ) == []

    def test_no_job_number_makes_no_invoices(self):
        assert synthesize_invoices({"amount_paid": 100.0}) == []

    def test_missing_start_date_falls_back_to_today(self):
        from datetime import date
        invs = synthesize_invoices({"job_number": "260101", "amount_paid": 1.0})
        assert invs[0]["issue_date"] == date.today().isoformat()

    def test_notes_say_synthesized(self):
        invs = synthesize_invoices({"job_number": "260101", "amount_paid": 1.0})
        assert "Synthesized" in invs[0]["notes"]


# ---------------------------------------------------------------------------
# client identity / ensure_client
# ---------------------------------------------------------------------------
class TestClients:
    def test_identity_none_when_absent(self):
        assert client_identity({}) is None
        assert client_identity({"_client_company": "  "}) is None

    def test_identity_case_insensitive(self):
        a = client_identity({"_client_company": "ACME Corp", "_client_contact": "Jane"})
        b = client_identity({"_client_company": "acme corp", "_client_contact": "jane"})
        assert a == b

    def test_ensure_client_creates_then_reuses(self, db):
        cid1 = ensure_client(db, "Acme Corp", "Jane Doe")
        cid2 = ensure_client(db, "ACME CORP", "jane doe")
        assert cid1 == cid2
        row = db.execute("SELECT name, company FROM clients WHERE id = ?", (cid1,)).fetchone()
        assert row["name"] == "Jane Doe"
        assert row["company"] == "Acme Corp"
        assert db.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"] == 1

    def test_ensure_client_company_only(self, db):
        cid = ensure_client(db, "Solo LLC", None)
        row = db.execute("SELECT name FROM clients WHERE id = ?", (cid,)).fetchone()
        assert row["name"] == "Solo LLC"

    def test_ensure_client_nothing_returns_none(self, db):
        assert ensure_client(db, None, None) is None
        assert ensure_client(db, " ", "") is None


# ---------------------------------------------------------------------------
# commit_rows integration (fixture DB only)
# ---------------------------------------------------------------------------
def _result(jn, name, outcome=Outcome.CREATE):
    return {"row": 1, "job_number": jn, "name": name, "outcome": outcome, "errors": []}


def _row(jn, name, **extra):
    return {"job_number": jn, "name": name, "status": "active", **extra}


class TestCommitSynthesis:
    def test_flags_off_creates_nothing_extra(self, db):
        counters = commit_rows(
            [_result("260101", "A")],
            [_row("260101", "A", amount_paid=100.0, _client_company="Acme")],
            conn=db,
        )
        assert counters == {"invoices_created": 0, "clients_created": 0, "clients_linked": 0}
        assert db.execute("SELECT COUNT(*) AS c FROM invoices").fetchone()["c"] == 0
        assert db.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"] == 0

    def test_synthesis_creates_invoices_and_clients(self, db):
        counters = commit_rows(
            [_result("260101", "A"), _result("260201", "B")],
            [
                _row("260101", "A", start_date="2026-01-15",
                     amount_paid=7500.0, outstanding_balance=2500.0,
                     _client_company="Acme Corp", _client_contact="Jane Doe"),
                _row("260201", "B", outstanding_balance=900.0,
                     _client_company="Acme Corp", _client_contact="Jane Doe"),
            ],
            conn=db,
            synthesize_financials=True,
            create_clients=True,
        )
        assert counters["invoices_created"] == 3  # L1+L2 for A, L2 for B
        assert counters["clients_created"] == 1   # same client deduped
        assert counters["clients_linked"] == 2

        # Dollar totals land where the dashboard reads them.
        outstanding = db.execute(
            "SELECT COALESCE(SUM(amount - paid_amount), 0) AS o "
            "FROM invoices WHERE status IN ('sent', 'overdue')"
        ).fetchone()["o"]
        assert outstanding == 2500.0 + 900.0
        paid = db.execute(
            "SELECT COALESCE(SUM(paid_amount), 0) AS p FROM invoices "
            "WHERE status = 'paid'"
        ).fetchone()["p"]
        assert paid == 7500.0

        # Both projects linked to the ONE client record.
        client_ids = {
            r["client_id"] for r in db.execute(
                "SELECT client_id FROM projects WHERE job_number IN ('260101','260201')"
            ).fetchall()
        }
        assert len(client_ids) == 1 and None not in client_ids

    def test_rerun_is_idempotent(self, db):
        results = [_result("260101", "A")]
        rows = [_row("260101", "A", amount_paid=100.0,
                     _client_company="Acme", _client_contact="Jane")]
        c1 = commit_rows(results, rows, conn=db,
                         synthesize_financials=True, create_clients=True)
        # Second run: project now exists -> UPDATE path; invoices/client must
        # NOT duplicate.
        results2 = [_result("260101", "A", outcome=Outcome.UPDATE)]
        c2 = commit_rows(results2, rows, conn=db,
                         synthesize_financials=True, create_clients=True)
        assert c1["invoices_created"] == 1
        assert c2["invoices_created"] == 0
        assert c2["clients_created"] == 0
        assert db.execute("SELECT COUNT(*) AS c FROM invoices").fetchone()["c"] == 1
        assert db.execute("SELECT COUNT(*) AS c FROM clients").fetchone()["c"] == 1

    def test_existing_client_link_not_overwritten(self, db):
        from modules.projects.crud import create_project
        other = ensure_client(db, "Original LLC", None)
        create_project(db, name="A", job_number="260101", client_id=other)
        commit_rows(
            [_result("260101", "A", outcome=Outcome.UPDATE)],
            [_row("260101", "A", _client_company="Different Corp")],
            conn=db,
            create_clients=True,
        )
        row = db.execute(
            "SELECT client_id FROM projects WHERE job_number = '260101'"
        ).fetchone()
        assert row["client_id"] == other  # only fills NULL, never overwrites
