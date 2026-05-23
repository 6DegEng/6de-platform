"""Phase 2 Session 2c — checkpoint smoke test.

Round-trips a tiny payload through the live SharePoint Graph wrapper to
prove the wiring lands in real storage before the retry-hardener and
live-tests-builder subagents run. Writes to /Test/ at the drive root, NOT
into any real project folder.

Usage (from the platform root):

    python scripts/smoke_sharepoint_upload.py

First run: msgraph DeviceCodeCredential will print a code and URL — open
the URL in a browser, paste the code, sign in. The script then resumes
automatically. Subsequent runs in the same process reuse the in-memory
token.

Cleanup: the script deletes the uploaded item before exiting. If anything
fails mid-flight, the item may be left behind in /Test/.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# Ensure the platform root is on sys.path so `from modules...` works
# when this script is invoked from anywhere.
_PLATFORM_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.documents.sharepoint import (  # noqa: E402
    DocumentMissingError,
    get_graph_client,
)


def main() -> int:
    print("[1/5] Building Graph client...")
    client = get_graph_client()
    print(f"      client type: {type(client).__name__}")
    if type(client).__name__ == "StubGraphClient":
        print("ERROR: get_graph_client() returned StubGraphClient. .env not loading.")
        return 2

    ts = time.strftime("%Y%m%d_%H%M%S")
    test_path = f"Test/phase_c_smoke_{ts}.txt"
    payload = f"phase 2 session 2c smoke @ {ts}\n".encode()

    print(f"[2/5] Upload {len(payload)} bytes to /{test_path} ...")
    print("      (first run will print a device-code login prompt below)")
    result = client.upload_bytes(test_path, payload, content_type="text/plain")
    item_id = result.get("id")
    web_url = result.get("webUrl")
    drive_id = (result.get("parentReference") or {}).get("driveId")
    print(f"      uploaded. id={item_id}")
    print(f"      webUrl={web_url}")
    print(f"      driveId={drive_id}")

    if not item_id:
        print("ERROR: upload returned no item id; cannot verify or clean up.")
        return 3

    print("[3/5] get_link(item_id) ...")
    link = client.get_link(item_id)
    print(f"      link={link}")
    assert link == web_url, f"get_link mismatch: {link!r} vs {web_url!r}"

    print("[4/5] list_folder('Test') ...")
    children = client.list_folder("Test")
    names = [c.get("name") for c in children]
    print(f"      {len(children)} item(s) in /Test/: {names[:5]}{'...' if len(names) > 5 else ''}")
    assert any(c.get("id") == item_id for c in children), "uploaded item not in /Test/ listing"

    print(f"[5/5] delete(item_id) ...")
    client.delete(item_id)
    print("      deleted.")

    # Confirm 404 on a follow-up get_link.
    try:
        client.get_link(item_id)
    except DocumentMissingError:
        print("      verified: get_link on deleted id raises DocumentMissingError.")
    else:
        print("WARN: get_link on deleted id did not raise DocumentMissingError.")

    print("\nSMOKE OK — wiring is live. /Test/ is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
