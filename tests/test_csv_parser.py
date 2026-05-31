"""Unit tests for the BofA CSV parser.

Covers: empty files, malformed dates, Unicode descriptions, amount parsing,
header detection, BofA-specific quirks, and row-hash dedup.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

# Bootstrap project root so imports resolve
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.banking.csv_import import (
    parse_bofa_csv,
    compute_row_hash,
    _parse_date,
    _parse_amount,
    _clean_description,
)


# ====================================================================
# _parse_date
# ====================================================================

class TestParseDate:
    def test_standard_format(self):
        assert _parse_date("05/01/2026") == "2026-05-01"

    def test_single_digit_month_day(self):
        assert _parse_date("1/5/2026") == "2026-01-05"

    def test_two_digit_year(self):
        assert _parse_date("12/31/26") == "2026-12-31"

    def test_whitespace_stripped(self):
        assert _parse_date("  05/01/2026  ") == "2026-05-01"

    def test_invalid_date_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _parse_date("") is None

    def test_iso_format_not_supported(self):
        # BofA doesn't use ISO; parser should not match it
        assert _parse_date("2026-05-01") is None


# ====================================================================
# _parse_amount
# ====================================================================

class TestParseAmount:
    def test_positive(self):
        assert _parse_amount("1234.56") == 1234.56

    def test_negative(self):
        assert _parse_amount("-500.00") == -500.0

    def test_with_commas(self):
        assert _parse_amount("1,234,567.89") == 1234567.89

    def test_with_dollar_sign(self):
        assert _parse_amount("$1,234.56") == 1234.56

    def test_whitespace(self):
        assert _parse_amount("  -42.00  ") == -42.0

    def test_empty_string_returns_none(self):
        assert _parse_amount("") is None

    def test_non_numeric_returns_none(self):
        assert _parse_amount("abc") is None


# ====================================================================
# _clean_description
# ====================================================================

class TestCleanDescription:
    def test_strips_whitespace(self):
        assert _clean_description("  hello  ") == "hello"

    def test_collapses_internal_spaces(self):
        assert _clean_description("ZELLE   PAYMENT   FROM   CLIENT") == "ZELLE PAYMENT FROM CLIENT"

    def test_tabs_and_newlines(self):
        assert _clean_description("line1\tline2\nline3") == "line1 line2 line3"

    def test_unicode_preserved(self):
        assert _clean_description("Café del Sol") == "Café del Sol"


# ====================================================================
# compute_row_hash
# ====================================================================

class TestComputeRowHash:
    def test_deterministic(self):
        h1 = compute_row_hash("2026-05-01", -50.0, "TEST")
        h2 = compute_row_hash("2026-05-01", -50.0, "TEST")
        assert h1 == h2

    def test_different_inputs_different_hashes(self):
        h1 = compute_row_hash("2026-05-01", -50.0, "TEST A")
        h2 = compute_row_hash("2026-05-01", -50.0, "TEST B")
        assert h1 != h2

    def test_amount_precision(self):
        # -50 and -50.00 should produce same hash
        h1 = compute_row_hash("2026-05-01", -50, "TEST")
        h2 = compute_row_hash("2026-05-01", -50.0, "TEST")
        assert h1 == h2

    def test_returns_hex_string(self):
        h = compute_row_hash("2026-05-01", -50.0, "TEST")
        assert len(h) == 64  # SHA-256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


# ====================================================================
# parse_bofa_csv — full parser
# ====================================================================

class TestParseBofa:
    def test_basic_csv_with_header(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,ZELLE PAYMENT FROM CLIENT,500.00,12345.67\n"
            "05/02/2026,UBER EATS,-25.50,12320.17\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 2
        assert len(warnings) == 0
        assert txns[0]["txn_date"] == "2026-05-01"
        assert txns[0]["description"] == "ZELLE PAYMENT FROM CLIENT"
        assert txns[0]["amount"] == 500.0
        assert txns[0]["balance"] == 12345.67
        assert txns[1]["amount"] == -25.5

    def test_csv_without_header(self):
        csv_text = (
            "05/01/2026,ZELLE PAYMENT FROM CLIENT,500.00,12345.67\n"
            "05/02/2026,UBER EATS,-25.50,12320.17\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 2

    def test_empty_csv(self):
        txns, warnings = parse_bofa_csv("")
        assert len(txns) == 0
        assert any("empty" in w.lower() for w in warnings)

    def test_empty_rows_skipped(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "\n"
            "05/01/2026,Valid Transaction,100.00,5000.00\n"
            ",,\n"
            "05/02/2026,Another Transaction,-50.00,4950.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 2

    def test_malformed_date_warning(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "bad-date,SOME VENDOR,-10.00,1000.00\n"
            "05/01/2026,GOOD VENDOR,-20.00,980.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert len(warnings) == 1
        assert "invalid date" in warnings[0].lower()

    def test_malformed_amount_warning(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,SOME VENDOR,NOT_A_NUMBER,1000.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 0
        assert len(warnings) == 1
        assert "invalid amount" in warnings[0].lower()

    def test_empty_description_warning(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,,-10.00,1000.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 0
        assert len(warnings) == 1
        assert "empty description" in warnings[0].lower()

    def test_too_few_columns_warning(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,VENDOR\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 0
        assert len(warnings) == 1
        assert "too few columns" in warnings[0].lower()

    def test_no_balance_column(self):
        """BofA sometimes exports 3 columns without Running Bal."""
        csv_text = (
            "Date,Description,Amount\n"
            "05/01/2026,DEPOSIT,1000.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert txns[0]["balance"] is None

    def test_unicode_description(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,Café del Sol — lunch,-15.00,985.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert "Café" in txns[0]["description"]

    def test_bytes_input_utf8(self):
        csv_bytes = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,TEST,100.00,5000.00\n"
        ).encode("utf-8")
        txns, warnings = parse_bofa_csv(csv_bytes)
        assert len(txns) == 1

    def test_bytes_input_utf8_bom(self):
        csv_bytes = (
            "﻿Date,Description,Amount,Running Bal.\n"
            "05/01/2026,TEST,100.00,5000.00\n"
        ).encode("utf-8-sig")
        txns, warnings = parse_bofa_csv(csv_bytes)
        assert len(txns) == 1

    def test_bytes_input_latin1(self):
        csv_bytes = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,Café,-10.00,990.00\n"
        ).encode("latin-1")
        txns, warnings = parse_bofa_csv(csv_bytes)
        assert len(txns) == 1

    def test_file_like_input(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,TEST,100.00,5000.00\n"
        )
        file_obj = io.StringIO(csv_text)
        txns, warnings = parse_bofa_csv(file_obj)
        assert len(txns) == 1

    def test_external_id_populated(self):
        csv_text = (
            "05/01/2026,TEST,100.00,5000.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert "external_id" in txns[0]
        assert len(txns[0]["external_id"]) == 64

    def test_commas_in_amounts(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            '05/01/2026,BIG DEPOSIT,"1,234.56","12,345.67"\n'
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert txns[0]["amount"] == 1234.56
        assert txns[0]["balance"] == 12345.67

    def test_dollar_signs_in_amounts(self):
        csv_text = (
            "Date,Description,Amount,Running Bal.\n"
            "05/01/2026,DEPOSIT,$500.00,$5500.00\n"
        )
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1
        assert txns[0]["amount"] == 500.0

    def test_large_file_performance(self):
        """Ensure parser handles a reasonably large file without error."""
        lines = ["Date,Description,Amount,Running Bal."]
        for i in range(1000):
            day = (i % 28) + 1
            lines.append(f"05/{day:02d}/2026,TRANSACTION {i},-{i}.00,{10000 - i}.00")
        csv_text = "\n".join(lines) + "\n"
        txns, warnings = parse_bofa_csv(csv_text)
        assert len(txns) == 1000
        assert len(warnings) == 0
