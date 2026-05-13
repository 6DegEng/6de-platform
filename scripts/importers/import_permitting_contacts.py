"""Import data from Permitting Contacts.xlsm into the platform contacts table.

Closes B6/I4 from SESSION34_BUG_BACKLOG.md — the file was named in the
Session 32 prompt but no importer was written. Once this runs, the Permits
page Contacts tab shows real data and the per-permit Inspector dropdown
can autocomplete from this list.

Per B18 consolidation: writes to the single `contacts` table. The schema's
`permit_contacts` table reference in the bug backlog turned out to be a
mis-remembering — only `contacts` exists in schema.sql.

Source workbook layout (sheet "Contact Database"):
    Row 1 = header
    Columns A-M: Region, County, Municipality, Department, Division/Section,
                 Position/Title, Contact Name, Phone, Email,
                 Online Portal URL, Notes/Comments, Last Verified, Status

Idempotency: dedup by email if present; otherwise by (name, organization).
"""
from __future__ import annotations

import sys
from pathlib import Path

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
if str(PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(PLATFORM_ROOT))

from db import ensure_db, log_activity  # noqa: E402

import openpyxl  # noqa: E402

SOURCE = (
    Path(r"C:\Users\juanc\OneDrive - 6th Degree Engineering")
    / "Documents - 6th Degree Engineering"
    / "06_Engineering"
    / "Permitting Contacts.xlsm"
)


def _classify_role(title: str | None, department: str | None) -> str:
    """Pick a role_type from the seven allowed values."""
    haystack = " ".join(filter(None, [title or "", department or ""])).lower()
    if "inspector" in haystack:
        return "inspector"
    if "attorney" in haystack or "legal" in haystack:
        return "attorney"
    if "architect" in haystack:
        return "architect"
    if "contractor" in haystack:
        return "contractor"
    if "consultant" in haystack:
        return "consultant"
    return "county_official"


def _clean(value) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _build_name(contact_name: str | None, position: str | None, org: str | None) -> str | None:
    """Use Contact Name if present, else synthesize from position+org."""
    if contact_name:
        return contact_name
    if position and org:
        return f"{position} — {org}"
    if position:
        return position
    if org:
        return f"{org} (general)"
    return None


def _build_org(municipality: str | None, department: str | None) -> str | None:
    if municipality and department:
        return f"{municipality} — {department}"
    return municipality or department


def _build_notes(
    region: str | None,
    county: str | None,
    division: str | None,
    portal_url: str | None,
    notes: str | None,
    last_verified,
    status: str | None,
) -> str | None:
    parts = []
    if region and region not in ("N/A", "n/a"):
        parts.append(f"Region: {region}")
    if county and county not in ("N/A", "n/a"):
        parts.append(f"County: {county}")
    if division:
        parts.append(f"Division: {division}")
    if portal_url:
        parts.append(f"Portal: {portal_url}")
    if notes:
        parts.append(notes)
    if last_verified:
        parts.append(f"Last verified: {last_verified}")
    if status:
        parts.append(f"Status: {status}")
    return " | ".join(parts) if parts else None


def import_contacts(conn, wb) -> dict:
    ws = wb["Contact Database"]
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    rows = ws.iter_rows(min_row=2, values_only=True)
    for raw in rows:
        # Excel cells past the last populated column come back as None; pad
        padded = list(raw) + [None] * (13 - len(raw))
        (
            region, county, municipality, department, division,
            position, contact_name, phone, email, portal_url,
            notes_raw, last_verified, status,
        ) = padded[:13]

        contact_name = _clean(contact_name)
        position = _clean(position)
        municipality = _clean(municipality)
        department = _clean(department)
        email = _clean(email)
        phone = _clean(phone)

        org = _build_org(municipality, department)
        name = _build_name(contact_name, position, org)

        if not name:
            stats["skipped"] += 1
            continue

        role = _classify_role(position, department)
        full_notes = _build_notes(
            _clean(region), _clean(county), _clean(division),
            _clean(portal_url), _clean(notes_raw), last_verified, _clean(status),
        )

        # Dedup: prefer email match; fall back to (name, organization)
        existing = None
        if email:
            existing = conn.execute(
                "SELECT id FROM contacts WHERE email = ?", (email,),
            ).fetchone()
        if existing is None:
            existing = conn.execute(
                "SELECT id FROM contacts WHERE name = ? AND COALESCE(organization,'') = COALESCE(?, '')",
                (name, org),
            ).fetchone()

        if existing:
            conn.execute(
                "UPDATE contacts SET title=?, organization=?, department=?, "
                "email=?, phone=?, role_type=?, notes=? WHERE id=?",
                (position, org, department, email, phone, role, full_notes, existing["id"]),
            )
            stats["updated"] += 1
        else:
            conn.execute(
                "INSERT INTO contacts (name, title, organization, department, "
                "email, phone, role_type, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (name, position, org, department, email, phone, role, full_notes),
            )
            stats["inserted"] += 1

    conn.commit()
    return stats


def main():
    print(f"Source: {SOURCE}")
    if not SOURCE.exists():
        print(f"ERROR: Source file not found: {SOURCE}")
        sys.exit(1)

    wb = openpyxl.load_workbook(SOURCE, data_only=True, read_only=True)
    conn = ensure_db()
    try:
        stats = import_contacts(conn, wb)
        print(f"Contacts:  {stats['inserted']} inserted, "
              f"{stats['updated']} updated, {stats['skipped']} skipped")

        log_activity(
            conn,
            entity_type="importer",
            entity_id=0,
            action="imported",
            details={
                "importer": "import_permitting_contacts",
                "source": str(SOURCE.name),
                "contacts": stats,
            },
        )
        conn.commit()
    finally:
        wb.close()
        conn.close()


if __name__ == "__main__":
    main()
