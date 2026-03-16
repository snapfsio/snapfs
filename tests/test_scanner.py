__doc__ = """
Unit tests for snapfs.scanner.
"""

from types import SimpleNamespace

import pytest

from snapfs import scanner


class DummyAuthError(Exception):
    """Simulated authentication error with optional HTTP status code."""

    def __init__(self, status=None, message=""):
        super().__init__(message)
        self.status = status


def test_sha1_file_and_async_match(tmp_path):
    """Test that synchronous and asynchronous SHA-1 hashing produce the same result."""
    path = tmp_path / "sample.txt"
    path.write_text("snapfs test data\n", encoding="utf-8")

    sync_hash = scanner.sha1_file(str(path))
    async_hash = __import__("asyncio").run(scanner.sha1_file_async(str(path)))

    assert sync_hash == "123f7631859af45c1566b781bed2355685aa1fcf"
    assert async_hash == sync_hash


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, "manual"),
        ("manual", "manual"),
        (" schedule ", "schedule"),
        ("API", "api"),
        ("unknown", "manual"),
    ],
)
def test_normalize_trigger_type(value, expected):
    """Test that various trigger type inputs are normalized correctly."""
    assert scanner._normalize_trigger_type(value) == expected


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (DummyAuthError(status=401), True),
        (DummyAuthError(status=403), True),
        (DummyAuthError(status=500, message="Unauthorized"), True),
        (RuntimeError("forbidden by policy"), True),
        (RuntimeError("connection reset"), False),
    ],
)
def test_is_auth_error(exc, expected):
    """Test that various exceptions are correctly identified as authentication errors."""
    assert scanner._is_auth_error(exc) is expected


def test_lookup_owner_group_falls_back_to_ids(monkeypatch):
    """Test that _lookup_owner_group returns UID/GID strings when pwd/grp modules are unavailable."""
    monkeypatch.setattr(scanner, "pwd", None)
    monkeypatch.setattr(scanner, "grp", None)
    st = SimpleNamespace(st_uid=501, st_gid=20)

    owner, group = scanner._lookup_owner_group(st)

    assert owner == "501"
    assert group == "20"


def test_event_from_stat_builds_expected_payload(monkeypatch):
    """Test that event_from_stat constructs the expected event payload from a stat result."""
    monkeypatch.setattr(scanner, "_lookup_owner_group", lambda st: ("alice", "staff"))
    monkeypatch.setattr(scanner.time, "time", lambda: 1712345678.25)

    st = SimpleNamespace(
        st_size=1234,
        st_mtime_ns=1_700_000_000_123_000_000,
        st_atime_ns=1_700_000_000_456_000_000,
        st_ctime_ns=1_700_000_000_789_000_000,
        st_ino=42,
        st_dev=7,
        st_nlink=2,
        st_uid=1000,
        st_gid=100,
        st_mode=0o100644,
    )

    event = scanner.event_from_stat(
        "/data/example/file.txt",
        st,
        "sha1",
        "abc123",
        fsize_du=4096,
        root_path="/data",
        scan_id="scan-123",
    )

    assert event["type"] == "file.upsert"
    data = event["data"]
    assert data["root_path"] == "/data"
    assert data["scan_id"] == "scan-123"
    assert data["path"] == "/data/example/file.txt"
    assert data["dir"] == "/data/example"
    assert data["name"] == "file.txt"
    assert data["ext"] == ".txt"
    assert data["size"] == 1234
    assert data["fsize_du"] == 4096
    assert data["mtime"] == 1_700_000_000_123
    assert data["atime"] == 1_700_000_000_456
    assert data["ctime"] == 1_700_000_000_789
    assert data["nlinks"] == 2
    assert data["inode"] == 42
    assert data["dev"] == 7
    assert data["owner"] == "alice"
    assert data["group"] == "staff"
    assert data["uid"] == 1000
    assert data["gid"] == 100
    assert data["mode"] == 0o644
    assert data["algo"] == "sha1"
    assert data["hash"] == "abc123"
    assert data["seen_at"] == 1712345678.25
