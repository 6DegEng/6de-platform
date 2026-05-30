"""QuickBooks Online invoice export (Phase 0 — CSV, credential-free).

First slice of the QuickBooks integration on the roadmap
(``docs/roadmap/integrations.md`` #1). This module is a **pure data
transform**: given the platform's SQLite connection, it serializes finalized
invoices into the column layout QuickBooks Online accepts for its CSV invoice
import. No QBO API, OAuth, or network access is involved — that's a later
slice. The export is gated behind the ``ENABLE_QBO_EXPORT`` feature flag
(see ``config.py``); the flag guards UI exposure, while the functions here are
always safe to call directly (e.g. from tests or a one-off script).

QBO's invoice CSV import is *one row per line item*, with the invoice-level
fields (number, customer, dates, memo) repeated on each row. An invoice with
no line items still exports as a single summary row carrying the invoice
total, so fixed-fee invoices created without an itemized breakdown are not
dropped.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from collections.abc import Iterable, Sequence

# QuickBooks Online invoice-import column order (one row per line item).
QBO_CSV_COLUMNS: tuple[str, ...] = (
    "InvoiceNo",
    "Customer",
    "InvoiceDate",
    "DueDate",
    "Item",
    "ItemDescription",
    "ItemQuantity",
    "ItemRate",
    "ItemAmount",
    "Memo",
)

# Map the platform's invoice_line_items.line_type to a QBO product/service item.
_LINE_TYPE_TO_QBO_ITEM: dict[str, str] = {
    "time": "Engineering Services",
    "fixed_fee": "Engineering Services",
    "expense": "Reimbursable Expenses",
    "adjustment": "Adjustment",
}
_DEFAULT_QBO_ITEM = "Engineering Services"

# Invoice statuses that represent a finalized, exportable invoice. Drafts and
# voids are intentionally excluded.
DEFAULT_EXPORT_STATUSES: tuple[str, ...] = ("sent", "paid", "overdue")


def _money(value: float | int | None) -> str:
    """Format a monetary value as a plain 2-decimal string (no symbols)."""
    return f"{float(value or 0):.2f}"


def _qty(value: float | int | None) -> str:
    """Format a quantity, dropping a trailing .0 for whole numbers."""
    num = float(value if value is not None else 1)
    return str(int(num)) if num.is_integer() else f"{num:g}"


def _customer_name(row: sqlite3.Row) -> str:
    """Resolve a QBO customer name from joined client/project columns.

    Prefers the client's company, then the client's contact name, then falls
    back to a project label so an invoice with no linked client still exports
    with a meaningful customer.
    """
    company = (row["client_company"] or "").strip() if "client_company" in row.keys() else ""
    if company:
        return company
    name = (row["client_name"] or "").strip() if "client_name" in row.keys() else ""
    if name:
        return name
    job = (row["job_number"] or "").strip() if "job_number" in row.keys() else ""
    proj = (row["project_name"] or "").strip() if "project_name" in row.keys() else ""
    label = " - ".join(p for p in (job, proj) if p)
    return label or "Unknown Customer"


def fetch_exportable_invoices(
    conn: sqlite3.Connection,
    statuses: Sequence[str] = DEFAULT_EXPORT_STATUSES,
    invoice_ids: Iterable[int] | None = None,
) -> list[sqlite3.Row]:
    """Return invoice header rows eligible for export, with client/project joins.

    Filters to *statuses* (default: finalized invoices) and, if *invoice_ids*
    is given, restricts to those ids. Ordered by invoice number for stable,
    diff-friendly output.
    """
    sql = (
        "SELECT i.id, i.invoice_number, i.description, i.amount, i.status, "
        "       i.issue_date, i.due_date, "
        "       p.job_number, p.name AS project_name, "
        "       c.name AS client_name, c.company AS client_company "
        "FROM invoices i "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "LEFT JOIN clients c ON c.id = p.client_id "
        "WHERE i.status IN (%s)" % ",".join("?" for _ in statuses)
    )
    params: list[object] = list(statuses)
    ids = None if invoice_ids is None else list(invoice_ids)
    if ids is not None:
        if not ids:
            return []
        sql += " AND i.id IN (%s)" % ",".join("?" for _ in ids)
        params.extend(ids)
    sql += " ORDER BY i.invoice_number"
    return conn.execute(sql, params).fetchall()


def _invoice_rows(conn: sqlite3.Connection, inv: sqlite3.Row) -> list[dict[str, str]]:
    """Build the per-line-item QBO rows for a single invoice header row."""
    customer = _customer_name(inv)
    memo_parts = [str(inv["description"])] if inv["description"] else []
    if inv["job_number"]:
        memo_parts.append(f"Job {inv['job_number']}")
    memo = " | ".join(memo_parts)

    base = {
        "InvoiceNo": inv["invoice_number"],
        "Customer": customer,
        "InvoiceDate": inv["issue_date"] or "",
        "DueDate": inv["due_date"] or "",
        "Memo": memo,
    }

    line_items = conn.execute(
        "SELECT line_type, description, quantity, unit_rate, amount "
        "FROM invoice_line_items WHERE invoice_id = ? ORDER BY sort_order, id",
        (inv["id"],),
    ).fetchall()

    if not line_items:
        # No itemized breakdown — emit a single summary row at the invoice total.
        return [
            {
                **base,
                "Item": _DEFAULT_QBO_ITEM,
                "ItemDescription": inv["description"] or "Professional engineering services",
                "ItemQuantity": "1",
                "ItemRate": _money(inv["amount"]),
                "ItemAmount": _money(inv["amount"]),
            }
        ]

    rows: list[dict[str, str]] = []
    for li in line_items:
        item = _LINE_TYPE_TO_QBO_ITEM.get(li["line_type"], _DEFAULT_QBO_ITEM)
        rows.append(
            {
                **base,
                "Item": item,
                "ItemDescription": li["description"] or item,
                "ItemQuantity": _qty(li["quantity"]),
                "ItemRate": _money(li["unit_rate"]),
                "ItemAmount": _money(li["amount"]),
            }
        )
    return rows


def export_invoices_to_qbo_csv(
    conn: sqlite3.Connection,
    statuses: Sequence[str] = DEFAULT_EXPORT_STATUSES,
    invoice_ids: Iterable[int] | None = None,
) -> str:
    """Serialize finalized invoices to a QuickBooks Online import CSV string.

    Returns CSV text (header row always present). One row per line item;
    invoices without line items produce a single summary row. Read-only — does
    not mutate the database.
    """
    invoices = fetch_exportable_invoices(conn, statuses=statuses, invoice_ids=invoice_ids)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=QBO_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for inv in invoices:
        for row in _invoice_rows(conn, inv):
            writer.writerow(row)
    return buf.getvalue()
