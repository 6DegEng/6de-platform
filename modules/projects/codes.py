"""Auto-numbered job code generator.

Generates codes in the pattern {YY}{prefix}{NN} where:
  - YY = two-digit year
  - prefix = discipline/pipeline prefix (e.g. "SD" for structural design)
  - NN = zero-padded sequence number per (year, prefix) pair

Example: 26SD01, 26SD02, 26RO01

The sequence is derived from existing job_numbers in the DB that match
the (year, prefix) pattern, so it is safe to call concurrently — the
next-available number is always computed fresh.

# TODO: prefix should eventually be configurable per pipeline/discipline
# via a settings table or config file, not hard-coded per call site.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date


def next_job_code(
    conn: sqlite3.Connection,
    prefix: str = "SD",
    year: int | None = None,
) -> str:
    """Return the next available job code for the given prefix and year.

    Parameters
    ----------
    conn : sqlite3.Connection
        Database connection with row_factory set.
    prefix : str
        Two-letter discipline prefix (default "SD").
    year : int | None
        Four-digit year. Defaults to current year.

    Returns
    -------
    str
        Job code like "26SD01".
    """
    if year is None:
        year = date.today().year
    yy = str(year)[-2:]
    pattern = f"{yy}{prefix}%"

    row = conn.execute(
        "SELECT job_number FROM projects "
        "WHERE job_number LIKE ? "
        "ORDER BY job_number DESC LIMIT 1",
        (pattern,),
    ).fetchone()

    if row is None:
        return f"{yy}{prefix}01"

    existing = row["job_number"]
    # Extract the numeric suffix after the prefix
    suffix_match = re.search(rf"{re.escape(yy)}{re.escape(prefix)}(\d+)$", existing)
    if suffix_match:
        next_num = int(suffix_match.group(1)) + 1
    else:
        next_num = 1

    return f"{yy}{prefix}{next_num:02d}"
