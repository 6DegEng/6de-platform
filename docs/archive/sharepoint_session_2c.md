# Session 2c — msgraph-sdk wire-up spec (verifier output)

**Date:** 2026-05-21
**Author:** spec-verifier subagent (research-only — no code touched)
**Status:** Spec complete; one HIGH-severity mismatch + two open questions block graph-wirer
**Inputs reviewed:** `PLATFORM_GOAL_v1.md`, `modules/documents/sharepoint.py`, `tests/test_sharepoint.py`, `config.py`, `docs/qa/session_2c_blocked.md`, live `msgraph-sdk` 1.58.0 introspection

---

## 1. Purpose

Confirm that the Session 2a stub interface (`StubGraphClient` in
`modules/documents/sharepoint.py` lines 271–338) maps 1:1 onto the real
msgraph-sdk calls the next subagent (graph-wirer) is about to write into the
`NotImplementedError` branches at lines 415–483.

This spec is **read-only research**. No code changed. Findings below feed
directly into the graph-wirer's implementation plan.

---

## 2. What the platform contract promises (PLATFORM_GOAL_v1.md)

### 2.1 SharePoint as the document store (Outcome #8, §1)

> Every generated PDF lands in `/Projects/{ProjectNumber}_{ProjectName}/{Calcs|Drawings|Permits|Billing|Correspondence}` via Graph upload. No human-facing PDFs in Render/Azure blob; SharePoint URLs render correctly in-app.

### 2.2 Phase 2 stack decision (§3)

> **Document store:** SharePoint via Graph API — `msgraph-sdk-python`. Already in tenant; permissions inherit.

### 2.3 Phase 2 Session 2a scope (§4 Phase 2)

> `modules/documents/sharepoint.py` wraps `msgraph-sdk-python`:
> - `ensure_project_folder(project_number, project_name) -> drive_item_id` — creates `/Projects/{NUM}_{NAME}/{Calcs|Drawings|Permits|Billing|Correspondence}` if missing
> - `upload_bytes(...)` — small files <4MB
> - `upload_large(...)` — chunked via `createUploadSession`, 5MB chunks
> - `get_link(item_id)`, `delete(item_id)`, `list_folder(...)`

### 2.4 Phase 2 Session 2b gate

> Test PDF uploads to `/Projects/260512_TestProject/Billing/`, returns working SharePoint URL, `documents` row links back. Re-running returns same URL. 50-char-filename-with-illegal-chars uploads sanitized.

### 2.5 Trade-off #2 — auth (§11)

> SharePoint OAuth needs a registered redirect URI. App registration in Phase 2 uses `http://localhost:8502/` for dev. Microsoft allows multiple redirect URIs on a single app registration, so at Phase 8 (hosting flip) the production URL is *added* to the existing registration — no re-registration, no token invalidation.

### 2.6 Risk register (§7) — relevant items

- "SharePoint Graph rate limit (10 req/sec) — Med — Chunked uploader respects 429; bulk-ingestion spreads across hours"
- "Filename sanitization edge case — Low — 20 adversarial unit tests; on 400 from Graph, retry with more aggressive sanitization"

The contract above is what graph-wirer must satisfy. The rest of this spec
checks whether the stub interface lines up with what msgraph-sdk 1.58.0
actually exposes.

---

## 3. Method-by-method mapping

For each stub method: Python signature, the Graph REST call the wirer will
make, the corresponding msgraph-sdk SDK fluent call, and (most importantly)
the return-shape contract — both what tests assert today and what the SDK
hands back.

### 3.1 `ensure_folder(path: str) -> str`

**Stub (lines 289–293):**
```python
def ensure_folder(self, path: str) -> str:
    # returns a drive_item_id string
```

Stub returns a synthetic `"folder-NNNNNN"` string and stores it in `self.folders[path]`.

**REST equivalent:** `POST /drives/{drive-id}/items/{parent-id}/children` with body:
```json
{
  "name": "<segment>",
  "folder": {},
  "@microsoft.graph.conflictBehavior": "rename"
}
```
…iterated segment-by-segment from the drive root. **The "rename" conflict
behavior in the prompt is wrong for an `ensure_folder` operation**: rename
creates a sibling like "Calcs 1" when "Calcs" already exists. The correct
verb here is `conflictBehavior=replace` (returns existing if same kind) or
better yet `fail` + catch the 409 → fetch existing. See §6 OPEN QUESTION #1.

