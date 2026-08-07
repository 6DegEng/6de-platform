"""Friendly handling for database failures.

Without this, any database problem renders Streamlit's default traceback —
Python internals and server file paths — to whoever is logged in. That is
what a dropped Azure Postgres connection looked like before ``db.pg_compat``
learned to reconnect: a wall of red on the dashboard.

Connection loss is now healed one layer down, so reaching this module means
something genuinely needs attention (server down, credentials expired, disk
full). Say so in words the reader can act on, keep the technical detail one
click away, and offer a retry that drops the cached connection — a handle
that has gone bad in a way the adapter can't repair would otherwise be
reused for the life of the process.
"""
from __future__ import annotations

import sqlite3

import streamlit as st

# Errors that mean "the database is unreachable or unhappy" rather than
# "this code is wrong". Everything else should keep bubbling up loudly.
DB_ERRORS = (sqlite3.Error,)

_CREDENTIALS = "The database rejected the platform's credentials."

# Ordered most-specific first: "the connection is closed" also contains
# "connection", and the generic phrasing would otherwise win.
_FRIENDLY = (
    ("closed", "The connection to the database dropped."),
    ("does not exist", "The database is reachable but a table is missing — "
                       "a migration may not have finished."),
    ("password", _CREDENTIALS),
    ("authentication", _CREDENTIALS),
    ("permission denied", _CREDENTIALS),
    ("timeout", "The database took too long to answer."),
    ("timed out", "The database took too long to answer."),
    ("connection", "The database server didn't answer."),
)


def friendly_reason(exc: BaseException) -> str:
    """One plain-English sentence for the most common failures."""
    text = str(exc).lower()
    for needle, message in _FRIENDLY:
        if needle in text:
            return message
    return "The platform couldn't read from the database."


def render_db_error(exc: BaseException, what: str = "this page") -> None:
    """Show a readable failure panel with a retry that clears caches.

    Call inside ``except DB_ERRORS`` and follow with ``st.stop()`` — the
    caller has no data to draw.
    """
    st.error(
        f"**Couldn't load {what}.** {friendly_reason(exc)}\n\n"
        "This is usually temporary. Try again in a moment — if it keeps "
        "happening, the database server needs attention."
    )

    if st.button("Try again", type="primary", key=f"db_retry_{what}"):
        # Drop cached query results *and* the cached connection: a handle
        # the adapter couldn't heal would otherwise be handed back forever.
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()

    with st.expander("Technical details"):
        st.caption("Useful when reporting the problem.")
        st.code(f"{type(exc).__name__}: {exc}", language="text")


def connect_or_explain(what: str = "this page"):
    """Open the database, or render the failure panel and halt the page.

    The one-liner every page uses in place of a bare ``ensure_db()``::

        conn = connect_or_explain("Projects")

    Returns a live connection. Never returns on failure — ``st.stop()``
    ends the script run, so callers can use the result unconditionally.
    """
    from db import ensure_db

    try:
        return ensure_db()
    except DB_ERRORS as exc:
        render_db_error(exc, what)
        st.stop()
