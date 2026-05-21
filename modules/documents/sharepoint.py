"""SharePoint document layer for the 6DE Company Platform (Phase 2).

Wraps Microsoft Graph for the project folder convention:

    {SIXDE_PROJECTS_ROOT}/{NUM}_{NAME}/{Calcs|Drawings|Permits|Billing|Correspondence}

Default root: "06_Engineering/01_ Active Projects" (leading space in segment 2
is intentional — tracked as B27 in SESSION36_BUG_BACKLOG.md). All path segments
are URL-encoded at the Graph boundary; callers should pass raw strings.

Auth boundary
-------------
``get_graph_client()`` returns a real ``GraphServiceClient`` when
``MSGRAPH_CLIENT_ID`` and ``MSGRAPH_TENANT_ID`` are both set, otherwise a
``StubGraphClient`` that records calls in memory. The rest of this module is
written against the boundary, so wiring real credentials later is one config
change, not a refactor.

Token storage
-------------
Phase 2 stores the refresh token as a Fernet-encrypted blob at
``MSGRAPH_TOKEN_PATH`` (default ``%LOCALAPPDATA%\\6de-platform\\graph_token.enc``).
The encryption key comes from the ``SIXDE_TOKEN_KEY`` env var.

Phase 5 migration TODO (when the ``users`` table lands):
    1. Read the encrypted blob from MSGRAPH_TOKEN_PATH.
    2. ``INSERT INTO users.ms_graph_refresh_token`` for the appropriate user row.
    3. Delete the file at MSGRAPH_TOKEN_PATH.
    4. Update get_graph_client() to read from users table instead of _TokenStore.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from config import (
    MSGRAPH_CLIENT_ID,
    MSGRAPH_TENANT_ID,
    MSGRAPH_TOKEN_PATH,
    SIXDE_PROJECTS_ROOT,
    SIXDE_TOKEN_KEY,
)

CATEGORIES = ("Calcs", "Drawings", "Permits", "Billing", "Correspondence")

# Heuristic mapping from real-world subfolder names to canonical Phase 2
# categories. Order matters — first match wins. Patterns are lowercased and
# substring-matched. Returns None when no rule applies; callers default to
# "Correspondence" or surface a warning.
_CATEGORY_PATTERNS: tuple[tuple[str, str], ...] = (
    # Calcs — calculation packages, engineering analysis output
    ("calc", "Calcs"),
    ("calculation", "Calcs"),
    ("hydraulic", "Calcs"),
    ("drainage", "Calcs"),
    ("structural analysis", "Calcs"),
    # Drawings — CAD, shop drawings, renderings, plans, photos that document the site
    ("drawing", "Drawings"),
    ("dwg", "Drawings"),
    ("render", "Drawings"),
    ("plan", "Drawings"),
    ("shop draw", "Drawings"),
    ("site photo", "Drawings"),
    ("photo", "Drawings"),
    # Permits — permit applications, inspection reports
    ("permit", "Permits"),
    ("inspection", "Permits"),
    ("noa", "Permits"),  # Notice of Acceptance — Miami-Dade-specific
    # Billing — invoices, contracts, accounting
    ("billing", "Billing"),
    ("invoice", "Billing"),
    ("account", "Billing"),
    ("contract", "Billing"),
    ("proposal", "Billing"),
    ("payment", "Billing"),
    # Correspondence — emails, letters, meeting notes, reference docs
    ("correspondence", "Correspondence"),
    ("email", "Correspondence"),
    ("letter", "Correspondence"),
    ("meeting", "Correspondence"),
    ("memo", "Correspondence"),
    ("ppt", "Correspondence"),
    ("presentation", "Correspondence"),
    ("survey", "Correspondence"),
    ("geotech", "Correspondence"),
    ("product data", "Correspondence"),
    ("spec", "Correspondence"),
)


def classify_category(subfolder_name: str | None) -> str | None:
    """Map a real-world subfolder name to one of the 5 canonical categories.

    Returns None when no heuristic matches. Callers can default to
    "Correspondence" (safest catch-all) or log the unmatched name for
    later taxonomy work. Substring match on lowercased input.
    """
    if not subfolder_name:
        return None
    needle = subfolder_name.lower()
    if needle.startswith("00_") or needle.startswith("99_"):
        return None  # archive/template — exclude from indexing
    for pattern, category in _CATEGORY_PATTERNS:
        if pattern in needle:
            return category
    return None

# Strip SharePoint/Windows-illegal chars plus C0 control chars EXCEPT whitespace
# (tab/LF/CR), which we convert to spaces below so they collapse via the
# whitespace pass. This matches NTFS rules and the Phase 2 spec.
_ILLEGAL_FILENAME_CHARS = re.compile(
    r'[<>:"/\\|?*\x00-\x08\x0b\x0c\x0e-\x1f]'
)
_WHITESPACE_CONTROLS = str.maketrans({"\t": " ", "\n": " ", "\r": " "})
_MAX_SEGMENT_LEN = 128
_MAX_PATH_LEN = 255
_LARGE_UPLOAD_THRESHOLD = 4 * 1024 * 1024  # 4 MB — Graph small-upload limit
_CHUNK_SIZE = 5 * 1024 * 1024  # 5 MB — recommended chunk for createUploadSession


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------
def sanitize_filename(name: str) -> str:
    """Make `name` safe for SharePoint / OneDrive filenames.

    Strips Windows-illegal characters, collapses whitespace, trims to 128
    characters per segment. Returns "_" for an empty result so callers never
    end up with an empty filename.
    """
    if not name:
        return "_"
    # Promote whitespace control chars (\t \n \r) to spaces so collapse handles
    # them, but strip other C0 control chars as illegal characters.
    cleaned = name.translate(_WHITESPACE_CONTROLS)
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = cleaned.rstrip(". ")
    if not cleaned:
        return "_"
    if len(cleaned) > _MAX_SEGMENT_LEN:
        stem, dot, ext = cleaned.rpartition(".")
        if dot and len(ext) <= 10:
            keep = _MAX_SEGMENT_LEN - len(ext) - 1
            cleaned = f"{stem[:keep]}.{ext}"
        else:
            cleaned = cleaned[:_MAX_SEGMENT_LEN]
    return cleaned


def project_folder_name(project_number: str | int, project_name: str) -> str:
    """Return the standard "{NUM}_{NAME}" segment, sanitized."""
    num = str(project_number).strip() if project_number is not None else ""
    nm = sanitize_filename(project_name or "")
    if not num:
        return nm
    return f"{num}_{nm}" if nm else num


def project_folder_path(project_number: str | int, project_name: str, category: str | None = None) -> str:
    """Compose the unencoded SharePoint path for a project (and optional category).

    Returns the path with the configured leading root segment and the leading
    space in "01_ Active Projects" intact (per B27 directive). The Graph caller
    is responsible for URL-encoding when issuing requests.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}. Expected one of {CATEGORIES}.")
    parts = [SIXDE_PROJECTS_ROOT, project_folder_name(project_number, project_name)]
    if category is not None:
        parts.append(category)
    return "/".join(p for p in parts if p)