**msgraph-sdk call (per-segment, walking the path):**
```python
from msgraph.generated.models.drive_item import DriveItem
from msgraph.generated.models.folder import Folder

new_folder = DriveItem(
    name=segment,
    folder=Folder(),
    additional_data={"@microsoft.graph.conflictBehavior": "fail"},
)
created = await client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id(parent_id) \
    .children.post(new_folder)
# created.id  -> the new (or existing-on-409-handled) drive item id
```

**Return-shape contract:**

| Caller need | Stub behavior | SDK call result | Wirer action |
|---|---|---|---|
| Return a drive item id string | `"folder-000001"` | `created.id: str` | Pull `.id`, return |
| Idempotent on re-call | Dict cache by path | Graph itself; `replace`/`fail`+lookup | Use 409 catch + GET, or `replace` |

**Mismatch:** none on the **return type** (`str`), but the **idempotency
mechanism** differs and is the source of the conflict-behavior debate in §6.

---

### 3.2 `upload_bytes(path, content, *, content_type) -> dict[str, Any]`

**Stub (lines 295–311):** returns a dict shaped:
```python
{
    "id": "item-NNNNNN",
    "name": "<basename>",
    "size": <int>,
    "webUrl": "https://stub.sharepoint.invalid/<encoded-path>",
    "parentReference": {"driveId": "stub-drive-0001", "path": "<parent>"},
    "file": {"hashes": {"quickXorHash": "STUB"}},
}
```

**REST equivalent (small, ≤4MB):**
```
PUT /drives/{drive-id}/root:/<path>:/content
Content-Type: <content_type or octet-stream>
<bytes>
```
Returns a `driveItem` JSON resource.

**msgraph-sdk call:**
```python
# Path-based addressing via get_item_with_path is the idiomatic way:
item_builder = client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id("root:/" + encoded_path + ":")
result = await item_builder.content.put(content)
# result is a DriveItem instance
```
Alternative explicit form:
```python
from msgraph.generated.drives.item.items.item.content.content_request_builder import (
    ContentRequestBuilder,
)
# or use get_item_at_path_with_path(...).content.put(...)
```

**Return-shape contract — THIS IS THE CRITICAL MISMATCH:**

| Test assertion (`test_sharepoint.py`) | Stub dict key | SDK `DriveItem` field |
|---|---|---|
| `meta["id"].startswith("item-")` | `"id"` (camelCase) | `result.id` (snake) |
| `meta["name"] == "calc_package.pdf"` | `"name"` | `result.name` |
| `meta["size"] == len(content)` | `"size"` | `result.size` |
| `"webUrl" in meta` / `meta["webUrl"]` | **`"webUrl"`** | **`result.web_url`** |
| `record_upload` reads `upload_result.get("parentReference") → .get("driveId")` (sharepoint.py L518, L537) | **`"parentReference"["driveId"]`** | **`result.parent_reference.drive_id`** |

