"""Verification of the two modules flagged 'never confirmed' in
Platform_Findings_2026-05-31.md: the BofA CSV importer (summary preamble +
blank line before the header) and the SharePoint mirror on missing/partial data.

Verdict (2026-05-31): NO DEFECT in either — both handle the flagged cases. These
tests lock that behavior in as regression coverage.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.banking.csv_import import parse_bofa_csv  # noqa: E402
from modules.documents.sharepoint import StubGraphClient  # noqa: E402
from modules.mirror import sync as sync_mod  # noqa: E402
from modules.mirror.sync import sync_all, sync_portfolio_xlsx, sync_project_markdown  # noqa: E402
from modules.projects.crud import create_project  # noqa: E402

import pytest  # noqa: E402

# A realistic BofA export: multi-line summary preamble, a blank line, the real
# header, then transactions (amounts with quotes/commas, a credit and debits).
BOFA_WITH_PREAMBLE = (
    "Description,,Summary Amt.\n"
    "Beginning balance as of 05/01/2026,,\"12,000.00\"\n"
    "Total credits,,\"3,000.00\"\n"
    "Total debits,,\"-1,500.00\"\n"
    "Ending balance as of 05/31/2026,,\"13,500.00\"\n"
    "\n"
    "Date,Description,Amount,Running Bal.\n"
    "05/01/2026,ZELLE PAYMENT FROM CLIENT,\"2,500.00\",\"14,500.00\"\n"
    "05/02/2026,UBER EATS,-25.50,\"14,474.50\"\n"
    "05/03/2026,PUBLIX SUPER MARKETS,-45.67,\"14,428.83\"\n"
)


class TestBofaPreamble:
    def test_preamble_skipped_real_transactions_parsed(self):
        txns, warnings = parse_bofa_csv(BOFA_WITH_PREAMBLE)
        # exactly the 3 real transactions, no preamble/header/blank leaked in
        assert len(txns) == 3, f"expected 3 txns, got {len(txns)}: {[t['description'] for t in txns]}"
        descs = [t["description"] for t in txns]
        assert "ZELLE PAYMENT FROM CLIENT" in descs
        assert all("balance" not in d.lower() and "total" not in d.lower() for d in descs)
        amounts = sorted(t["amount"] for t in txns)
        assert amounts == [-45.67, -25.50, 2500.00]
        # preamble/header lines were skipped (not silently lost without notice)
        assert warnings, "expected skip warnings for the preamble/header lines"

    def test_no_crash_on_only_preamble(self):
        txns, warnings = parse_bofa_csv("Beginning balance,,\"1.00\"\nTotal credits,,\"0\"\n")
        assert txns == []  # no real transactions; no exception


class TestMirrorMissingData:
    @pytest.fixture()
    def isolated_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sync_mod, "_state_path", lambda: tmp_path / "mirror_state.json")
        monkeypatch.setattr(sync_mod, "_local_snapshots_root", lambda: tmp_path / "snap")

    def test_sync_project_with_sparse_nulls_does_not_crash(self, db, isolated_state):
        # project with only the required columns; everything else NULL/missing
        pid = create_project(db, name="Sparse", status="active", state="FL")
        res = sync_project_markdown(db, pid, client=StubGraphClient(), today=date(2026, 5, 31))
        assert res["status"] in ("local", "uploaded")

    def test_sync_missing_project_returns_missing(self, db, isolated_state):
        res = sync_project_markdown(db, 999_999, client=StubGraphClient(), today=date(2026, 5, 31))
        assert res["status"] == "missing"

    def test_portfolio_and_sync_all_on_empty_db(self, db, isolated_state):
        # zero projects — the "regenerate snapshots" path must not raise
        pf = sync_portfolio_xlsx(db, client=StubGraphClient(), today=date(2026, 5, 31))
        assert pf["status"] in ("local", "uploaded")
        res = sync_all(db, client=StubGraphClient(), today=date(2026, 5, 31))
        assert "errors" in res and not res["errors"]
