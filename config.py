"""Centralised path and runtime configuration for the 6DE Company Platform.

Every external path is driven by an environment variable with a sensible
default. Set the env-var to override (local dev, CI, container, production).

Environment variables (defaults shown):

    PLATFORM_DB_PATH        %LOCALAPPDATA%\\6th-degree-platform\\data\\platform.db
    DB_BACKEND              sqlite                  ("sqlite" or "postgres")
    PLATFORM_DATABASE_URL   (unset)                 used when DB_BACKEND=postgres
    AUTH_CONFIG_PATH        <project_root>/auth_config.yaml

    SIXDE_CALC_DB           OneDrive default        calc engine common.db (read-only)
    SIXDE_STRUCTURAL_DB     OneDrive default
    SIXDE_DRAINAGE_DB       OneDrive default
    SIXDE_INSPECTION_DB     OneDrive default
    SIXDE_CALC_EXE          OneDrive default        path to PyWebView calc launcher

    MSGRAPH_CLIENT_ID       (unset)                 Entra ID app registration client ID
    MSGRAPH_TENANT_ID       (unset)                 Entra ID tenant ID
    MSGRAPH_TOKEN_PATH      %LOCALAPPDATA%\\6de-platform\\graph_token.enc
    SIXDE_TOKEN_KEY         (unset)                 Fernet key for token encryption (32 url-safe base64 bytes)
    SIXDE_PROJECTS_ROOT     "06_Engineering/01_ Active Projects"   path under the
                            "Documents - 6th Degree Engineering" library where
                            per-project folders live. Leading space in segment 2
                            is intentional (B27); URL-encoded at the Graph boundary.

When MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID are both set, modules.documents.sharepoint
returns a real GraphServiceClient; otherwise it returns a StubGraphClient suitable
for offline development and tests. This lets the SharePoint code be exercised
before the Entra ID app registration is created.
"""
from __future__ import annotations

import os
from pathlib import Path

_PLATFORM_ROOT = Path(__file__).resolve().parent

# Load .env from the platform root before anything reads os.environ below.
# python-dotenv is a hard dep (requirements.txt); if it ever goes missing
# we'd rather fail loudly than silently miss MSGRAPH_* and fall back to stubs.
try:
    from dotenv import load_dotenv
    load_dotenv(_PLATFORM_ROOT / ".env")
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Database backend selection (Phase 1 seam — Phase 8 implements postgres on Azure)
# ---------------------------------------------------------------------------
DB_BACKEND = os.environ.get("DB_BACKEND", "sqlite").lower()
PLATFORM_DATABASE_URL = os.environ.get("PLATFORM_DATABASE_URL")

