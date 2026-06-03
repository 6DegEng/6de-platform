"""Bank of America CSV parser and transaction importer.

Phase 0 of the bank integration: parses BofA CSV exports and writes
transactions to the platform database with auto-categorization.

BofA CSV format (as of 2026):
    Date,Description,Amount,Running Bal.
    05/01/2026,ZELLE PAYMENT FROM CLIENT,-500.00,12345.67

Some exports omit the header row entirely.  The parser detects this by
checking whether the first field of the first row parses as a date.
"""
from __future__ import annotations

import csv
import hashlib
import io
import sqlite3
from datetime import datetime
from typing import BinaryIO, Optional

from modules.accounting.categorization import categorize_transaction


# ---------------------------------------------------------------------------
# CSV parsing
# ---------------------------------------------------------------------------

# Known BofA header variations (case-insensitive first-field check)
_HEADER_MARKERS = {"date", "posted date", "transaction date"}


def _parse_date(raw: str) -> Optional[str]:
    """Parse MM/DD/YYYY or M/D/YYYY to YYYY-MM-DD.  Returns None on failure."""
    raw = raw.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_amount(raw: str) -> Optional[float]:
    """Parse a dollar amount string, stripping commas and whitespace."""
    raw = raw.strip().replace(",", "").replace("$", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _clean_description(raw: str) -> str:
    """Normalize description text: strip, collapse whitespace."""
    return " ".join(raw.split())


def compute_row_hash(txn_date: str, amount: float, description: str) -> str:
    """SHA-256 hash of date|amount|description for dedup as external_id."""
    payload = f"{txn_date}|{amount:.2f}|{description}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_bofa_csv(
    file_content: str | bytes | BinaryIO,
) -> tuple[list[dict], list[str]]:
    """Parse a Bank of America CSV export.

    Parameters
    ----------
    file_content : str, bytes, or file-like
        The CSV data.  Accepts raw string content, bytes (decoded as
        UTF-8 with fallback to latin-1), or a file-like object (e.g.
        Streamlit ``UploadedFile``).

    Returns
    -------
    (transactions, warnings) : tuple
        ``transactions`` is a list of dicts with keys:
            txn_date, description, amount, balance, external_id
        ``warnings`` is a list of human-readable warning strings for
        rows that could not be parsed.
    """
    # --- Normalise input to a string ---
    if hasattr(file_content, "read"):
        raw_bytes = file_content.read()
        if isinstance(raw_bytes, str):
            text = raw_bytes
        else:
            try:
                text = raw_bytes.decode("utf-8-sig")  # handles BOM
            except UnicodeDecodeError:
                text = raw_bytes.decode("latin-1")
    elif isinstance(file_content, bytes):
        try:
            text = file_content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = file_content.decode("latin-1")
    else:
        text = file_content

    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    if not rows:
        return [], ["CSV file is empty."]

    transactions: list[dict] = []
    warnings: list[str] = []

    start_idx = 0
    # Detect header row
    first_field = rows[0][0].strip().lower() if rows[0] else ""
    if first_field in _HEADER_MARKERS or not _parse_date(rows[0][0] if rows[0] else ""):
        start_idx = 1

    for i, row in enumerate(rows[start_idx:], start=start_idx + 1):
        # Skip empty rows
        if not row or all(cell.strip() == "" for cell in row):
            continue

        # BofA CSV has 4 columns: Date, Description, Amount, Running Bal.
        if len(row) < 3:
            warnings.append(f"Row {i}: too few columns ({len(row)}), skipped.")
            continue

        txn_date = _parse_date(row[0])
        if txn_date is None:
            warnings.append(f"Row {i}: invalid date '{row[0].strip()}', skipped.")
            continue

        description = _clean_description(row[1])
        if not description:
            warnings.append(f"Row {i}: empty description, skipped.")
            continue

        amount = _parse_amount(row[2])
        if amount is None:
            warnings.append(f"Row {i}: invalid amount '{row[2].strip()}', skipped.")
            continue

        # Running balance is optional (column index 3)
        balance = _parse_amount(row[3]) if len(row) > 3 else None

        ext_id = compute_row_hash(txn_date, amount, description)

        transactions.append({
            "txn_date": txn_date,
            "description": description,
            "amount": amount,
            "balance": balance,
            "external_id": ext_id,
        })

    return transactions, warnings


# ---------------------------------------------------------------------------
# Categorization pass
# ---------------------------------------------------------------------------

