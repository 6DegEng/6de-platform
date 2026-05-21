"""Phase 2 SharePoint module tests.

Covers:
  - Filename sanitization (20 adversarial cases per Phase 2 spec).
  - Path composition + URL encoding (preserves the intentional leading space
    in "01_ Active Projects" per B27).
  - StubGraphClient round-trips (env-var-absent path).
  - Fernet token store round-trip.
  - DB record_upload writes documents + activity_log rows.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import pytest

_PLATFORM_ROOT = Path(__file__).resolve().parents[1]
if str(_PLATFORM_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLATFORM_ROOT))

from modules.documents import sharepoint as sp  # noqa: E402


# ---------------------------------------------------------------------------
# Filename sanitization — 20 adversarial cases
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hello.pdf", "hello.pdf"),
        ("Project 260512 Calcs.pdf", "Project 260512 Calcs.pdf"),
        ('bad<>chars?.pdf', "badchars.pdf"),
        ('quote"in"name.pdf', "quoteinname.pdf"),
        ("slash/in/name.pdf", "slashinname.pdf"),
        ("backslash\\in\\name.pdf", "backslashinname.pdf"),
        ("pipe|name.pdf", "pipename.pdf"),
        ("star*name.pdf", "starname.pdf"),
        ("colon:in:name.pdf", "coloninname.pdf"),
        ("    leading and trailing.pdf    ", "leading and trailing.pdf"),
        ("multiple    spaces.pdf", "multiple spaces.pdf"),
        ("trailing.dot.", "trailing.dot"),
        ("trailing space ", "trailing space"),
        ("", "_"),
        ("   ", "_"),
        ("<<<>>>", "_"),
        ("a" * 200 + ".pdf", "a" * 124 + ".pdf"),  # 124 + ".pdf" = 128 chars
        ("control\x00\x01char.pdf", "controlchar.pdf"),
        ("newline\nname.pdf", "newline name.pdf"),  # newline -> whitespace -> collapsed
        ("tab\tname.pdf", "tab name.pdf"),
    ],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    result = sp.sanitize_filename(raw)
    assert result == expected, f"sanitize_filename({raw!r}) = {result!r} (expected {expected!r})"


def test_sanitize_filename_caps_at_max_segment_len() -> None:
    very_long = "a" * 500
    assert len(sp.sanitize_filename(very_long)) <= sp._MAX_SEGMENT_LEN


# ---------------------------------------------------------------------------
# Path composition
# ---------------------------------------------------------------------------
def test_project_folder_path_preserves_leading_space() -> None:
    """The leading space in '01_ Active Projects' is intentional (B27).
    project_folder_path() must NOT normalize or strip it."""
    path = sp.project_folder_path("260512", "Hibiscus St Residence")
    assert "01_ Active Projects" in path
    assert "01_Active Projects" not in path
    assert path.endswith("260512_Hibiscus St Residence")


def test_project_folder_path_includes_category() -> None:
    path = sp.project_folder_path("260512", "Test", category="Calcs")
    assert path.endswith("/260512_Test/Calcs")


def test_project_folder_path_rejects_bad_category() -> None:
    with pytest.raises(ValueError):
        sp.project_folder_path("260512", "Test", category="NotARealCategory")


def test_encode_path_encodes_spaces_and_preserves_slashes() -> None:
    raw = "06_Engineering/01_ Active Projects/260512_Test"
    encoded = sp.encode_path(raw)
    assert "%20" in encoded
    assert encoded.count("/") == raw.count("/")
    # Leading space specifically — verify it round-trips through encoding
    assert "01_%20Active%20Projects" in encoded


def test_project_folder_name_sanitizes_project_name() -> None:
    name = sp.project_folder_name("260512", "Bad/Chars*?:")
    assert "/" not in name
    assert "*" not in name
    assert "?" not in name
    assert ":" not in name
    assert name.startswith("260512_")


# ---------------------------------------------------------------------------
# StubGraphClient — exercises the offline-development boundary
# ---------------------------------------------------------------------------
@pytest.fixture()
def stub_client():
    sp.reset_stub_client()
    client = sp._get_stub_singleton()
    yield client
    sp.reset_stub_client()


def test_get_graph_client_returns_stub_when_env_unset(monkeypatch):
    """With MSGRAPH_* env vars unset, get_graph_client() must return a stub."""
    monkeypatch.setattr(sp, "MSGRAPH_CLIENT_ID", None)
    monkeypatch.setattr(sp, "MSGRAPH_TENANT_ID", None)
    sp.reset_stub_client()
    client = sp.get_graph_client()
    assert isinstance(client, sp.StubGraphClient)


def test_ensure_project_folder_creates_all_categories(stub_client):
    result = sp.ensure_project_folder("260512", "Test Project", client=stub_client)
    assert "_root" in result
    for cat in sp.CATEGORIES:
        assert cat in result
        assert result[cat]
    # Idempotent: second call returns identical IDs
    result2 = sp.ensure_project_folder("260512", "Test Project", client=stub_client)
    assert result == result2


def test_upload_bytes_records_call_and_returns_metadata(stub_client):
    meta = sp.upload_bytes(
        "260512",
        "Test Project",
        "Calcs",
        "calc_package.pdf",
        b"%PDF-1.4 fake pdf content",
        content_type="application/pdf",
        client=stub_client,
    )
    assert meta["id"].startswith("item-")
    assert meta["name"] == "calc_package.pdf"
    assert meta["size"] == len(b"%PDF-1.4 fake pdf content")
    assert "webUrl" in meta
    # The recorded call's path should include the project + category + filename
    upload_calls = [c for c in stub_client.calls if c.op == "upload_bytes"]
    assert upload_calls
    assert "260512_Test Project" in upload_calls[-1].path
    assert "/Calcs/calc_package.pdf" in upload_calls[-1].path


def test_upload_bytes_routes_large_payload_to_chunked(stub_client):
    big = b"x" * (sp._LARGE_UPLOAD_THRESHOLD + 1)
    sp.upload_bytes(
        "260512", "Big File Project", "Drawings", "huge.pdf", big, client=stub_client,
    )
    large_calls = [c for c in stub_client.calls if c.op == "upload_large"]
    assert large_calls
    assert large_calls[-1].extra["size"] == len(big)


def test_upload_bytes_rejects_unknown_category(stub_client):
    with pytest.raises(ValueError):
        sp.upload_bytes(
            "260512", "Test", "NotACategory", "x.pdf", b"x", client=stub_client,
        )


def test_upload_bytes_sanitizes_filename(stub_client):
    meta = sp.upload_bytes(
        "260512", "Test", "Billing", "bad<>name?.pdf", b"x", client=stub_client,
    )
    assert "<" not in meta["name"]
    assert "?" not in meta["name"]
    assert meta["name"] == "badname.pdf"


def test_get_link_returns_web_url(stub_client):
    meta = sp.upload_bytes(
        "260512", "Test", "Permits", "permit.pdf", b"x", client=stub_client,
    )
    url = sp.get_link(meta["id"], client=stub_client)
    assert url == meta["webUrl"]


def test_delete_removes_from_stub(stub_client):
    meta = sp.upload_bytes("260512", "Test", "Calcs", "x.pdf", b"x", client=stub_client)
    sp.delete(meta["id"], client=stub_client)
    assert meta["id"] not in stub_client.items


# ---------------------------------------------------------------------------
# Token store — Fernet round-trip
# ---------------------------------------------------------------------------
def test_token_store_roundtrip(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    key = Fernet.generate_key()
    store = sp.get_token_store(path=tmp_path / "graph_token.enc", key=key)
    payload = {"refresh_token": "fake-refresh-xyz", "expires_at": "2026-12-31T00:00:00Z"}
    store.write(payload)
    assert (tmp_path / "graph_token.enc").exists()
    read_back = store.read()
    assert read_back == payload


def test_token_store_read_missing_returns_none(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    store = sp.get_token_store(path=tmp_path / "absent.enc", key=Fernet.generate_key())
    assert store.read() is None


def test_token_store_without_key_raises(tmp_path, monkeypatch):
    """No SIXDE_TOKEN_KEY -> _TokenStore can't operate.

    Clears the env-derived fallback so this test stays valid once dotenv
    loading populates SIXDE_TOKEN_KEY for real runs.
    """
    monkeypatch.setattr(sp, "SIXDE_TOKEN_KEY", None)
    store = sp.get_token_store(path=tmp_path / "x.enc", key=None)
    with pytest.raises(sp.TokenStoreError):
        store.write({"refresh_token": "x"})


def test_token_store_corrupted_ciphertext_raises(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    path = tmp_path / "corrupt.enc"
    path.write_bytes(b"this is not a valid fernet token")
    store = sp.get_token_store(path=path, key=Fernet.generate_key())
    with pytest.raises(sp.TokenStoreError):
        store.read()


def test_token_store_clear_removes_file(tmp_path):
    pytest.importorskip("cryptography")
    from cryptography.fernet import Fernet

    path = tmp_path / "to_clear.enc"
    store = sp.get_token_store(path=path, key=Fernet.generate_key())
    store.write({"refresh_token": "x"})
    assert path.exists()
    store.clear()
    assert not path.exists()


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------
def test_content_sha256_deterministic():
    a = sp.content_sha256(b"hello world")
    b = sp.content_sha256(b"hello world")
    assert a == b
    assert sp.content_sha256(b"hello world!") != a


# ---------------------------------------------------------------------------
# DB integration — record_upload writes documents + activity_log per B4 directive
# ---------------------------------------------------------------------------
def test_record_upload_writes_documents_and_activity_log(db, stub_client):
    db.execute("INSERT INTO clients (name) VALUES ('Test Client')")
    db.execute(
        "INSERT INTO projects (job_number, name, client_id) VALUES ('260512', 'Hibiscus Residence', 1)"
    )
    db.commit()
    project_id = db.execute("SELECT id FROM projects WHERE job_number='260512'").fetchone()[0]

    content = b"%PDF-1.4 fake calc package"
    upload_meta = sp.upload_bytes(
        "260512", "Hibiscus Residence", "Calcs", "calc_package.pdf",
        content, client=stub_client,
    )
    doc_id = sp.record_upload(
        db,
        entity_type="project",
        entity_id=project_id,
        doc_type="calc_pdf",
        project_number="260512",
        project_name="Hibiscus Residence",
        category="Calcs",
        filename="calc_package.pdf",
        content=content,
        upload_result=upload_meta,
    )
    row = db.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)).fetchone()
    assert row["sharepoint_item_id"] == upload_meta["id"]
    assert row["sharepoint_web_url"] == upload_meta["webUrl"]
    assert row["sharepoint_drive_id"] == "stub-drive-0001"
    assert row["sha256"] == sp.content_sha256(content)
    assert "01_ Active Projects" in row["file_path"]

    # B4 directive: activity_log must reflect the upload
    log_rows = db.execute(
        "SELECT * FROM activity_log WHERE entity_type='document' AND entity_id=?",
        (doc_id,),
    ).fetchall()
    assert len(log_rows) == 1
    assert log_rows[0]["action"] == "uploaded_sharepoint"


def test_find_by_sha256_dedup_lookup(db, stub_client):
    db.execute("INSERT INTO clients (name) VALUES ('C')")
    db.execute("INSERT INTO projects (job_number, name, client_id) VALUES ('260101', 'P', 1)")
    db.commit()
    project_id = db.execute("SELECT id FROM projects WHERE job_number='260101'").fetchone()[0]

    content = b"unique-content-xyz"
    meta = sp.upload_bytes("260101", "P", "Permits", "p.pdf", content, client=stub_client)
    sp.record_upload(
        db,
        entity_type="project",
        entity_id=project_id,
        doc_type="permit_drawing",
        project_number="260101",
        project_name="P",
        category="Permits",
        filename="p.pdf",
        content=content,
        upload_result=meta,
    )
    sha = sp.content_sha256(content)
    found = sp.find_by_sha256(db, sha)
    assert found is not None
    assert found["sha256"] == sha
    assert sp.find_by_sha256(db, "deadbeef" * 8) is None


# ---------------------------------------------------------------------------
# Schema delta verification — Phase 2 columns present on documents
# ---------------------------------------------------------------------------
def test_documents_schema_includes_sharepoint_columns(db):
    cols = {r[1] for r in db.execute("PRAGMA table_info(documents)").fetchall()}
    for required in ("sharepoint_item_id", "sharepoint_web_url", "sharepoint_drive_id", "sha256"):
        assert required in cols, f"Phase 2 column {required} missing from documents schema"


# ---------------------------------------------------------------------------
# classify_category — heuristic subfolder → canonical category mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "subfolder,expected",
    [
        # Calcs
        ("Hydraulic Calculations", "Calcs"),
        ("Drainage Calculations", "Calcs"),
        ("Calcs", "Calcs"),
        ("Structural Analysis", "Calcs"),
        # Drawings
        ("Drawings", "Drawings"),
        ("Dwgs", "Drawings"),
        ("DWGs", "Drawings"),
        ("Shop Drawings", "Drawings"),
        ("Renders", "Drawings"),
        ("Site Photos", "Drawings"),
        ("Photos", "Drawings"),
        # Permits
        ("Permits", "Permits"),
        ("Permitting", "Permits"),
        ("Inspection Reports", "Permits"),
        ("NOA Approvals", "Permits"),
        # Billing
        ("Billing", "Billing"),
        ("Accounting", "Billing"),
        ("Contract Agreements", "Billing"),
        ("Invoices", "Billing"),
        # Correspondence
        ("Correspondence", "Correspondence"),
        ("PPT", "Correspondence"),
        ("Survey", "Correspondence"),
        ("Geotechnical Engineering", "Correspondence"),
        ("Product Data", "Correspondence"),
        # Archive / templates — excluded
        ("00_Archive", None),
        ("99_Templates", None),
        # Truly unrecognized
        ("RAMP, GLASS RAILING, POOL EQUIPMENT ENCLOSURE", None),
        ("", None),
        (None, None),
    ],
)
def test_classify_category(subfolder, expected):
    assert sp.classify_category(subfolder) == expected


# ---------------------------------------------------------------------------
# ensure_project_folder idempotency — re-running produces identical IDs
# ---------------------------------------------------------------------------
def test_ensure_project_folder_idempotent(stub_client):
    first = sp.ensure_project_folder("260512", "Idempotency Test", client=stub_client)
    pre_call_count = len(stub_client.calls)
    second = sp.ensure_project_folder("260512", "Idempotency Test", client=stub_client)
    assert first == second
    # ensure_folder is called again (6 times: root + 5 categories) but folders
    # dict keys are unchanged. The stub's internal state shows no new folder
    # IDs were minted.
    post_call_count = len(stub_client.calls)
    assert post_call_count - pre_call_count == 6  # root + 5 categories
    # But no new folder IDs minted
    assert set(first.values()) == set(second.values())


# ---------------------------------------------------------------------------
# Chunked upload routing — _LARGE_UPLOAD_THRESHOLD boundary cases
# ---------------------------------------------------------------------------
def test_upload_routes_below_threshold_to_small(stub_client):
    payload = b"x" * (sp._LARGE_UPLOAD_THRESHOLD - 1)
    sp.upload_bytes("260512", "Test", "Calcs", "small.pdf", payload, client=stub_client)
    small_calls = [c for c in stub_client.calls if c.op == "upload_bytes"]
    large_calls = [c for c in stub_client.calls if c.op == "upload_large"]
    assert len(small_calls) == 1
    assert len(large_calls) == 0


def test_upload_routes_at_exact_threshold_to_small(stub_client):
    """At-threshold (== 4MB) routes to small upload per <= comparison."""
    payload = b"x" * sp._LARGE_UPLOAD_THRESHOLD
    sp.upload_bytes("260512", "Test", "Calcs", "exact.pdf", payload, client=stub_client)
    small_calls = [c for c in stub_client.calls if c.op == "upload_bytes"]
    assert len(small_calls) == 1


def test_upload_routes_above_threshold_to_large(stub_client):
    payload = b"x" * (sp._LARGE_UPLOAD_THRESHOLD + 1)
    sp.upload_bytes("260512", "Test", "Drawings", "big.dwg", payload, client=stub_client)
    large_calls = [c for c in stub_client.calls if c.op == "upload_large"]
    assert len(large_calls) == 1
    # Chunks expected
    chunks = large_calls[0].extra["chunks"]
    expected = (len(payload) + sp._CHUNK_SIZE - 1) // sp._CHUNK_SIZE
    assert chunks == expected


# ---------------------------------------------------------------------------
# retry_with_backoff — 429 retry semantics
# ---------------------------------------------------------------------------
def test_retry_with_backoff_succeeds_on_eventual_success(monkeypatch):
    monkeypatch.setattr(sp.time, "sleep", lambda _: None)
    attempts = {"n": 0}

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("HTTP 429 Too Many Requests")
        return "ok"

    result = sp.retry_with_backoff(flaky, max_attempts=5, base_delay=0.01)
    assert result == "ok"
    assert attempts["n"] == 3


def test_retry_with_backoff_raises_after_max_attempts(monkeypatch):
    monkeypatch.setattr(sp.time, "sleep", lambda _: None)

    def always_fail():
        raise RuntimeError("HTTP 503 Service Unavailable")

    with pytest.raises(RuntimeError, match="503"):
        sp.retry_with_backoff(always_fail, max_attempts=3, base_delay=0.01)


def test_retry_with_backoff_does_not_swallow_non_throttle_errors(monkeypatch):
    monkeypatch.setattr(sp.time, "sleep", lambda _: None)
    attempts = {"n": 0}

    def fails_with_400():
        attempts["n"] += 1
        raise RuntimeError("HTTP 400 Bad Request")

    with pytest.raises(RuntimeError, match="400"):
        sp.retry_with_backoff(fails_with_400, max_attempts=5, base_delay=0.01)
    assert attempts["n"] == 1  # no retry on 400