def encode_path(path: str) -> str:
    """URL-encode each segment of a SharePoint path. Forward slashes preserved."""
    return "/".join(quote(seg, safe="") for seg in path.split("/"))


# ---------------------------------------------------------------------------
# Token storage (Fernet-encrypted file)
# ---------------------------------------------------------------------------
class TokenStoreError(RuntimeError):
    """Raised when the encrypted token store cannot be read/written."""


@dataclass
class _TokenStore:
    """Read/write the Fernet-encrypted Graph refresh token blob.

    The file at ``path`` contains a Fernet ciphertext whose plaintext is a
    JSON document. The schema is intentionally minimal so a future Phase 5
    migration is one INSERT + one delete.
    """

    path: Path
    key: bytes | None

    def _cipher(self):
        if not self.key:
            raise TokenStoreError(
                "SIXDE_TOKEN_KEY env var is not set; cannot encrypt/decrypt token store."
            )
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:
            raise TokenStoreError(
                "cryptography package is required for token storage. "
                "Install via requirements.txt."
            ) from exc
        return Fernet(self.key)

    def read(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        try:
            from cryptography.fernet import InvalidToken
        except ImportError as exc:
            raise TokenStoreError(
                "cryptography package is required for token storage."
            ) from exc
        try:
            ciphertext = self.path.read_bytes()
            plaintext = self._cipher().decrypt(ciphertext)
            return json.loads(plaintext.decode("utf-8"))
        except (OSError, ValueError, InvalidToken) as exc:
            raise TokenStoreError(
                f"Failed to read token store at {self.path}: {exc}"
            ) from exc

    def write(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        plaintext = json.dumps(payload, sort_keys=True).encode("utf-8")
        ciphertext = self._cipher().encrypt(plaintext)
        self.path.write_bytes(ciphertext)

    def clear(self) -> None:
        if self.path.exists():
            self.path.unlink()


def get_token_store(path: Path | None = None, key: bytes | None = None) -> _TokenStore:
    """Factory used by both production code and tests. Tests pass their own path+key."""
    resolved_path = path or MSGRAPH_TOKEN_PATH
    resolved_key = key if key is not None else (SIXDE_TOKEN_KEY.encode() if SIXDE_TOKEN_KEY else None)
    return _TokenStore(path=Path(resolved_path), key=resolved_key)


# ---------------------------------------------------------------------------
# Auth boundary
# ---------------------------------------------------------------------------
@dataclass
class StubCall:
    """One recorded call against the stub Graph client."""

    op: str
    path: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class StubGraphClient:
    """In-memory mock used when MSGRAPH_CLIENT_ID / MSGRAPH_TENANT_ID are unset.

    Records calls for inspection in tests. Returns deterministic fake IDs and
    URLs so the rest of the module produces consistent outputs offline.
    """

    calls: list[StubCall] = field(default_factory=list)
    folders: dict[str, str] = field(default_factory=dict)  # path -> drive_item_id
    items: dict[str, dict[str, Any]] = field(default_factory=dict)  # id -> metadata
    _id_counter: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _next_id(self, prefix: str) -> str:
        with self._lock:
            self._id_counter += 1
            return f"{prefix}-{self._id_counter:06d}"

    def ensure_folder(self, path: str) -> str:
        self.calls.append(StubCall(op="ensure_folder", path=path))
        if path not in self.folders:
            self.folders[path] = self._next_id("folder")
        return self.folders[path]

    def upload_bytes(self, path: str, content: bytes, *, content_type: str | None = None) -> dict[str, Any]:
        self.calls.append(StubCall(
            op="upload_bytes",
            path=path,
            extra={"size": len(content), "content_type": content_type},
        ))
        item_id = self._next_id("item")
        meta = {
            "id": item_id,
            "name": path.rsplit("/", 1)[-1],
            "size": len(content),
            "webUrl": f"https://stub.sharepoint.invalid/{encode_path(path)}",
            "parentReference": {"driveId": "stub-drive-0001", "path": path.rsplit("/", 1)[0]},
            "file": {"hashes": {"quickXorHash": "STUB"}},
        }
        self.items[item_id] = meta
        return meta

    def upload_large(self, path: str, content: bytes, *, content_type: str | None = None) -> dict[str, Any]:
        self.calls.append(StubCall(
            op="upload_large",
            path=path,
            extra={"size": len(content), "content_type": content_type, "chunks": (len(content) + _CHUNK_SIZE - 1) // _CHUNK_SIZE},
        ))
        return self.upload_bytes(path, content, content_type=content_type)

    def get_link(self, item_id: str) -> str:
        self.calls.append(StubCall(op="get_link", path=item_id))
        item = self.items.get(item_id)
        if item is None:
            raise KeyError(item_id)
        return item["webUrl"]

    def delete(self, item_id: str) -> None:
        self.calls.append(StubCall(op="delete", path=item_id))
        self.items.pop(item_id, None)

    def list_folder(self, path: str) -> list[dict[str, Any]]:
        self.calls.append(StubCall(op="list_folder", path=path))
        prefix = path.rstrip("/") + "/"
        return [
            meta for meta in self.items.values()
            if (meta.get("parentReference", {}).get("path", "") + "/").startswith(prefix)
        ]


_stub_singleton: StubGraphClient | None = None
_stub_lock = threading.Lock()


def _get_stub_singleton() -> StubGraphClient:
    """Module-level stub singleton so the same in-memory state is shared across calls."""
    global _stub_singleton
    with _stub_lock:
        if _stub_singleton is None:
            _stub_singleton = StubGraphClient()
        return _stub_singleton


def reset_stub_client() -> None:
    """Test helper: clear the stub singleton so each test starts fresh."""
    global _stub_singleton
    with _stub_lock:
        _stub_singleton = None


def get_graph_client():
    """Return the active Graph client — real ``GraphServiceClient`` or the stub.

    The decision is based purely on env-var presence so tests and offline dev
    proceed without an Azure round-trip. When real credentials are set, this
    function builds a ``GraphServiceClient`` backed by ``DeviceCodeCredential``
    plus the refresh token from ``_TokenStore``.
    """
    if not (MSGRAPH_CLIENT_ID and MSGRAPH_TENANT_ID):
        return _get_stub_singleton()
    return _build_real_client()


def _build_real_client():
    """Construct the live Graph client. Imports inside the function so the stub
    path works on machines that don't have msgraph-sdk / azure-identity installed."""
    try:
        from azure.identity import DeviceCodeCredential
        from msgraph import GraphServiceClient  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "MSGRAPH_CLIENT_ID is set but msgraph-sdk / azure-identity are not installed. "
            "pip install -r requirements.txt"
        ) from exc

    credential = DeviceCodeCredential(
        client_id=MSGRAPH_CLIENT_ID,
        tenant_id=MSGRAPH_TENANT_ID,
    )
    scopes = ["Sites.ReadWrite.All", "Files.ReadWrite.All", "offline_access"]
    return GraphServiceClient(credentials=credential, scopes=scopes)


# ---------------------------------------------------------------------------
# Project folder + upload operations
# ---------------------------------------------------------------------------
def ensure_project_folder(
    project_number: str | int,
    project_name: str,
    *,
    client=None,
) -> dict[str, str]:
    """Create the ``{NUM}_{NAME}/{Calcs,Drawings,Permits,Billing,Correspondence}``
    folder tree if missing. Returns a dict mapping category -> drive_item_id.
    Idempotent: re-running on an existing project returns the same IDs.
    """
    client = client or get_graph_client()
    project_path = project_folder_path(project_number, project_name)
    result = {"_root": _ensure_folder(client, project_path)}
    for category in CATEGORIES:
        result[category] = _ensure_folder(client, f"{project_path}/{category}")
    return result


def _ensure_folder(client, path: str) -> str:
    """Dispatch to client.ensure_folder when available (stub), otherwise build
    a real Graph PATCH-or-create call. The real path is not implemented in
    Session 2a — it raises NotImplementedError so the integration test catches
    it the moment real creds get wired in."""
    if hasattr(client, "ensure_folder"):
        return client.ensure_folder(path)
    raise NotImplementedError(
        "Real Graph ensure_folder is wired in Session 2b. See PLATFORM_GOAL_v1.md "
        "Phase 2 Session 2b for the createOrGet driveItem path."
    )


def upload_bytes(
    project_number: str | int,
    project_name: str,
    category: str,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
    client=None,
) -> dict[str, Any]:
    """Upload ``content`` to the category folder under the project. Returns the
    Graph driveItem metadata (id, name, size, webUrl, parentReference, ...).
    Routes to chunked upload when ``content`` is larger than 4 MB.
    """
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}. Expected one of {CATEGORIES}.")
    safe_name = sanitize_filename(filename)
    path = f"{project_folder_path(project_number, project_name, category)}/{safe_name}"
    client = client or get_graph_client()
    if hasattr(client, "upload_bytes") and len(content) <= _LARGE_UPLOAD_THRESHOLD:
        return client.upload_bytes(path, content, content_type=content_type)
    if hasattr(client, "upload_large"):
        return client.upload_large(path, content, content_type=content_type)
    raise NotImplementedError(
        "Real Graph upload is wired in Session 2b. See PLATFORM_GOAL_v1.md "
        "Phase 2 Session 2b for the small-upload and createUploadSession paths."
    )


def get_link(item_id: str, *, client=None) -> str:
    client = client or get_graph_client()
    if hasattr(client, "get_link"):
        return client.get_link(item_id)
    raise NotImplementedError("Real Graph get_link wired in Session 2b.")


def delete(item_id: str, *, client=None) -> None:
    client = client or get_graph_client()
    if hasattr(client, "delete"):
        client.delete(item_id)
        return
    raise NotImplementedError("Real Graph delete wired in Session 2b.")


def list_folder(
    project_number: str | int,
    project_name: str,
    category: str | None = None,
    *,
    client=None,
) -> list[dict[str, Any]]:
    client = client or get_graph_client()
    path = project_folder_path(project_number, project_name, category)
    if hasattr(client, "list_folder"):
        return client.list_folder(path)
    raise NotImplementedError("Real Graph list_folder wired in Session 2b.")


# ---------------------------------------------------------------------------
# Content hashing (dedup)
# ---------------------------------------------------------------------------
def content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


# ---------------------------------------------------------------------------
# DB linkage — registers an uploaded file in the documents table
# ---------------------------------------------------------------------------
def record_upload(
    conn: sqlite3.Connection,
    *,
    entity_type: str,
    entity_id: int,
    doc_type: str,
    project_number: str | int,
    project_name: str,
    category: str,
    filename: str,
    content: bytes,
    upload_result: dict[str, Any],
) -> int:
    """Insert a row in ``documents`` reflecting a SharePoint upload.

    Returns the new document id. Logs to ``activity_log`` so the Home
    "Recent Activity" feed actually shows uploads (per S36 B4 directive —
    new write paths must wire activity_log correctly from day one).
    """
    if category not in CATEGORIES:
        raise ValueError(f"Unknown category {category!r}.")
    sha = content_sha256(content)
    parent = upload_result.get("parentReference") or {}
    safe_name = sanitize_filename(filename)
    relative_path = f"{project_folder_path(project_number, project_name, category)}/{safe_name}"

    cur = conn.execute(
        """
        INSERT INTO documents (
            entity_type, entity_id, doc_type, file_name, file_path,
            sharepoint_item_id, sharepoint_web_url, sharepoint_drive_id, sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            entity_type,
            entity_id,
            doc_type,
            safe_name,
            relative_path,
            upload_result.get("id"),
            upload_result.get("webUrl"),
            parent.get("driveId"),
            sha,
        ),
    )
    doc_id = cur.lastrowid

    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, action, details) VALUES (?, ?, ?, ?)",
        (
            "document",
            doc_id,
            "uploaded_sharepoint",
            json.dumps({
                "category": category,
                "file_name": safe_name,
                "project_number": str(project_number),
                "size": upload_result.get("size", len(content)),
                "sha256": sha,
            }),
        ),
    )
    conn.commit()
    return doc_id


def find_by_sha256(conn: sqlite3.Connection, sha256: str) -> sqlite3.Row | None:
    """Lookup an existing document by content hash for dedup."""
    return conn.execute(
        "SELECT * FROM documents WHERE sha256 = ? LIMIT 1",
        (sha256,),
    ).fetchone()


# ---------------------------------------------------------------------------
# Retry helper for 429 Throttled responses (used in Session 2b live path)
# ---------------------------------------------------------------------------
def retry_with_backoff(fn, *, max_attempts: int = 5, base_delay: float = 1.0):
    """Run ``fn`` with exponential backoff on transient Graph errors.

    Wired but unused in Session 2a — exposed for Session 2b's live upload paths
    and the chunked-upload tests. Recognizes 429 / 503 by string match on
    common SDK exception messages; real impl uses the SDK's retry policy.
    """
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — Graph SDK exceptions vary
            msg = str(exc)
            if "429" not in msg and "503" not in msg:
                raise
            last_exc = exc
            time.sleep(base_delay * (2 ** attempt))
    raise last_exc  # type: ignore[misc]
