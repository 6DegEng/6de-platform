"""Human-readable activity log formatter for the Home dashboard.

Converts raw ``activity_log`` rows into English one-liners suitable for
the Recent Activity feed on the Home page.  Unlike the per-project
``modules.projects.activity.summarize_activity`` (which only handles
``project`` and ``milestone`` entity types), this formatter covers
**every** entity type that writes to the ``activity_log`` table:

    project, milestone, invoice, permit, calc_link, opportunity,
    client, bid, document, time_entry, expense, employee,
    subconsultant, purchase_order

Session 3c -- data-hygiene pass (2026-05-24).
"""

from __future__ import annotations

import json
from typing import Any


def _parse_details(raw: Any) -> dict:
    """Defensively parse the ``details`` column into a dict."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        decoded = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _fmt_value(key: str, value: Any) -> str:
    """Format a single detail value for display."""
    if value is None:
        return "cleared"
    if isinstance(value, float):
        if key in ("amount", "estimated_value", "contract_value",
                    "paid_amount", "outstanding_balance"):
            return f"${value:,.2f}"
        return str(value)
    return str(value)


def _meaningful_keys(details: dict) -> dict:
    """Strip auto-generated bookkeeping keys from the details dict."""
    skip = {"updated_at", "created_at", "linked_at"}
    return {k: v for k, v in details.items() if k not in skip}


def _summarize_changes(details: dict, entity_label: str) -> str:
    """Summarize an 'updated' action into a readable string."""
    meaningful = _meaningful_keys(details)
    if not meaningful:
        return f"{entity_label} touched (no field changes)"

    if "status" in meaningful:
        status = str(meaningful["status"]).replace("_", " ").title()
        return f"{entity_label} status changed to {status}"

    if len(meaningful) == 1:
        key, val = next(iter(meaningful.items()))
        label = key.replace("_", " ")
        return f"{entity_label} {label} updated to {_fmt_value(key, val)}"

    keys = ", ".join(k.replace("_", " ") for k in sorted(meaningful.keys()))
    return f"{entity_label} updated: {keys}"


# ---------------------------------------------------------------------------
# Entity-specific formatters
# ---------------------------------------------------------------------------

def _project_fmt(action: str, entity_id: int, details: dict) -> str:
    label = f"Project #{entity_id}"
    if action == "created":
        name = details.get("name")
        if details.get("source") == "opportunity":
            opp_id = details.get("opportunity_id", "?")
            return f"{label} converted from opportunity #{opp_id}"
        if name:
            return f"{label} created: {name}"
        return f"{label} created"
    if action == "updated":
        return _summarize_changes(details, label)
    if action == "deleted":
        return f"{label} deleted"
    return f"{label}: {action.replace('_', ' ')}"


def _invoice_fmt(action: str, entity_id: int, details: dict) -> str:
    inv_num = details.get("invoice_number", f"#{entity_id}")
    label = f"Invoice {inv_num}"
    if action == "created":
        return f"{label} created"
    if action == "updated":
        return _summarize_changes(details, label)
    if action in ("sent", "paid", "voided"):
        return f"{label} marked {action}"
    return f"{label}: {action.replace('_', ' ')}"


def _permit_fmt(action: str, entity_id: int, details: dict) -> str:
    permit_num = details.get("permit_number", f"#{entity_id}")
    label = f"Permit {permit_num}"
    if action == "created":
        return f"{label} created"
    if action == "updated":
        return _summarize_changes(details, label)
    return f"{label}: {action.replace('_', ' ')}"


def _calc_link_fmt(action: str, entity_id: int, details: dict) -> str:
    calc_id = details.get("calc_project_id", "?")
    erp_id = details.get("erp_project_id", "?")
    label = f"Calc link #{entity_id}"
    if action == "created":
        return f"{label}: calc #{calc_id} linked to project #{erp_id}"
    if action == "updated":
        return _summarize_changes(details, label)
    return f"{label}: {action.replace('_', ' ')}"


def _opportunity_fmt(action: str, entity_id: int, details: dict) -> str:
    label = f"Opportunity #{entity_id}"
    name = details.get("name")
    if name:
        label = f"Opportunity \"{name}\""
    if action == "created":
        return f"{label} created"
    if action == "updated":
        return _summarize_changes(details, label)
    if action == "stage_change":
        old = details.get("old_stage", "?").replace("_", " ").title()
        new = details.get("new_stage", "?").replace("_", " ").title()
        return f"{label} moved from {old} to {new}"
    if action == "converted_to_project":
        pid = details.get("project_id", "?")
        return f"{label} converted to project #{pid}"
    return f"{label}: {action.replace('_', ' ')}"


def _milestone_fmt(action: str, entity_id: int, details: dict) -> str:
    label = f"Milestone #{entity_id}"
    name = details.get("name")
    if name:
        label = f"Milestone \"{name}\""
    if action == "created":
        return f"{label} added"
    if action == "updated":
        if "done" in details:
            return f"{label} completed" if details["done"] == 1 else f"{label} reopened"
        if "status" in details:
            s = details["status"]
            if s == "completed":
                return f"{label} completed"
            return f"{label} status: {s.replace('_', ' ').title()}"
        return _summarize_changes(details, label)
    return f"{label}: {action.replace('_', ' ')}"


def _client_fmt(action: str, entity_id: int, details: dict) -> str:
    name = details.get("name")
    label = f"Client \"{name}\"" if name else f"Client #{entity_id}"
    if action == "created":
        return f"{label} added"
    if action == "updated":
        return _summarize_changes(details, label)
    return f"{label}: {action.replace('_', ' ')}"


def _bid_fmt(action: str, entity_id: int, details: dict) -> str:
    title = details.get("title")
    label = f"Bid \"{title}\"" if title else f"Bid #{entity_id}"
    if action == "created":
        return f"{label} added"
    if action == "updated":
        return _summarize_changes(details, label)
    return f"{label}: {action.replace('_', ' ')}"


def _document_fmt(action: str, entity_id: int, details: dict) -> str:
    fname = details.get("file_name", f"#{entity_id}")
    label = f"Document \"{fname}\""
    if action == "created" or action == "linked":
        return f"{label} linked"
    if action == "deleted":
        return f"{label} removed"
    return f"{label}: {action.replace('_', ' ')}"


def _generic_fmt(entity_type: str, action: str, entity_id: int, details: dict) -> str:
    """Fallback for unknown entity types."""
    label = f"{entity_type.replace('_', ' ').title()} #{entity_id}"
    if action == "created":
        return f"{label} created"
    if action == "updated":
        return _summarize_changes(details, label)
    if action == "deleted":
        return f"{label} deleted"
    return f"{label}: {action.replace('_', ' ')}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_FORMATTERS = {
    "project": _project_fmt,
    "invoice": _invoice_fmt,
    "permit": _permit_fmt,
    "calc_link": _calc_link_fmt,
    "opportunity": _opportunity_fmt,
    "milestone": _milestone_fmt,
    "client": _client_fmt,
    "bid": _bid_fmt,
    "document": _document_fmt,
}


def format_activity(entry: dict) -> str:
    """Convert an activity_log row (as dict) to a human-readable one-liner.

    *entry* must have keys: ``entity_type``, ``entity_id``, ``action``,
    and optionally ``details`` (JSON string or dict).

    Returns a plain-text string with no HTML.
    """
    entity_type = (entry.get("entity_type") or "").strip()
    action = (entry.get("action") or "").strip()
    entity_id = entry.get("entity_id", 0)
    details = _parse_details(entry.get("details"))

    formatter = _FORMATTERS.get(entity_type)
    if formatter:
        return formatter(action, entity_id, details)
    return _generic_fmt(entity_type, action, entity_id, details)
