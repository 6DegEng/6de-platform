"""Transaction Categorization Rules Engine.

Ports the VBA macro pattern-matching logic into a Python/SQLite rules engine
that can auto-categorize bank transactions by description.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Optional

# ---------------------------------------------------------------------------
# Default rules extracted from the VBA macro (Categorization VBA Script_03012026.txt).
# Each tuple is (pattern_regex, category, priority).
# Lower priority number = matched first.  Rules within the same priority
# block are evaluated in insertion order.
# ---------------------------------------------------------------------------
_VBA_RULES: list[tuple[str, str, int]] = [
    # --- TRANSFERS, OWNER DRAWS & CONTRIBUTIONS (priority 10) ---
    (r"atm|withdrawal", "Owner Draws/Distributions", 10),
    (r"online banking transfer from chk 6485", "Owner Draws/Distributions", 10),
    (r"online banking transfer from chk 6402", "Owner Contributions", 10),

    # --- CREDIT PAYMENTS (priority 15) ---
    (r"online banking payment to crd 6010", "Credit Card - Personal", 15),
    (r"online banking payment to crd 6310", "Credit Card - Corporate", 15),
    (r"paypal", "Credit Card - Paypal", 15),
    (r"synchrony", "Credit Card - Synchrony", 15),

    # --- REVENUE & TRANSFERS (priority 20) ---
    (r"zelle payment from vitoria cavalcanti", "Real Estate Rental Revenue", 20),
    (r"zelle payment from", "Engineering Revenue", 21),
    (r"bkofamerica mobile|deposit", "Engineering Revenue", 22),

    # --- BANK FEES (priority 30) ---
    (r"monthly maintenance fee|monthly fee business adv relationship", "Bank Fees", 30),

    # --- SUBCONTRACTORS (priority 35) ---
    # Note: "zelle payment to" must come after "zelle payment from" rules
    (r"zelle payment to|fiverr|paypal.*fiverr", "Engineering Subcontractors", 35),

    # --- MEALS & ENTERTAINMENT (priority 40) ---
    (
        r"uber eats|burger king|mcdonald|wendys|china express|panera bread|"
        r"hooters|taco bell|carrabbas|phat boy sushi|rock n roll ribs|sumo japanese|"
        r"antojitos|pasquales|tst|pasquale|sushiko|jimmy johns|flanigans|atlantic vending|"
        r"chilis|bar louie|lifebox|kona ice|dunkin|bakery|ihop|hotdog|"
        r"steam|starz|youtube|tinder|hard rock|cinema|regal|silver spot|"
        r"meetup|vending|chao|cafe|coffee|pizza|pita|wings|"
        r"tacos|sushi|grocery|food truck|restaurant|amazon digi|voodoo doughnut|"
        r"angel studios|kfc|eats",
        "Meals & Entertainment",
        40,
    ),

    # --- TRAVEL & TRANSPORTATION (priority 45) ---
    (r"uber technolog|lyft", "Travel and Transportation (Other)", 45),

    # --- SOFTWARE SUBSCRIPTIONS (priority 50) ---
    (
        r"microsoft|quickbooks|intuit|chatgpt|openai|monday\.com|"
        r"bittitan|turbotax|gsuite|paypal.*google|jamsoftwa|software|"
        r"autodesk|autocad|revit|civil 3d|meccawind|bluebeam|"
        r"dropbox|box\.com|msbill\.info",
        "Software Subscriptions",
        50,
    ),

    # --- UTILITIES (priority 55) ---
    (r"google fi|xfinity|comcast|verizon|fpl|electric|utilities", "Utilities", 55),

    # --- INSURANCE (priority 60) ---
    (r"aetna|insurance|cvs hlth|progressive|prog american", "Insurance Expenses", 60),

    # --- WEBSITE HOSTING (priority 65) ---
    (r"godaddy|hosting|domain", "Website Hosting & Development", 65),

    # --- OFFICE EQUIPMENT (priority 70) ---
    (r"best buy|bestbuy|amazon\.com", "Office Equipment", 70),

    # --- OFFICE SUPPLIES (priority 75) ---
    (r"office supplies|stationery|envelopes|pe stamps|staples|office depot", "Office Supplies", 75),

    # --- OFFICE GROCERIES (priority 80) ---
    (
        r"publix|walmart|walgreens|target|super m|seabra|"
        r"bath and body|handy food|winndixie|aldi|whole foods|sedano.s|"
        r"presidente|fresco y m.s|bravo supermarket|sav-a-lot|trader joe.s",
        "Office Groceries",
        80,
    ),

    # --- FUEL AND GAS (priority 85) ---
    (
        r"exxon|chevron|shell|sunoco|wawa|bp|costco|7-eleven|"
        r"marathon|racetrac|bird road stat|gas|petro|k20 oil|fuel|"
        r"valero|mobil|speedway|citgo|circle k",
        "Fuel and Gas",
        85,
    ),

    # --- MORTGAGE (priority 90) ---
    (r"freedom|mortgage|crystal lake|acct integrators", "Mortgage - CL3930", 90),

    # --- VEHICLE LOANS (priority 92) ---
    (r"gte financial|loan|vehicle", "Vehicle Loans", 92),

    # --- VEHICLE MAINTENANCE (priority 94) ---
    (r"autozone|oil connection|advance auto", "Vehicle Maintenance & Repairs", 94),

    # --- ADVERTISING (priority 96) ---
    (r"vistaprint|facebook ads|google ads|instagram|linkedin ads", "Advertising & Marketing", 96),

    # --- CONTINUING EDUCATION (priority 98) ---
    (r"udemy|pdh academy|audible|vue|testing", "Continuing Education", 98),

    # --- TOLLS (priority 100) ---
    (r"sunpass|epass|toll", "Tolls", 100),

    # --- PARKING FEES (priority 102) ---
    (r"parkmobile|verrus|paybyphone|pioneer park|asta parking|coh|mb-parking parkmo", "Parking Fees", 102),

    # --- PERMITTING (priority 104) ---
    (
        r"city clerk|lauderdale lak|public record|hialeah|miami gardens|doral|"
        r"pembroke pines|miramar|fort lauderdale|weston|hollywood|coral springs|"
        r"plantation|tamarac|sunrise|aventura|sweetwater|margate|"
        r"parkland|hallandale|north miami|cooper city|cutler bay|homestead",
        "Permitting & City Fees",
        104,
    ),

    # --- UNIFORMS (priority 106) ---
    (
        r"nike|foot locker|burlington|journeys|macys|cubavera|"
        r"pacsun|marshall|tj maxx|forever 21|express|uniqlo|"
        r"guess|zara|gap|h&m|old navy|abercrombie|aeropostale|"
        r"american eagle|hollister",
        "Uniforms",
        106,
    ),
]


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

def categorize_transaction(conn: sqlite3.Connection, description: str) -> Optional[str]:
    """Run *description* against all active rules ordered by priority ASC.

    Returns the category of the first matching rule, or ``None`` if nothing
    matches.
    """
    if not description:
        return None

    rows = conn.execute(
        "SELECT pattern, category FROM categorization_rules "
        "WHERE is_active = 1 ORDER BY priority ASC, id ASC"
    ).fetchall()

    for row in rows:
        try:
            if re.search(row["pattern"], description, re.IGNORECASE):
                return row["category"]
        except re.error:
            # Skip rules with invalid regex
            continue

    return None


def categorize_all_uncategorized(conn: sqlite3.Connection) -> int:
    """Categorize every transaction whose expense_category is NULL or
    'Uncategorized'.

    Returns the number of rows updated.
    """
    rows = conn.execute(
        "SELECT id, description FROM transactions "
        "WHERE expense_category IS NULL "
        "   OR expense_category = '' "
        "   OR expense_category = 'Uncategorized'"
    ).fetchall()

    updated = 0
    for row in rows:
        category = categorize_transaction(conn, row["description"] or "")
        if category:
            conn.execute(
                "UPDATE transactions SET expense_category = ? WHERE id = ?",
                (category, row["id"]),
            )
            updated += 1

    if updated:
        conn.commit()

    return updated


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def seed_rules_from_vba(conn: sqlite3.Connection) -> int:
    """Insert default rules extracted from the VBA macro.

    Idempotent: uses INSERT OR IGNORE with UNIQUE constraint on pattern.
    Returns the number of rules inserted.
    """
    inserted = 0
    for pattern, category, priority in _VBA_RULES:
        cur = conn.execute(
            "INSERT OR IGNORE INTO categorization_rules "
            "(pattern, category, priority) VALUES (?, ?, ?)",
            (pattern, category, priority),
        )
        inserted += cur.rowcount

    if inserted:
        conn.commit()

    return inserted


def get_all_rules(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all categorization rules ordered by priority."""
    return conn.execute(
        "SELECT * FROM categorization_rules ORDER BY priority ASC, id ASC"
    ).fetchall()


def get_distinct_categories(conn: sqlite3.Connection) -> list[str]:
    """Return sorted list of distinct category values used in rules."""
    rows = conn.execute(
        "SELECT DISTINCT category FROM categorization_rules ORDER BY category"
    ).fetchall()
    return [r["category"] for r in rows]
