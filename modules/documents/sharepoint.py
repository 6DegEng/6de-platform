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

import asyncio
import hashlib
import io
import json
import random
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
    SIXDE_GRAPH_HOSTNAME,
    SIXDE_GRAPH_SITE_PATH,
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


class DocumentMissingError(RuntimeError):
    """Raised when a SharePoint drive item cannot be found (Graph 404).

    Wraps the underlying SDK exception so callers can catch a stable, module-
    level type without importing msgraph-sdk. ``delete()`` is NOT silent on
    404 — callers wanting idempotent delete should
    ``try: delete(id); except DocumentMissingError: pass``. ``get_link()``
    likewise propagates this on missing items.
    """


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


def _driveitem_to_dict(item: Any) -> dict[str, Any]:
    """Project an msgraph-sdk ``DriveItem`` (snake_case attributes) onto the
    camelCase dict shape the rest of the module + tests expect.

    Keeping this translation at the boundary means ``record_upload`` and every
    downstream consumer reads the same dict whether the upload came from the
    stub or the live Graph client. See docs/specs/sharepoint_session_2c.md §3.2
    for the full mismatch table.
    """
    if item is None:
        return {}
    parent = getattr(item, "parent_reference", None)
    file_obj = getattr(item, "file", None)
    hashes = getattr(file_obj, "hashes", None) if file_obj else None
    file_payload: dict[str, Any] | None = None
    if hashes is not None:
        file_payload = {
            "hashes": {
                "quickXorHash": getattr(hashes, "quick_xor_hash", None),
            }
        }
    return {
        "id": getattr(item, "id", None),
        "name": getattr(item, "name", None),
        "size": getattr(item, "size", None),
        "webUrl": getattr(item, "web_url", None),
        "parentReference": {
            "driveId": getattr(parent, "drive_id", None) if parent else None,
            "path": getattr(parent, "path", None) if parent else None,
        },
        "file": file_payload,
    }


def _odata_status_code(exc: Exception) -> int | None:
    """Extract the HTTP status code from an msgraph-sdk ``ODataError``.

    The SDK exposes ``response_status_code`` directly; callers don't need to
    import the SDK exception type. Returns ``None`` for non-Graph errors.
    """
    return getattr(exc, "response_status_code", None)


# Background event loop shared by every RealGraphClient call. msgraph-sdk's
# httpx connection pool, the credential's token cache, and kiota's middleware
# stack all bind themselves to whatever loop first touched them, so each
# asyncio.run() (which creates and tears down a fresh loop) leaves the next
# call with stale loop-bound resources — on Windows the visible symptom is
# AttributeError: 'NoneType' object has no attribute 'send' from the proactor.
# A single long-lived loop in a daemon thread avoids that.
_graph_loop: asyncio.AbstractEventLoop | None = None
_graph_loop_lock = threading.Lock()


def _get_graph_loop() -> asyncio.AbstractEventLoop:
    global _graph_loop
    if _graph_loop is not None and not _graph_loop.is_closed():
        return _graph_loop
    with _graph_loop_lock:
        if _graph_loop is None or _graph_loop.is_closed():
            loop = asyncio.new_event_loop()
            t = threading.Thread(target=loop.run_forever, name="graph-loop", daemon=True)
            t.start()
            _graph_loop = loop
    return _graph_loop


def _run_on_graph_loop(coro):
    """Schedule ``coro`` on the persistent graph loop and block until done."""
    fut = asyncio.run_coroutine_threadsafe(coro, _get_graph_loop())
    return fut.result()


