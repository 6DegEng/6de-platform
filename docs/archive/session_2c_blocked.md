# Phase 2 Session 2c — Blocked on Entra ID app registration

**Date:** 2026-05-21
**Phase:** C (real msgraph-sdk wiring)
**Status:** **BLOCKED**

---

## Pre-flight result

```
$ python -c "from modules.documents.sharepoint import get_graph_client; print(type(get_graph_client()).__name__)"
StubGraphClient
```

`MSGRAPH_CLIENT_ID`, `MSGRAPH_TENANT_ID`, and `SIXDE_TOKEN_KEY` are all unset
in the current process environment. Per the Phase C gate in the Session 2b
bug-fix sprint plan:

> If it prints StubGraphClient: Azure app reg not configured yet. STOP.

Phase C is therefore deferred until the app registration is provisioned and
the corresponding env vars are exported to Juan's working shell + the
Streamlit launcher.

---

## What Juan needs to do to unblock

Per `Technical Reference\sharepoint_session2b_prep.md` Part 1 Section C
(the canonical app-reg checklist):

1. **Azure portal — Microsoft Entra admin center** → App registrations → New
   registration.
   - Name: `6DE Company Platform` (or similar)
   - Supported account types: **Accounts in this organizational directory
     only** (single-tenant — the 6th Degree Engineering tenant)
   - Redirect URI: **Public client / native** → `http://localhost:8502/`
2. **API permissions** → Add a permission → Microsoft Graph → Delegated:
   - `Sites.ReadWrite.All`
   - `Files.ReadWrite.All`
   - `offline_access`
   - `User.Read` (default — kept for profile fetch)
3. **Grant admin consent** for the tenant on `Sites.ReadWrite.All` (required
   even with delegated scope when the tenant requires it).
4. **Copy** the Application (client) ID and the Directory (tenant) ID from
   the app's Overview blade.
5. **Generate a Fernet key** for refresh-token encryption:
   ```powershell
   py -3.14 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
6. **Export env vars** in the shell that launches the Streamlit app:
   ```powershell
   $env:MSGRAPH_CLIENT_ID = "<paste-client-id>"
   $env:MSGRAPH_TENANT_ID = "<paste-tenant-id>"
   $env:SIXDE_TOKEN_KEY   = "<paste-fernet-key>"
   ```
   For persistent setup, add these to the user environment via
   `[System.Environment]::SetEnvironmentVariable(...)` or via the Settings
   app → Advanced system settings → Environment Variables.
7. **Install the missing SDKs:**
   ```powershell
   py -3.14 -m pip install "msgraph-sdk>=1.0,<2" "azure-identity>=1.15,<2"
   ```
   `cryptography` is already installed (v48.0.0).
8. **Re-run the pre-flight** — should now print a class name other than
   `StubGraphClient` (probably `GraphServiceClient`):
   ```powershell
   py -3.14 -c "from modules.documents.sharepoint import get_graph_client; print(type(get_graph_client()).__name__)"
   ```

---

## What Phase C will do (once unblocked)

Scope from the sprint plan:

1. Replace `NotImplementedError` in these methods inside
   `modules/documents/sharepoint.py`:
   - `_ensure_folder(client, path)`
   - `upload_bytes(...)` real path (the one beyond the stub branch)
   - `upload_large(...)`
   - `get_link(item_id)`
   - `delete(item_id)`
   - `list_folder(project_number, project_name, category)`

   Auth uses the boundary already in `get_graph_client()`; the new code
   issues Graph SDK calls against the Sites / Drives endpoints.

2. Add `@pytest.mark.live` tests in `tests/test_sharepoint_live.py` for each
   method. Default test run skips them (`pytest -m "not live"`); to run them:

   ```powershell
   py -3.14 -m pytest tests/test_sharepoint_live.py -m live
   ```

3. Wire `retry_with_backoff` into the four mutation methods
   (`upload_bytes`, `upload_large`, `delete`, `_ensure_folder`) per Graph
   throttling guidance: respect `Retry-After` on 429, exponential backoff
   with jitter on 5xx, max 5 attempts.

4. **DO NOT run** `scripts/scan_existing_project_docs.py` against live
   SharePoint. UI uploads via the Documents tab will be tested manually by
   Juan with a single small test file uploaded to a `/Test/` subfolder.

---

## State of the rest of the Session 2b sprint

- **Phase A (260205 investigation):** complete — see
  `docs/qa/260205_investigation.md`. Verdict (a) — project exists, search
  bug masked it.
- **Phase B (search filter fix):** complete — commit `f1101d9`. Browser
  smoke-tested by Juan; tests 105/105 passing.
- **Phase C:** **blocked here.**

When Juan completes the app-reg checklist above and re-runs the pre-flight
to a non-stub result, restart this phase with `start phase c` (or equivalent)
and the gate will open.

---

## TODOs surfaced during the sprint (not in scope for Phase C)

Filed as future tickets:

1. **streamlit-authenticator JWT key is 26 bytes** (below RFC 7518's
   recommended 32-byte minimum for HMAC-SHA256). Warning visible in
   `launcher.log`. Cosmetic warning today, real risk only at scale.
2. **12 completed-status projects** still have OneDrive folders in
   `01_ Active Projects/`. Archive-on-completion convention not yet
   defined. (See `260205_investigation.md` side observations.)
3. **3 projects on disk missing from DB** (`260304 Buena Vista`, `260409
   1390 S Ocean Blvd`, `260413 3107 PGA Blvd`). Likely jobs started
   post-last-import; needs a one-shot importer pass to capture them.
4. **31 subfolder names unclassified** during backfill (recurring patterns:
   `Reports`, `From Client`, `03_From Client`, `05_Reports`). Easy to
   absorb into `classify_category` if Juan wants those ~300 files indexed.