The DriveItem SDK model is **a Python object with snake_case attributes**,
not a JSON-shaped dict. The stub returns camelCase dict keys verbatim
(matching Graph's REST JSON wire format).

**Severity: HIGH.** This affects:

1. `tests/test_sharepoint.py::test_upload_bytes_records_call_and_returns_metadata` — asserts `meta["webUrl"]` exists. Will fail if wirer hands back `DriveItem` directly.
2. `tests/test_sharepoint.py::test_record_upload_writes_documents_and_activity_log` — asserts `row["sharepoint_drive_id"] == "stub-drive-0001"`. The DB write path at sharepoint.py:518–537 reads `upload_result.get("parentReference") → .get("driveId")`. Both keys are camelCase dict-lookups; `DriveItem.parent_reference.drive_id` won't be reached.
3. `tests/test_sharepoint.py::test_get_link_returns_web_url` — asserts `url == meta["webUrl"]`.

**Required wirer action — a translation layer.** The wirer MUST NOT return the
raw `DriveItem` object. It MUST project to the stub's dict shape:

```python
def _driveitem_to_dict(item: DriveItem) -> dict[str, Any]:
    parent = item.parent_reference
    return {
        "id": item.id,
        "name": item.name,
        "size": item.size,
        "webUrl": item.web_url,
        "parentReference": {
            "driveId": parent.drive_id if parent else None,
            "path":    parent.path     if parent else None,
        },
        "file": (
            {"hashes": {"quickXorHash": item.file.hashes.quick_xor_hash}}
            if item.file and item.file.hashes else None
        ),
    }
```
Doing this once at the module boundary keeps the stub contract and every
downstream consumer (record_upload, future Documents tab UI) unchanged.

---

### 3.3 `upload_large(path, content, *, content_type) -> dict[str, Any]`

**Stub (lines 313–319):** records `chunks = (len + CHUNK_SIZE − 1) // CHUNK_SIZE`, delegates to `upload_bytes` for the actual return shape. So the stub return shape is identical to small upload.

**REST equivalent (large, >4MB):**

1. `POST /drives/{drive-id}/root:/<path>:/createUploadSession` with body:
   ```json
   {"item": {"@microsoft.graph.conflictBehavior": "replace", "name": "<basename>"}}
   ```
   Response: `UploadSession { upload_url, expiration_date_time, next_expected_ranges }`.
2. For each 5MB chunk: `PUT <upload_url>` with header
   `Content-Range: bytes <start>-<end>/<total>`. Graph returns 202 with
   updated `next_expected_ranges` until the last chunk, which returns 201
   + the final `driveItem`.

**msgraph-sdk call:**

The SDK exposes upload-session creation:
```python
from msgraph.generated.drives.item.items.item.create_upload_session.create_upload_session_post_request_body \
    import CreateUploadSessionPostRequestBody
from msgraph.generated.models.drive_item_uploadable_properties import DriveItemUploadableProperties

body = CreateUploadSessionPostRequestBody(
    item=DriveItemUploadableProperties(
        name=basename,
        additional_data={"@microsoft.graph.conflictBehavior": "replace"},
    )
)
session = await client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id("root:/" + encoded_path + ":") \
    .create_upload_session.post(body)
# session.upload_url, session.next_expected_ranges, session.expiration_date_time
```

**Chunk uploads** are PUTs against the raw `upload_url` and do NOT go through
the GraphServiceClient — they hit the bare HTTPS endpoint with `Content-Range`.
The wirer needs either `httpx` or `requests` to drive the chunked PUT loop.
msgraph-sdk does not currently ship a fluent chunked-upload helper that does
this loop end-to-end (1.58.0 — confirmed via attribute introspection).

**Return-shape contract:** the final 201 response is a `driveItem` JSON
matching `upload_bytes`. The wirer projects to dict the same way (§3.2).

**Mismatch:** same camelCase / snake_case translation as §3.2. **Additional
chunked-upload-specific concerns:**

- **Chunk size must be a multiple of 320 KiB** per Graph docs. Current
  `_CHUNK_SIZE = 5 * 1024 * 1024 = 5,242,880 bytes`. `5,242,880 / 327,680 =
  16.0` — clean multiple of 320 KiB. Fine.
- **`next_expected_ranges`** must be honored — if a chunk fails and Graph
  reports it expects bytes 5,242,880-10,485,759, the wirer resumes from
  that range, not from a local counter. The stub doesn't simulate this.
- **Retry-After on 503** during chunked upload must be respected (see §4
  on retry).

---

### 3.4 `get_link(item_id: str) -> str`

**Stub (lines 321–326):** looks up its in-memory `items[item_id]["webUrl"]`,
raises `KeyError` if missing.

**REST equivalent:** `GET /drives/{drive-id}/items/{item-id}` — returns the
driveItem; pull `webUrl`. (For shareable links, the wirer could also call
`POST /drives/{drive-id}/items/{item-id}/createLink`, but the test
(`test_get_link_returns_web_url`) just asserts the stored webUrl, so a plain
GET is sufficient.)

**msgraph-sdk call:**
```python
item = await client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id(item_id) \
    .get()
return item.web_url
```

**Return-shape contract:** `str`. No mismatch — the wirer just reads
`item.web_url` (snake_case at the SDK boundary, returned as plain string).

**Mismatch:** the stub `raise KeyError(item_id)` for missing items vs. SDK
raising `ODataError` with `response_status_code=404`. The function
`sharepoint.get_link()` at module level does **not** currently translate that
exception. See §4 (error handling) and OPEN QUESTION #2.

**Also note:** `get_link()` does not receive a `drive_id` parameter. The
wirer needs the drive id from somewhere. Two options:
- Look it up once per process (cache `_SITE_DRIVE_ID`) — the platform uses a
  single SharePoint document library, so one drive_id is sufficient.
- Encode it in the `item_id` (the platform's `documents.sharepoint_drive_id`
  column stores it; the wirer reads from DB).

See §5 (path/drive strategy).

---

### 3.5 `delete(item_id: str) -> None`

**Stub (lines 328–330):** pops the item from in-memory dict, no return.

**REST equivalent:** `DELETE /drives/{drive-id}/items/{item-id}` — 204.

**msgraph-sdk call:**
```python
await client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id(item_id) \
    .delete()
```

**Return-shape contract:** `None` either way. No mismatch.

**Mismatch:** same `ODataError` 404 vs silent pop. The stub silently
succeeds when the item doesn't exist (`self.items.pop(item_id, None)`); the
real SDK will raise on 404. The module-level wrapper should either swallow
404 to match the stub OR document that the real-path behavior is
"raises on missing" — see OPEN QUESTION #2.

---

### 3.6 `list_folder(path: str) -> list[dict[str, Any]]`

**Stub (lines 332–338):** walks its in-memory items, returns those whose
`parentReference.path` starts with the input path.

**REST equivalent:** `GET /drives/{drive-id}/root:/<path>:/children` — returns
a page of child DriveItems. May paginate via `@odata.nextLink`.

**msgraph-sdk call:**
```python
# Path-based addressing for the parent folder:
result = await client.drives.by_drive_id(drive_id) \
    .items.by_drive_item_id("root:/" + encoded_path + ":") \
    .children.get()
# result.value: list[DriveItem]
# result.odata_next_link: optional str for next page
```

The wirer must handle pagination — `result.odata_next_link` indicates more
pages; loop until `None`.

**Return-shape contract:** `list[dict[str, Any]]`, each dict in the stub's
camelCase shape. Wirer applies the same `_driveitem_to_dict` projection from
§3.2 across `result.value`.

**Mismatch:** camelCase projection (per §3.2). Plus pagination — the stub
returns a flat list with no pagination concept; the real SDK does. Wirer
must roll up all pages before returning to match.

---

## 4. Error handling shape — string-match retry vs structured SDK errors

### 4.1 What the module does today (line 573)

```python
def retry_with_backoff(fn, *, max_attempts=5, base_delay=1.0):
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            msg = str(exc)
            if "429" not in msg and "503" not in msg:
                raise
            last_exc = exc
            time.sleep(base_delay * (2 ** attempt))
    raise last_exc
```

String-matching `"429"` / `"503"` against `str(exc)`. The tests
(`test_retry_with_backoff_*`) pass plain `RuntimeError("HTTP 429 ...")`
which satisfies the match.

### 4.2 What msgraph-sdk actually raises

`msgraph.generated.models.o_data_errors.o_data_error.ODataError` — inherits
from `kiota_abstractions.api_error.APIError`. Confirmed via introspection:

```python
ODataError(
    backing_store, additional_data,
    message: str | None,
    response_status_code: int | None,    # ← structured!
    response_headers: dict[str, str] | None,
    error: Optional[MainError]
)
```

This is **strictly better** than string-matching. The wirer should refactor
`retry_with_backoff` to detect throttling by attribute, not regex:

```python
def _is_throttled(exc: Exception) -> bool:
    code = getattr(exc, "response_status_code", None)
    if code in (429, 503, 504):
        return True
    # Fallback for raw HTTPX errors during chunked PUT
    msg = str(exc)
    return "429" in msg or "503" in msg

def _retry_after(exc: Exception) -> float | None:
    headers = getattr(exc, "response_headers", None) or {}
    ra = headers.get("Retry-After")
    return float(ra) if ra else None
```

Existing tests will still pass — the fallback string match covers them. New
behavior: the wirer can honor the `Retry-After` header that Graph sends on
real 429s.

**Severity: MEDIUM.** Doesn't break the stub or the existing tests, but the
session-2c-blocked doc explicitly calls for "respect `Retry-After` on 429,
exponential backoff with jitter on 5xx, max 5 attempts" — which the current
helper doesn't do. The wirer should refactor.

### 4.3 Mismatches against test_sharepoint.py retry tests

| Test | Behavior | Wirer impact |
|---|---|---|
| `test_retry_with_backoff_succeeds_on_eventual_success` | `RuntimeError("HTTP 429 ...")` | Keep fallback string-match path so test stays green |
| `test_retry_with_backoff_raises_after_max_attempts` | `RuntimeError("HTTP 503 ...")` | Same — keep string fallback |
| `test_retry_with_backoff_does_not_swallow_non_throttle_errors` | `RuntimeError("HTTP 400 ...")` | Same — 400 not in throttle set |

The wirer can add structured detection AS WELL AS the string fallback and
none of the three retry tests need to change.

---

## 5. Path strategy — where does `drive-id` come from?

The stub takes a path like `"06_Engineering/01_ Active Projects/260512_Foo/Calcs"` and treats it as if it could be passed straight to Graph. Real Graph needs `{drive-id}` and a colon-delimited path.

### 5.1 Drive resolution — the missing link

`PLATFORM_GOAL_v1.md` §3 specifies "SharePoint" as the document store
(not personal OneDrive). The Phase 2a tenant uses M365 with a SharePoint
site whose **document library** holds `06_Engineering/01_ Active Projects/...`.

Two-step resolution the wirer must perform once at module load (cache it):

**Step 1 — site lookup:**

```python
# By hostname + site-relative path:
site = await client.sites.with_url(
    f"https://{HOSTNAME}/sites/{SITE_NAME}"
).get()
# OR by hostname:path:
site = await client.sites.get_by_path_with_path(...).get()
# site.id  → "tenant.sharepoint.com,<site-guid>,<web-guid>"
```

**Step 2 — drive lookup (default document library):**

```python
drive = await client.sites.by_site_id(site.id).drive.get()
# drive.id  → cache this for the process
```

**What we don't know from the files:** the SharePoint **hostname** and
**site relative path**. `config.py` only exposes `SIXDE_PROJECTS_ROOT =
"06_Engineering/01_ Active Projects"` — the path INSIDE the document library,
not the site URL.

This is **OPEN QUESTION #3** in §6.

The likely answer (based on a typical 6DE tenant + the
`PLATFORM_GOAL_v1.md` "Already in tenant; permissions inherit" line) is
that the documents live in the **default tenant document library** — i.e.
`https://6thde.sharepoint.com/sites/<site>` or the root site
`https://6thde.sharepoint.com/`, with `Shared Documents` (or the localized
library name) as the drive. But the spec-verifier must NOT invent this —
the wirer must read the actual value from Juan or from a `SIXDE_GRAPH_SITE`
env var (proposed below).

**Proposed config additions** (NOT in scope to add — wirer's call):

```python
# config.py — proposed
SIXDE_GRAPH_HOSTNAME   = os.environ.get("SIXDE_GRAPH_HOSTNAME",   "6thde.sharepoint.com")
SIXDE_GRAPH_SITE_PATH  = os.environ.get("SIXDE_GRAPH_SITE_PATH",  "/sites/6DE")  # or empty for root site
SIXDE_GRAPH_DRIVE_NAME = os.environ.get("SIXDE_GRAPH_DRIVE_NAME", "Documents")   # libraries can be renamed
```

### 5.2 Path encoding — does the leading space survive?

The stub stores paths with the literal leading space in `"01_ Active
Projects"`. The module's `encode_path()` (line 184) does:

```python
def encode_path(path: str) -> str:
    return "/".join(quote(seg, safe="") for seg in path.split("/"))
```

`urllib.parse.quote("01_ Active Projects", safe="")` returns
`"01_%20Active%20Projects"` — verified by `test_encode_path_encodes_spaces_and_preserves_slashes`.

When the wirer constructs `f"root:/{encode_path(path)}:"` and hands it to
the SDK builder via `.items.by_drive_item_id("root:/...:")`, the SDK passes
the already-encoded segment through without double-encoding (the SDK
treats the segment as a literal item-id string at that point — it's the
path-style addressing reserved syntax `root:/<percent-encoded>:`). **The
leading-space survives the encoding** and Graph receives `%20` which it
decodes back to ` ` (space) at its end.

**Verification needed at integration time:** Graph occasionally normalizes
paths. The graph-wirer should add a smoke test that creates and reads back
a file under `"01_ Active Projects/"` and asserts the parent path round-trips
with the space intact. This is the explicit B27 directive in the source
header.

**No code mismatch** — `encode_path()` already does the right thing. Just
flagging that the wirer should not be tempted to "clean up" the path before
encoding.

---

## 6. Auth strategy — DeviceCodeCredential vs InteractiveBrowserCredential

### 6.1 Current code (lines 386–391)

```python
credential = DeviceCodeCredential(
    client_id=MSGRAPH_CLIENT_ID,
    tenant_id=MSGRAPH_TENANT_ID,
)
scopes = ["Sites.ReadWrite.All", "Files.ReadWrite.All", "offline_access"]
return GraphServiceClient(credentials=credential, scopes=scopes)
```

### 6.2 Is DeviceCodeCredential the right choice?

**Yes, given the setup notes in `docs/qa/session_2c_blocked.md`:**

- The app registration is **single-tenant** (6th Degree Engineering tenant only).
- Configured as **"Public client / native"** with redirect URI
  `http://localhost:8502/`.
- Admin consent granted on `Sites.ReadWrite.All`.

Public-client + device-code is the canonical combination for headless / CLI /
locally-running-server scenarios when you'd rather not spin up a temporary
HTTP server to catch a browser redirect. **DeviceCodeCredential is the
right choice** for Phase 2 dev (localhost Streamlit) AND for Phase 8 (Render
deploy) — at Render, `InteractiveBrowserCredential` wouldn't work anyway
(no browser on the server), but DeviceCodeCredential's "go to
microsoft.com/devicelogin and enter this code" flow works from any deploy
target.

**Alternative: `InteractiveBrowserCredential`** would auto-open a browser tab
on the dev box, which is slightly slicker for local dev. But it breaks the
moment the platform deploys to Render (Phase 8) and the wirer would have to
add a credential-selection seam. **DeviceCodeCredential is uniform across
dev and prod** and that's worth more than the one-time slickness on local.

**Recommendation: keep `DeviceCodeCredential`.** No change needed.

### 6.3 One subtlety — refresh token caching

`DeviceCodeCredential` by default caches tokens **in memory only**. To
persist refresh tokens to `MSGRAPH_TOKEN_PATH` (the encrypted file the
module already maintains), the wirer needs:

```python
from azure.identity import DeviceCodeCredential, TokenCachePersistenceOptions

credential = DeviceCodeCredential(
    client_id=MSGRAPH_CLIENT_ID,
    tenant_id=MSGRAPH_TENANT_ID,
    # Either use msal-extensions cache:
    cache_persistence_options=TokenCachePersistenceOptions(
        name="6de-platform", allow_unencrypted_storage=False,
    ),
    # OR (preferred) wire to the existing _TokenStore via a custom
    # TokenCachePersistenceOptions backend.
)
```

OR — the cleaner integration with the existing `_TokenStore` plumbing —
the wirer subclasses `DeviceCodeCredential` or wraps it so the refresh
token persists into the Fernet-encrypted file already at
`MSGRAPH_TOKEN_PATH`. The `_TokenStore.read()/write()` API already exists
for exactly this; it just isn't wired to `DeviceCodeCredential` yet.

**Severity: MEDIUM.** Without persistence, Juan has to re-do the device
code dance every time the Streamlit process restarts. That's annoying
during dev (process restarts on every code edit) and unacceptable in prod.
The Phase 5 migration TODO in the module docstring (lines 25–29) already
anticipates this — but the wiring isn't there yet.

---

## 7. Mismatch summary table

| # | Severity | Location | Stub behavior | Real SDK behavior | Wirer action |
|---|---|---|---|---|---|
| 1 | **HIGH** | `upload_bytes`, `upload_large`, `list_folder` return shape | camelCase dict (`webUrl`, `parentReference.driveId`) | snake_case object (`web_url`, `parent_reference.drive_id`) | Add `_driveitem_to_dict()` projection at boundary |
| 2 | MED | `_ensure_folder` idempotency | dict cache | Graph 409 on conflict | Use `conflictBehavior=fail` + catch 409 + GET existing (NOT `rename` as prompt suggested) |
| 3 | MED | `retry_with_backoff` error detection | String match on `str(exc)` for "429"/"503" | `ODataError.response_status_code: int` | Add structured detection + keep string fallback so existing tests pass; honor `Retry-After` |
| 4 | MED | `DeviceCodeCredential` token persistence | n/a (stub) | In-memory only by default | Wire SDK token cache to existing `_TokenStore` (Fernet-encrypted file) |
| 5 | LOW | `delete` / `get_link` on missing item | silent (delete) / `KeyError` (get_link) | `ODataError` 404 | Decide whether module wrappers swallow 404 to match stub semantics |
| 6 | LOW | `list_folder` pagination | flat list | `@odata.nextLink` pagination | Roll up all pages before returning |
| 7 | LOW | Drive resolution | hard-coded `"stub-drive-0001"` | requires `sites/{host}:{path}:/drive` lookup | One-time process-scoped lookup + cache |
| 8 | INFO | Path encoding (`01_ Active Projects` with leading space) | `encode_path()` preserves | `%20` survives `root:/...:` path-style addressing | No change; add round-trip smoke test |
| 9 | INFO | Chunk size 5 MiB | hard-coded `_CHUNK_SIZE` | Graph requires multiple of 320 KiB; 5 MiB is fine | No change |

**Total methods verified:** 6 stub methods + 1 retry helper + 1 auth/token flow = 8 surfaces.
**Mismatches found:** 1 HIGH, 3 MED, 3 LOW (plus 2 INFO-only "watch for this" items).
**Blockers:** the HIGH item (camelCase return shape) is fully addressable in
the wirer with a single projection helper; the 3 OPEN QUESTIONS below
require Juan input before the wirer can proceed.

---

## 8. Open questions blocking the graph-wirer

### Q1 — conflictBehavior for `ensure_folder`

The session-2c-blocked prompt says "Folder creation: `POST /drives/{drive-id}/items/{parent-id}/children` with `conflictBehavior=rename`".

**But `rename` is wrong for idempotent ensure semantics.** It would create
`"Calcs"`, then `"Calcs 1"`, then `"Calcs 2"`... on repeated calls.

**Two acceptable alternatives:**

- **`fail`** — POST returns 409 if folder exists. Wirer catches 409, issues
  GET on `root:/{path}:`, returns existing id. Two round-trips on
  collision, one round-trip on cold create.
- **`replace`** — POST returns 200 with the existing folder if same kind
  (folder vs file). One round-trip in either case. **BUT** documented Graph
  semantics around `replace` on a folder are subtle (does it delete
  contents?). Microsoft docs say `replace` on a folder = "use existing,
  don't touch contents" — but the spec-verifier hasn't confirmed this
  against the running tenant.

**Asking Juan to pick.** Default recommendation: **`fail` + catch 409 + GET** —
explicit, unambiguous, predictable Graph behavior. Slightly more code but
safer for an irreversible operation.

### Q2 — 404 swallow vs raise on missing items

`StubGraphClient.delete(item_id)` is silent on missing (uses
`pop(item_id, None)`). `StubGraphClient.get_link(item_id)` raises
`KeyError`.

The real SDK raises `ODataError(response_status_code=404)` for both.

**Pick one — does the module-level `sharepoint.delete()` / `sharepoint.get_link()` wrapper:**

- (a) Translate 404 → `KeyError` to match `StubGraphClient.get_link`?
  Translate `delete` 404 → silent success to match `StubGraphClient.delete`?
- (b) Let `ODataError` propagate unchanged on the real path? (Caller-burden;
  the call site at `2_Billing.py` etc. would need to know to catch it.)
- (c) Define a module-level `DocumentMissingError(KeyError)` that's raised
  by both stub and real paths uniformly? (Cleanest API, but requires
  changing the stub too — currently raises plain `KeyError`.)

**Asking Juan to pick.** Default recommendation: **(c)** — `DocumentMissingError`
as a module-level alias of `KeyError` so existing `KeyError` catches still
work but the type name is self-documenting. Wirer updates `StubGraphClient`
in step (the file is in scope for Session 2c per `session_2c_blocked.md`).

### Q3 — Site / drive resolution

`config.py` doesn't expose the SharePoint hostname or site-relative path.

Three things the wirer needs to know:

- **SharePoint hostname** — `6thde.sharepoint.com`? Or hosted under the
  parent company's tenant URL?
- **Site path** — root site (`https://{host}/`) or a specific site
  (`https://{host}/sites/{name}`)?
- **Document library name** — `"Documents"` (English default)?
  `"Documents - 6th Degree Engineering"` (matches the OneDrive sync folder
  name in the working directory at the top of this conversation)? Something
  else?

The working directory path in this conversation
(`...Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform`)
strongly suggests the library is named **"Documents - 6th Degree
Engineering"** — but the spec-verifier MUST NOT bake that assumption
into the wirer. Juan should confirm:

1. SharePoint site URL (paste from a browser tab on a known-good doc).
2. Library name as it appears in the Graph response (the wirer can write a
   one-shot `scripts/probe_graph_drive.py` to list `client.sites.by_site_id(
   site.id).drives.get()` and print names — Juan reads from output).

**Asking Juan for the site URL + library name.** Default assumption pending
his answer: the library is the one whose OneDrive sync path matches
`"Documents - 6th Degree Engineering"`. The wirer should add three env
vars (`SIXDE_GRAPH_HOSTNAME`, `SIXDE_GRAPH_SITE_PATH`, `SIXDE_GRAPH_DRIVE_NAME`)
to `config.py`, with defaults TBD by Juan's answer.

---

## 9. Recommendations summary for the graph-wirer

1. **Build `_driveitem_to_dict()` first.** All upload/list paths funnel
   through it. Get the projection right once and the rest of the wiring
   is mechanical. Unit-test the projection with a fixture `DriveItem`.

2. **Drive-id is process-scoped — cache it.** Add `_resolve_drive_id()`
   memoized via a module-level lock + sentinel. Don't look it up on
   every call. The OneDrive sync from one library → one drive_id is a
   stable invariant.

3. **Wire `_TokenStore` to `DeviceCodeCredential` in the same PR.** Without
   it, the device-code dance fires every Streamlit reload. The Fernet
   storage already exists; just hand it to `azure.identity` via custom
   `TokenCachePersistenceOptions` or a thin wrapper.

4. **Refactor `retry_with_backoff` to detect by attribute, keep string
   fallback.** Honor `Retry-After`. Add jitter (e.g.
   `backoff = base * (2**n) + random.uniform(0, 1)`). Existing 3 retry
   tests continue to pass — verify before merging.

5. **For `_ensure_folder` use `conflictBehavior=fail` + 409 → GET.**
   Override the `rename` instruction in the original prompt; rename creates
   sibling folders which is the opposite of "ensure". (Pending Q1 from Juan.)

6. **Add a single live-tier smoke test that round-trips a 1KB file** into
   the production library under `06_Engineering/01_ Active Projects/Test/`
   and verifies (a) upload returns dict-shaped result with `webUrl`
   populated, (b) `parentReference.driveId` matches the resolved drive id,
   (c) the leading space in `01_ Active Projects` survived, (d) `delete()`
   removes it. Single test, single roundtrip — gated under `pytest -m live`
   per `docs/qa/session_2c_blocked.md`.

7. **Do NOT remove `StubGraphClient`.** It remains the default when env
   vars are unset, and is what every existing test exercises. The wirer's
   changes go in the `NotImplementedError` branches (lines 415–483), not
   in the stub.

---

## 10. Files referenced (absolute paths)

- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\PLATFORM_GOAL_v1.md`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\modules\documents\sharepoint.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\tests\test_sharepoint.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\config.py`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\docs\qa\session_2c_blocked.md`
- `C:\Users\juanc\OneDrive - 6th Degree Engineering\Documents - 6th Degree Engineering\02_Information Technology\07_Company_Platform\requirements.txt`

msgraph-sdk version verified live: **1.58.0** (introspected for DriveItem,
ItemReference, UploadSession, ODataError field names).

---

## 11. Resolutions from Juan (2026-05-21)

The three blocking open questions in §6 have been resolved. The graph-wirer
proceeds with these answers:

1. **SharePoint site URL:**
   - Hostname: `6thdegreeengineering.sharepoint.com`
   - Site path: `/sites/6thDegreeEngineering`
   - Full URL: `https://6thdegreeengineering.sharepoint.com/sites/6thDegreeEngineering`
   - **Library/drive:** the OneDrive sync path is `Documents - 6th Degree Engineering`,
     which in Graph terms is the site's default document library named `Documents`
     (the suffix is added by the OneDrive client to disambiguate). The wirer
     resolves the drive at module load via `client.sites.by_site_id(site.id).drive.get()`
     and caches `drive.id` for the process. If the default-drive resolution
     ever returns the wrong library, the fallback is to enumerate
     `.drives.get()` and match on `name == "Documents"`.
   - New config keys (to add in config.py):
     ```python
     SIXDE_GRAPH_HOSTNAME   = os.environ.get("SIXDE_GRAPH_HOSTNAME",
                                              "6thdegreeengineering.sharepoint.com")
     SIXDE_GRAPH_SITE_PATH  = os.environ.get("SIXDE_GRAPH_SITE_PATH",
                                              "/sites/6thDegreeEngineering")
     ```
     `SIXDE_GRAPH_DRIVE_NAME` is NOT needed — the default drive is correct.

2. **conflictBehavior for ensure_folder:** `fail` + 409→GET fallback.
   The original prompt's `rename` was wrong (would create `Calcs 1`, `Calcs 2`
   on re-runs and break idempotence). Wirer: POST with `conflictBehavior=fail`,
   on 409 (or ODataError code `nameAlreadyExists`) issue a GET against
   `/drives/{drive-id}/root:/{path}:` to return the existing folder's id.

3. **404 semantics for delete() and get_link():** raise a new module-level
   `DocumentMissingError(RuntimeError)`. Add to `modules/documents/sharepoint.py`
   alongside `TokenStoreError`. Wirer must translate 404 ODataErrors → this
   exception so callers don't need to import msgraph-sdk to catch the missing
   case. `delete()` is NOT silent on 404 — callers who want idempotent delete
   can `try: ... except DocumentMissingError: pass`.