@dataclass
class RealGraphClient:
    """Live Microsoft Graph client wrapper. Duck-types ``StubGraphClient`` so
    the module-level dispatch (``hasattr(client, "upload_bytes")``) routes
    here when env vars are set.

    Sync-over-async: msgraph-sdk is async-first. We hand every coroutine off
    to a single long-lived event loop running in a daemon thread (see
    ``_get_graph_loop`` above). Earlier per-call ``asyncio.run()`` leaked
    loop-bound httpx state between calls. True async migration is a Phase 2
    follow-up.
    """

    _graph_client: Any
    _site_id: str | None = None
    _drive_id: str | None = None

    # ----- internal: site/drive resolution -----------------------------------
    async def _ensure_drive_id(self) -> str:
        """Async-safe lazy resolver for the default drive id. Internal async
        methods MUST call this instead of touching ``self._drive_id`` directly,
        otherwise the first call would have to wrap ``_resolve_site_and_drive``
        in ``asyncio.run()`` — which deadlocks because we're already inside
        the event loop spun up by the outer ``asyncio.run()`` in the sync
        wrapper. Single round-trip per process; idempotent if a race ever
        runs the resolver twice (the cached value just gets overwritten with
        the same id)."""
        if self._drive_id is not None:
            return self._drive_id
        self._site_id, self._drive_id = await self._resolve_site_and_drive()
        return self._drive_id

    async def _resolve_site_and_drive(self) -> tuple[str, str]:
        # Graph path-style site lookup: /sites/{hostname}:{site-relative-path}
        site_key = f"{SIXDE_GRAPH_HOSTNAME}:{SIXDE_GRAPH_SITE_PATH}"
        site = await self._graph_client.sites.by_site_id(site_key).get()
        if site is None or site.id is None:
            raise RuntimeError(
                f"SharePoint site lookup failed for {site_key!r}. "
                "Verify SIXDE_GRAPH_HOSTNAME / SIXDE_GRAPH_SITE_PATH."
            )
        drive = await self._graph_client.sites.by_site_id(site.id).drive.get()
        if drive is None or drive.id is None:
            raise RuntimeError(
                f"Default drive lookup failed for site {site.id!r}. "
                "Confirm the site has a default document library."
            )
        return site.id, drive.id

    # ----- ensure_folder ----------------------------------------------------
    def ensure_folder(self, path: str) -> str:
        return _run_on_graph_loop(self._ensure_folder_async(path))

    async def _ensure_folder_async(self, path: str) -> str:
        from msgraph.generated.models.drive_item import DriveItem
        from msgraph.generated.models.folder import Folder
        from msgraph.generated.models.o_data_errors.o_data_error import ODataError

        drive_id = await self._ensure_drive_id()
        segments = [s for s in path.split("/") if s]
        if not segments:
            raise ValueError("ensure_folder() requires a non-empty path.")

        async def _ensure_one(parent_id: str, seg: str, cumulative: list[str]) -> str:
            """Create-or-resolve a single folder segment.

            Wrapped in ``retry_with_backoff_async`` so transient 429/5xx on
            the POST (or on the 409→GET conflict path) are retried with
            backoff. The 409 conflict-resolved-by-GET path is NOT a throttle
            and is handled inline here, not as a retry.
            """
            new_folder = DriveItem(
                name=seg,
                folder=Folder(),
                additional_data={"@microsoft.graph.conflictBehavior": "fail"},
            )
            try:
                created = await (
                    self._graph_client.drives.by_drive_id(drive_id)
                    .items.by_drive_item_id(parent_id)
                    .children.post(new_folder)
                )
                if created is None or created.id is None:
                    raise RuntimeError(
                        f"ensure_folder POST returned no driveItem for segment {seg!r}."
                    )
                return created.id
            except ODataError as exc:
                if _odata_status_code(exc) == 409 or "nameAlreadyExists" in (str(exc) or ""):
                    # Folder already exists — fetch it via path-style addressing.
                    item_path = "/".join(cumulative)
                    existing = await (
                        self._graph_client.drives.by_drive_id(drive_id)
                        .items.by_drive_item_id(f"root:/{encode_path(item_path)}:")
                        .get()
                    )
                    if existing is None or existing.id is None:
                        raise RuntimeError(
                            f"409 on POST but GET returned no driveItem for {item_path!r}."
                        ) from exc
                    return existing.id
                raise

        # Start at the drive root, then create or fetch each successive segment.
        # parent_id == "root" is a Graph alias for the drive root drive item.
        parent_id = "root"
        cumulative: list[str] = []
        leaf_id: str | None = None
        for seg in segments:
            cumulative.append(seg)
            snapshot = list(cumulative)
            current_parent = parent_id
            leaf_id = await retry_with_backoff_async(
                lambda: _ensure_one(current_parent, seg, snapshot)
            )
            parent_id = leaf_id  # walk into the just-created/existing folder

        assert leaf_id is not None  # invariant: loop ran at least once
        return leaf_id

    # ----- upload_bytes -----------------------------------------------------
    def upload_bytes(
        self, path: str, content: bytes, *, content_type: str | None = None
    ) -> dict[str, Any]:
        return _run_on_graph_loop(self._upload_bytes_async(path, content, content_type=content_type))

    async def _upload_bytes_async(
        self, path: str, content: bytes, *, content_type: str | None = None
    ) -> dict[str, Any]:
        drive_id = await self._ensure_drive_id()
        # Ensure parent folder hierarchy exists before PUTing content.
        # _ensure_folder_async is itself retry-wrapped per segment, so we
        # don't double-wrap it here.
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        if parent_path:
            await self._ensure_folder_async(parent_path)

        async def _do_put() -> dict[str, Any]:
            item = await (
                self._graph_client.drives.by_drive_id(drive_id)
                .items.by_drive_item_id(f"root:/{encode_path(path)}:")
                .content.put(content)
            )
            return _driveitem_to_dict(item)

        return await retry_with_backoff_async(_do_put)

    # ----- upload_large -----------------------------------------------------
    def upload_large(
        self, path: str, content: bytes, *, content_type: str | None = None
    ) -> dict[str, Any]:
        return _run_on_graph_loop(self._upload_large_async(path, content, content_type=content_type))

    async def _upload_large_async(
        self, path: str, content: bytes, *, content_type: str | None = None
    ) -> dict[str, Any]:
        from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body import (
            CreateUploadSessionPostRequestBody,
        )
        from msgraph.generated.models.drive_item import DriveItem
        from msgraph.generated.models.drive_item_uploadable_properties import (
            DriveItemUploadableProperties,
        )
        from msgraph_core.tasks.large_file_upload import LargeFileUploadTask

        drive_id = await self._ensure_drive_id()
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        basename = path.rsplit("/", 1)[-1]
        if parent_path:
            await self._ensure_folder_async(parent_path)

        async def _do_upload() -> dict[str, Any]:
            upload_props = DriveItemUploadableProperties(
                name=basename,
                additional_data={"@microsoft.graph.conflictBehavior": "replace"},
            )
            body = CreateUploadSessionPostRequestBody(item=upload_props)
            session = await (
                self._graph_client.drives.by_drive_id(drive_id)
                .items.by_drive_item_id(f"root:/{encode_path(path)}:")
                .create_upload_session.post(body)
            )
            if session is None or getattr(session, "upload_url", None) is None:
                raise RuntimeError("createUploadSession returned no upload_url.")

            stream = io.BytesIO(content)
            task = LargeFileUploadTask(
                upload_session=session,
                request_adapter=self._graph_client.request_adapter,
                stream=stream,
                parsable_factory=DriveItem,
                max_chunk_size=_CHUNK_SIZE,
            )
            result = await task.upload()
            # LargeFileUploadTask.upload() returns the final DriveItem (or wraps it
            # via UploadResult.item_response on newer kiota releases).
            item = getattr(result, "item_response", result)
            return _driveitem_to_dict(item)

        return await retry_with_backoff_async(_do_upload)

    # ----- get_link ---------------------------------------------------------
    def get_link(self, item_id: str) -> str:
        return _run_on_graph_loop(self._get_link_async(item_id))

    async def _get_link_async(self, item_id: str) -> str:
        from msgraph.generated.models.o_data_errors.o_data_error import ODataError

        drive_id = await self._ensure_drive_id()
        try:
            item = await (
                self._graph_client.drives.by_drive_id(drive_id)
                .items.by_drive_item_id(item_id)
                .get()
            )
        except ODataError as exc:
            if _odata_status_code(exc) == 404:
                raise DocumentMissingError(item_id) from exc
            raise
        if item is None:
            raise DocumentMissingError(item_id)
        return item.web_url

    # ----- delete -----------------------------------------------------------
    def delete(self, item_id: str) -> None:
        _run_on_graph_loop(self._delete_async(item_id))

    async def _delete_async(self, item_id: str) -> None:
        from msgraph.generated.models.o_data_errors.o_data_error import ODataError

        drive_id = await self._ensure_drive_id()

        async def _do_delete() -> None:
            try:
                await (
                    self._graph_client.drives.by_drive_id(drive_id)
                    .items.by_drive_item_id(item_id)
                    .delete()
                )
            except ODataError as exc:
                # 404 is a terminal "missing" — translate and re-raise so the
                # retry helper sees a non-transient error and bails out.
                if _odata_status_code(exc) == 404:
                    raise DocumentMissingError(item_id) from exc
                raise

        await retry_with_backoff_async(_do_delete)

    # ----- list_folder ------------------------------------------------------
    def list_folder(self, path: str) -> list[dict[str, Any]]:
        return _run_on_graph_loop(self._list_folder_async(path))

    async def _list_folder_async(self, path: str) -> list[dict[str, Any]]:
        drive_id = await self._ensure_drive_id()
        builder = (
            self._graph_client.drives.by_drive_id(drive_id)
            .items.by_drive_item_id(f"root:/{encode_path(path)}:")
            .children
        )
        result = await builder.get()
        out: list[dict[str, Any]] = []
        while result is not None:
            for child in result.value or []:
                out.append(_driveitem_to_dict(child))
            next_link = getattr(result, "odata_next_link", None)
            if not next_link:
                break
            # Reuse the same builder to follow the @odata.nextLink page.
            result = await builder.with_url(next_link).get()
        return out


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


