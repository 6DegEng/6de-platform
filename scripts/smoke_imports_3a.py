"""Smoke test: confirm Session 3a UI deps import cleanly.

Run with:  py -3.14 scripts/smoke_imports_3a.py
Must print "OK" on stdout. Any ImportError fails the gate.
"""

import streamlit  # noqa: F401
import st_aggrid  # noqa: F401  (PyPI: streamlit-aggrid)
import streamlit_sortables  # noqa: F401  (PyPI: streamlit-sortables — kanban DnD)
import streamlit_calendar  # noqa: F401  (PyPI: streamlit-calendar)

print("OK")