def categorize(
    transactions: list[dict],
    conn: sqlite3.Connection,
) -> list[dict]:
    """Run each transaction through the categorization rules engine.

    Mutates and returns the same list with added keys:
        expense_category, auto_categorized, needs_review
    """
    for txn in transactions:
        category = categorize_transaction(conn, txn["description"])
        if category:
            txn["expense_category"] = category
            txn["auto_categorized"] = 1
            txn["needs_review"] = 0
        else:
            txn["expense_category"] = None
            txn["auto_categorized"] = 0
            txn["needs_review"] = 1
    return transactions


# ---------------------------------------------------------------------------
# Database commit
# ---------------------------------------------------------------------------

def commit_transactions(
    conn: sqlite3.Connection,
    transactions: list[dict],
    sync_run_id: int,
    bank_connection_id: int,
) -> tuple[int, int]:
    """Write parsed transactions to the database.

    Uses INSERT OR IGNORE to skip duplicates (keyed on the existing
    UNIQUE constraint: txn_date, amount, description).

    Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0

    # Display label for the account column, e.g. "Bank of America ...1234".
    # Resolved once from the bank_connections row (not the bare connection id).
    account_label = _get_account_label(conn, bank_connection_id)

    for txn in transactions:
        account_type = "Debit" if txn["amount"] < 0 else "Credit"
        month_val = int(txn["txn_date"].split("-")[1])

        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions "
            "(txn_date, account, account_type, description, amount, balance, "
            " expense_category, month, source, external_id, "
            " bank_connection_id, auto_categorized, needs_review, sync_run_id, "
            " imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'csv', ?, ?, ?, ?, ?, datetime('now'))",
            (
                txn["txn_date"],
                account_label,
                account_type,
                txn["description"],
                txn["amount"],
                txn.get("balance"),
                txn.get("expense_category"),
                month_val,
                txn["external_id"],
                bank_connection_id,
                txn.get("auto_categorized", 0),
                txn.get("needs_review", 1),
                sync_run_id,
            ),
        )
        if cur.rowcount > 0:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    return inserted, skipped


def _get_account_label(conn: sqlite3.Connection, bank_connection_id: int) -> str:
    """Build display label from bank_connections row."""
    row = conn.execute(
        "SELECT institution_name, account_mask FROM bank_connections WHERE id = ?",
        (bank_connection_id,),
    ).fetchone()
    if row:
        name = row["institution_name"] or "Bank"
        mask = row["account_mask"] or "????"
        return f"{name} ...{mask}"
    return f"Bank Connection #{bank_connection_id}"


def create_sync_run(
    conn: sqlite3.Connection,
    bank_connection_id: int,
    file_name: str | None = None,
) -> int:
    """Create a new sync_runs row and return its id."""
    cur = conn.execute(
        "INSERT INTO sync_runs (bank_connection_id, file_name) VALUES (?, ?)",
        (bank_connection_id, file_name),
    )
    conn.commit()
    return cur.lastrowid


def complete_sync_run(
    conn: sqlite3.Connection,
    sync_run_id: int,
    added: int,
    updated: int,
    error: str | None = None,
) -> None:
    """Mark a sync run as completed."""
    conn.execute(
        "UPDATE sync_runs SET completed_at = datetime('now'), "
        "transactions_added = ?, transactions_updated = ?, error_message = ? "
        "WHERE id = ?",
        (added, updated, error, sync_run_id),
    )
    conn.commit()


def get_or_create_bank_connection(
    conn: sqlite3.Connection,
    institution_name: str = "Bank of America",
    account_mask: str = "",
    account_type: str = "checking",
) -> int:
    """Find or create a bank_connections row. Returns the id."""
    row = conn.execute(
        "SELECT id FROM bank_connections "
        "WHERE institution_name = ? AND account_mask = ? AND source = 'csv'",
        (institution_name, account_mask),
    ).fetchone()
    if row:
        return row["id"]

    cur = conn.execute(
        "INSERT INTO bank_connections (source, institution_name, account_mask, account_type) "
        "VALUES ('csv', ?, ?, ?)",
        (institution_name, account_mask, account_type),
    )
    conn.commit()
    return cur.lastrowid


def get_sync_history(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Return recent sync runs for display."""
    rows = conn.execute(
        "SELECT sr.*, bc.institution_name, bc.account_mask "
        "FROM sync_runs sr "
        "LEFT JOIN bank_connections bc ON bc.id = sr.bank_connection_id "
        "ORDER BY sr.started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