def _build_real_client() -> RealGraphClient:
    """Construct the live Graph client wrapper.

    Returns a ``RealGraphClient`` whose duck-typed methods (``ensure_folder``,
    ``upload_bytes`` etc.) match ``StubGraphClient``. The module-level dispatch
    functions therefore route to the live wrapper via ``hasattr`` without any
    is-real branch.

    Imports inside the function so the stub path works on machines that don't
    have msgraph-sdk / azure-identity installed.

    TODO (retry-hardener or follow-up): the spec recommends wiring
    ``TokenCachePersistenceOptions`` so the DeviceCodeCredential refresh token
    persists into the existing Fernet-encrypted ``_TokenStore`` blob. Without
    this, every Streamlit reload triggers a fresh device-code dance. See
    docs/specs/sharepoint_session_2c.md §6.3.
    """
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
    # Only resource scopes here — MSAL auto-includes openid/profile/offline_access
    # and rejects explicit passes of those reserved values.
    scopes = ["Sites.ReadWrite.All", "Files.ReadWrite.All"]
    graph_client = GraphServiceClient(credentials=credential, scopes=scopes)
    return RealGraphClient(_graph_client=graph_client)


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
    """Dispatch to the active client's ``ensure_folder``. Both ``StubGraphClient``
    and ``RealGraphClient`` expose this method, so the only failure mode is a
    truly broken client. The ``hasattr`` guard keeps the door open for future
    alternate clients (in-tenant mocks, etc.)."""
    if hasattr(client, "ensure_folder"):
        return client.ensure_folder(path)
    raise NotImplementedError(
        f"Graph client {type(client).__name__} does not expose ensure_folder()."
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
        f"Graph client {type(client).__name__} does not expose upload_bytes/upload_large."
    )


