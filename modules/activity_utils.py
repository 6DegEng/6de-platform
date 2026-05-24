"""Shared utilities for activity_log serialization.

Provides ``sanitize_details()`` which walks a details dict and replaces
non-finite floats (NaN, Inf, -Inf) with ``None`` before the dict is
passed to ``json.dumps()``.  This prevents the Python JSON encoder from
emitting the non-standard ``NaN`` / ``Infinity`` tokens that downstream
renderers display as literal text.

Session 3c — data-hygiene pass (2026-05-24).
"""

from __future__ import annotations

import math
from typing import Any


def _sanitize_value(v: Any) -> Any:
    """Replace non-finite floats with None; recurse into dicts and lists."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {k: _sanitize_value(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_value(item) for item in v]
    return v


def sanitize_details(details: dict | None) -> dict:
    """Return a copy of *details* with NaN/Inf floats replaced by None.

    Returns ``{}`` when *details* is None or empty — matching the existing
    ``details or {}`` pattern used throughout the codebase.
    """
    if not details:
        return {}
    return _sanitize_value(details)  # type: ignore[return-value]
