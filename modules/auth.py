"""Signed-in user identity for the 6DE platform behind Azure Easy Auth.

In production the platform runs behind **Azure App Service Authentication**
("Easy Auth") with the Microsoft (Entra ID) provider, single-tenant. Azure
validates the sign-in *before* the request reaches Streamlit and injects the
identity as HTTP headers on every authenticated request:

    X-MS-CLIENT-PRINCIPAL-NAME   the user's UPN / email
    X-MS-CLIENT-PRINCIPAL-ID     the stable object id (oid)
    X-MS-CLIENT-PRINCIPAL        base64-encoded JSON of all claims (display name)

``get_current_user()`` reads those headers and returns ``{email, name, id}``.

On localhost (``streamlit run``) Easy Auth does not exist and the headers are
absent, so it falls back to a configurable DEV user (config.DEV_AUTH_USER_*)
so local development keeps working without any Azure round-trip.

We do NOT hand-roll authentication here — Azure does the OAuth/OIDC dance and
tenant validation. This module only *reads* the result.

TODO(roles): page-level authorization (e.g. Accounting vs Bids) is not built
yet. When needed, add a role map keyed by ``email``/``id`` and a
``require_role()`` helper here. ``get_current_role()`` in streamlit_app/auth.py
currently returns None for everyone.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
from typing import Optional, TypedDict

import streamlit as st

# Easy Auth identity headers (case-insensitive in practice; we normalize).
_HEADER_NAME = "X-MS-CLIENT-PRINCIPAL-NAME"
_HEADER_ID = "X-MS-CLIENT-PRINCIPAL-ID"
_HEADER_PRINCIPAL = "X-MS-CLIENT-PRINCIPAL"

# Easy Auth endpoints, relative to the app host. The provider alias "aad" is
# App Service's default for the Microsoft/Entra provider.
LOGIN_URL = "/.auth/login/aad"
LOGOUT_URL = "/.auth/logout"

# Claim types that carry a human-friendly display name, in priority order.
_NAME_CLAIM_TYPES = (
    "name",
    "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
    "preferred_username",
    "given_name",
)


class CurrentUser(TypedDict):
    email: str
    name: str
    id: str


def _headers() -> dict:
    """Return request headers as a plain dict, or {} if unavailable.

    ``st.context.headers`` is a case-insensitive Mapping in modern Streamlit,
    but may be absent under some test/runtime contexts — never raise.
    """
    try:
        headers = st.context.headers
    except Exception:
        return {}
    if not headers:
        return {}
    try:
        return dict(headers)
    except Exception:
        return headers  # already mapping-like


def _lookup(headers: dict, key: str) -> Optional[str]:
    """Case-insensitive header lookup."""
    if not headers:
        return None
    if key in headers:
        return headers[key]
    lower = key.lower()
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == lower:
            return v
    return None


def _decode_display_name(principal_b64: str, fallback: str) -> str:
    """Extract a display name from the base64-encoded claims blob.

    The X-MS-CLIENT-PRINCIPAL header is base64 JSON shaped like
    ``{"auth_typ": "...", "claims": [{"typ": "name", "val": "Jane Doe"}, ...]}``.
    Returns ``fallback`` (typically the email) if anything is malformed.
    """
    if not principal_b64:
        return fallback
    try:
        raw = base64.b64decode(principal_b64)
        data = json.loads(raw)
    except (binascii.Error, ValueError, TypeError):
        return fallback
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return fallback
    by_type: dict = {}
    for c in claims:
        if isinstance(c, dict) and c.get("typ") and c.get("typ") not in by_type:
            by_type[c["typ"]] = c.get("val")
    for typ in _NAME_CLAIM_TYPES:
        val = by_type.get(typ)
        if val:
            return str(val)
    return fallback


def _is_local_dev(headers: dict) -> bool:
    """True when we should hand back the DEV user instead of requiring Easy Auth.

    Behind Easy Auth (302-redirect mode) an unauthenticated request never
    reaches this code, so a request that *does* reach us without the principal
    header is either (a) local dev, or (b) an explicit override. On Azure App
    Service, WEBSITE_HOSTNAME is always set; locally it is not.
    """
    try:
        from config import FORCE_DEV_AUTH
        if FORCE_DEV_AUTH:
            return True
    except Exception:
        pass
    return not os.environ.get("WEBSITE_HOSTNAME")


def _dev_user() -> CurrentUser:
    try:
        from config import DEV_AUTH_USER_EMAIL, DEV_AUTH_USER_NAME
        email, name = DEV_AUTH_USER_EMAIL, DEV_AUTH_USER_NAME
    except Exception:
        email, name = "dev@6de.xyz", "Local Developer"
    return {"email": email, "name": name, "id": "dev-local"}


def get_current_user() -> Optional[CurrentUser]:
    """Return the signed-in user, or None if unauthenticated behind Easy Auth.

    - Behind Easy Auth: parsed from the X-MS-CLIENT-PRINCIPAL-* headers.
    - On localhost (no headers): a configurable DEV user (keeps dev working).
    - Returns None only if running on Azure but the headers are missing
      (misconfiguration) — callers should treat that as "not signed in".
    """
    headers = _headers()
    email = _lookup(headers, _HEADER_NAME)
    if email:
        oid = _lookup(headers, _HEADER_ID) or ""
        principal = _lookup(headers, _HEADER_PRINCIPAL) or ""
        name = _decode_display_name(principal, fallback=email)
        return {"email": email, "name": name, "id": oid}

    if _is_local_dev(headers):
        return _dev_user()

    return None