def get_link(item_id: str, *, client=None) -> str:
    client = client or get_graph_client()
    if hasattr(client, "get_link"):
        return client.get_link(item_id)
    raise NotImplementedError(
        f"Graph client {type(client).__name__} does not expose get_link()."
    )


def delete(item_id: str, *, client=None) -> None:
    client = client or get_graph_client()
    if hasattr(client, "delete"):
        client.delete(item_id)
        return
    raise NotImplementedError(
        f"Graph client {type(client).__name__} does not expose delete()."
    )


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
    raise NotImplementedError(
        f"Graph client {type(client).__name__} does not expose list_folder()."
    )


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


def _is_transient_graph_error(exc: Exception) -> bool:
    """Decide whether ``exc`` should trigger a retry.

    Preferred path: structured detection via ``_odata_status_code(exc)`` —
    retry on 429 (throttling) or any 5xx (server error).

    Fallback path (non-ODataError exceptions raised in test fixtures or by
    layers that have lost the SDK exception type): string-match "429" or
    "503" in ``str(exc)`` to mirror the sync ``retry_with_backoff`` helper.
    """
    code = _odata_status_code(exc)
    if isinstance(code, int):
        if code == 429:
            return True
        if 500 <= code <= 599:
            return True
        # Any other structured code (4xx other than 429) is non-transient.
        return False
    msg = str(exc)
    return "429" in msg or "503" in msg