# ---------------------------------------------------------------------------
# Integration feature flags (off by default — opt in per-environment)
# ---------------------------------------------------------------------------
def _flag(name: str, default: bool = False) -> bool:
    """Parse a boolean env var ('1', 'true', 'yes', 'on' → True)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# QuickBooks Online invoice export (CSV). Pure data transform, no credentials.
# See modules/integrations/quickbooks.py and docs/roadmap/integrations.md.
ENABLE_QBO_EXPORT = _flag("ENABLE_QBO_EXPORT", False)

# Delivery-milestone notification email (composed only — no SMTP send here).
# See modules/integrations/delivery_email.py and docs/roadmap/integrations.md #2.
ENABLE_DELIVERY_EMAIL = _flag("ENABLE_DELIVERY_EMAIL", False)

# Slack notification on client-facing / internal project updates (composed only —
# no webhook POST here). See modules/integrations/slack.py + docs/roadmap/integrations.md #3.
ENABLE_SLACK_NOTIFY = _flag("ENABLE_SLACK_NOTIFY", False)

# ---------------------------------------------------------------------------
# Local SQLite path — OUT of OneDrive sync by default to avoid lock cascades.
# ---------------------------------------------------------------------------
def _default_db_dir() -> Path:
    """%LOCALAPPDATA%\\6th-degree-platform\\data on Windows;
    ~/.local/share/6th-degree-platform/data elsewhere."""
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "6th-degree-platform" / "data"
    return Path.home() / ".local" / "share" / "6th-degree-platform" / "data"


_DEFAULT_DB_PATH = _default_db_dir() / "platform.db"

DB_PATH = Path(os.environ.get("PLATFORM_DB_PATH", str(_DEFAULT_DB_PATH)))

# Ensure the parent directory exists. Idempotent.
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Legacy path — the SQLite file used to live next to the source code in OneDrive.
# Migration script in db/__init__.py copies from here to DB_PATH on first run.
LEGACY_DB_PATH = _PLATFORM_ROOT / "db" / "platform.db"

# Schema source (lives in the repo, not in user data)
SCHEMA_PATH = _PLATFORM_ROOT / "db" / "schema.sql"

# Back-compat alias used by older imports
DB_DIR = DB_PATH.parent

# ---------------------------------------------------------------------------
# Calc engine — read-only bridge into the structural/civil/inspection DBs
# ---------------------------------------------------------------------------
_DEFAULT_REF_DB = str(
    Path.home()
    / "OneDrive - 6th Degree Engineering"
    / "Documents - 6th Degree Engineering"
    / "06_Engineering"
    / "02_Services Library"
    / "01_Dev"
    / "02_Reference DB"
)

CALC_DB_PATH = Path(os.environ.get(
    "SIXDE_CALC_DB",
    os.path.join(_DEFAULT_REF_DB, "common.db"),
))

STRUCTURAL_DB_PATH = Path(os.environ.get(
    "SIXDE_STRUCTURAL_DB",
    os.path.join(_DEFAULT_REF_DB, "structural.db"),
))

DRAINAGE_DB_PATH = Path(os.environ.get(
    "SIXDE_DRAINAGE_DB",
    os.path.join(_DEFAULT_REF_DB, "drainage.db"),
))

INSPECTION_DB_PATH = Path(os.environ.get(
    "SIXDE_INSPECTION_DB",
    os.path.join(_DEFAULT_REF_DB, "inspection.db"),
))

CALC_EXE_PATH = Path(os.environ.get(
    "SIXDE_CALC_EXE",
    str(
        Path.home()
        / "OneDrive - 6th Degree Engineering"
        / "Documents - 6th Degree Engineering"
        / "06_Engineering"
        / "02_Services Library"
        / "01_Dev"
        / "6th Degree Calculator.exe"
    ),
))

# ---------------------------------------------------------------------------
# Auth config (OPTIONAL) — NOT required to sign in.
# ---------------------------------------------------------------------------
# Login is handled by Azure App Service Easy Auth (Entra ID) in production and
# by a DEV identity locally — see modules/auth.py. This YAML is no longer a
# login gate; it is only read, when present, for the engineer profile on calc
# cover sheets (modules/calculator/cover_sheet.py), which falls back to sane
# defaults if the file is absent. The default is a repo-relative path resolved
# with pathlib — never an absolute Windows / Git-Bash path. A *relative*
# AUTH_CONFIG_PATH override is resolved against the project root so it can't
# leak a host-specific absolute path (the old /home/secrets and
# C:/Program Files/Git/home/secrets defaults are gone).
_auth_config_override = os.environ.get("AUTH_CONFIG_PATH")
if _auth_config_override:
    _acp = Path(_auth_config_override)
    AUTH_CONFIG_PATH = _acp if _acp.is_absolute() else (_PLATFORM_ROOT / _acp)
else:
    AUTH_CONFIG_PATH = _PLATFORM_ROOT / "auth_config.yaml"

# ---------------------------------------------------------------------------
# Staff SSO (Azure App Service "Easy Auth" + Entra ID, single-tenant)
# ---------------------------------------------------------------------------
# In production the platform runs behind Easy Auth, which injects the signed-in
# user as request headers (read in modules/auth.get_current_user). Easy Auth
# does not exist on localhost, so `streamlit run` falls back to this DEV user
# (set PLATFORM_FORCE_DEV_AUTH=1 to force the fallback even on a host that looks
# like Azure). These are NOT secrets — just a local identity for development.
DEV_AUTH_USER_EMAIL = os.environ.get("DEV_AUTH_USER_EMAIL", "dev@6de.xyz")
DEV_AUTH_USER_NAME = os.environ.get("DEV_AUTH_USER_NAME", "Local Developer")
FORCE_DEV_AUTH = _flag("PLATFORM_FORCE_DEV_AUTH", False)

# ---------------------------------------------------------------------------
# Microsoft Graph / SharePoint (Phase 2)
# ---------------------------------------------------------------------------
MSGRAPH_CLIENT_ID = os.environ.get("MSGRAPH_CLIENT_ID")
MSGRAPH_TENANT_ID = os.environ.get("MSGRAPH_TENANT_ID")
SIXDE_TOKEN_KEY = os.environ.get("SIXDE_TOKEN_KEY")


def _default_graph_token_path() -> Path:
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "6de-platform" / "graph_token.enc"
    return Path.home() / ".local" / "share" / "6de-platform" / "graph_token.enc"


MSGRAPH_TOKEN_PATH = Path(os.environ.get(
    "MSGRAPH_TOKEN_PATH",
    str(_default_graph_token_path()),
))

# Per Juan 2026-05-21: leading space in "01_ Active Projects" is intentional.
# Tracked for cleanup as B27 in SESSION36_BUG_BACKLOG.md. Graph-API callers
# URL-encode this string at the boundary; do not strip or normalize it here.
SIXDE_PROJECTS_ROOT = os.environ.get(
    "SIXDE_PROJECTS_ROOT",
    "06_Engineering/01_ Active Projects",
)

# SharePoint site coordinates for Graph site/drive resolution.
# Hostname + site path together identify the target site whose default document
# library hosts the {SIXDE_PROJECTS_ROOT}/... tree. Defaults match the 6th
# Degree Engineering tenant (Juan 2026-05-21, see
# docs/specs/sharepoint_session_2c.md §11).
SIXDE_GRAPH_HOSTNAME = os.environ.get(
    "SIXDE_GRAPH_HOSTNAME",
    "6thdegreeengineering.sharepoint.com",
)
SIXDE_GRAPH_SITE_PATH = os.environ.get(
    "SIXDE_GRAPH_SITE_PATH",
    "/sites/6thDegreeEngineering",
)