def _retry_after_seconds(exc: Exception) -> float | None:
    """Extract ``Retry-After`` (seconds) from an SDK exception's headers.

    Graph returns ``Retry-After`` either as a decimal seconds value or an
    HTTP-date. Only the seconds form is honored here — HTTP-date parsing is
    out of scope for the retry-hardener (Phase-3 polish). Returns None when
    the header is missing, non-numeric, or non-positive.
    """
    headers = getattr(exc, "response_headers", None)
    if headers is None:
        return None
    # SDK headers are typically dict-like, but kiota uses a case-insensitive
    # multi-dict. Try the obvious accessors before giving up.
    raw: Any = None
    if hasattr(headers, "get"):
        raw = headers.get("Retry-After") or headers.get("retry-after")
    if raw is None:
        try:
            raw = headers["Retry-After"]  # type: ignore[index]
        except (KeyError, TypeError):
            raw = None
    if raw is None:
        return None
    # Some SDKs return list-valued headers.
    if isinstance(raw, (list, tuple)) and raw:
        raw = raw[0]
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


async def retry_with_backoff_async(
    coro_factory,
    *,
    max_attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
):
    """Async sibling of :func:`retry_with_backoff` for coroutine factories.

    ``coro_factory`` is a zero-arg callable that returns a fresh coroutine
    each attempt (you can't await the same coroutine twice). On a transient
    Graph error (429 or 5xx, detected structurally via
    ``_odata_status_code`` or — as a fallback — by string match on the
    exception message), this helper sleeps and retries up to
    ``max_attempts`` times. Sleep duration honors the ``Retry-After``
    response header when present and positive; otherwise it follows an
    exponential schedule with random jitter, capped at ``max_delay``.

    On any other exception, the original is re-raised immediately. After
    ``max_attempts`` failed attempts, the last exception is re-raised.
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await coro_factory()
        except Exception as exc:  # noqa: BLE001 — Graph SDK exceptions vary
            if not _is_transient_graph_error(exc):
                raise
            last_exc = exc
            if attempt == max_attempts - 1:
                break
            retry_after = _retry_after_seconds(exc)
            if retry_after is not None:
                delay = min(retry_after, max_delay)
            else:
                delay = min(
                    base_delay * (2 ** attempt) + random.uniform(0, base_delay),
                    max_delay,
                )
            await asyncio.sleep(delay)
    assert last_exc is not None  # invariant: we only reach here after a caught exc
    raise last_exc
