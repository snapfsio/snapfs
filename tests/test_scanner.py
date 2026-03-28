__doc__ = """
Unit tests for snapfs.scanner.
"""

import asyncio
from types import SimpleNamespace

import pytest

from snapfs import hashing, scanner


class DummyAuthError(Exception):
    """Simulated authentication error with optional HTTP status code."""

    def __init__(self, status=None, message=""):
        super().__init__(message)
        self.status = status


class FakeGateway:
    """Minimal gateway double for scanner integration tests."""

    def __init__(self, probe_results=None):
        self.probe_results = list(probe_results or [])
        self.published_batches = []

    async def cache_probe_batch_async(self, probes):
        if self.probe_results:
            return self.probe_results.pop(0)
        return [{"status": "MISS"} for _ in probes]

    async def publish_events_async(self, events, subject=None):
        self.published_batches.append({"events": list(events), "subject": subject})
        return {"ok": True}


class FakeClient:
    """Minimal client wrapper exposing a fake gateway."""

    def __init__(self, gateway):
        self.gateway = gateway


def test_sha1_file_and_async_match(tmp_path):
    """Test that synchronous and asynchronous SHA-1 hashing produce the same result."""
    path = tmp_path / "sample.txt"
    path.write_bytes(b"snapfs test data\n")

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


def test_hashing_registry_supports_sha_algorithms(tmp_path):
    """Hashing registry should resolve and execute the built-in SHA algorithms."""
    path = tmp_path / "sample.txt"
    path.write_bytes(b"snapfs test data\n")

    assert hashing.resolve_algorithm("sha1") == "sha1"
    assert hashing.resolve_algorithm("sha256") == "sha256"
    assert hashing.hash_file(str(path), "sha1") == scanner.sha1_file(str(path))
    assert (
        hashing.hash_file(str(path), "sha256")
        == "f65be7b59cb7a10e38909f15d40008cda13a0da7fa2c087ffc8289245ba43399"
    )


def test_hashing_registry_reports_optional_algorithm_helpfully():
    """Unavailable optional algorithms should raise a useful error message."""
    if hashing.is_available("xxh64"):
        assert hashing.resolve_algorithm("xxh64") == "xxh64"
        return

    with pytest.raises(ValueError, match="xxhash"):
        hashing.resolve_algorithm("xxh64")


def test_scan_dir_supports_multi_worker_hashing(tmp_path, monkeypatch):
    """scan_dir should complete successfully when hashing uses multiple worker processes."""
    root = tmp_path / "root"
    root.mkdir()
    (root / "a.txt").write_text("alpha\n")
    (root / "b.txt").write_text("beta\n")

    gateway = FakeGateway()
    client = FakeClient(gateway)

    monkeypatch.setattr(scanner.settings, "probe_batch", 10)
    monkeypatch.setattr(scanner.settings, "publish_batch", 10)
    monkeypatch.setattr(scanner.settings, "scan_telemetry_interval_sec", 0)

    summary = __import__("asyncio").run(
        scanner.scan_dir(
            str(root),
            client,
            algo="sha256",
            hash_workers=2,
            hash_chunk_size=1024,
        )
    )

    assert summary["files"] == 2
    assert summary["hashed"] == 2
    assert summary["published"] == 2

    file_events = [
        event
        for batch in gateway.published_batches
        for event in batch["events"]
        if event.get("type") == "file.upsert"
    ]
    assert len(file_events) == 2
    assert {event["data"]["algo"] for event in file_events} == {"sha256"}
    assert all(event["data"]["hash"] for event in file_events)


def test_scan_dir_publishes_cancelled_when_task_is_interrupted(tmp_path, monkeypatch):
    """scan_dir should publish a terminal cancel event when interrupted mid-walk."""
    root = tmp_path / "root"
    root.mkdir()
    for idx in range(1024):
        (root / f"file-{idx}.txt").write_text("x")

    gateway = FakeGateway()
    client = FakeClient(gateway)

    monkeypatch.setattr(scanner.settings, "probe_batch", 64)
    monkeypatch.setattr(scanner.settings, "publish_batch", 64)
    monkeypatch.setattr(scanner.settings, "scan_telemetry_interval_sec", 0)

    async def run_case():
        task = asyncio.create_task(
            scanner.scan_dir(
                str(root),
                client,
                algo="sha256",
            )
        )

        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run_case())

    event_types = [
        event["type"]
        for batch in gateway.published_batches
        for event in batch["events"]
    ]
    assert "scan.started" in event_types
    assert "scan.cancelled" in event_types


def test_scan_dir_emits_hashing_telemetry_for_long_hashes(tmp_path, monkeypatch):
    """Long-running hashes should emit telemetry that shows hashing is actively in flight."""
    root = tmp_path / "root"
    root.mkdir()
    target = root / "large.bin"
    target.write_bytes(b"x" * 4096)

    gateway = FakeGateway()
    client = FakeClient(gateway)

    monkeypatch.setattr(scanner.settings, "probe_batch", 10)
    monkeypatch.setattr(scanner.settings, "publish_batch", 10)
    monkeypatch.setattr(scanner.settings, "scan_telemetry_interval_sec", 1)

    async def fake_hash_file_async(
        path, algorithm, *, chunk_size, executor=None, progress_callback=None
    ):
        await asyncio.sleep(1.1)
        if progress_callback is not None:
            await progress_callback(2048)
            await asyncio.sleep(0)
            await progress_callback(2048)
        return "deadbeef"

    monkeypatch.setattr(hashing, "hash_file_async", fake_hash_file_async)

    summary = asyncio.run(
        scanner.scan_dir(
            str(root),
            client,
            algo="sha256",
            hash_workers=1,
            hash_chunk_size=1024,
        )
    )

    assert summary["files"] == 1
    telemetry_events = [
        event
        for batch in gateway.published_batches
        for event in batch["events"]
        if event.get("type") == "scan.telemetry"
    ]
    assert telemetry_events
    hashing_telemetry = [
        event["data"]
        for event in telemetry_events
        if event.get("data", {}).get("phase") == "hashing"
        and event.get("data", {}).get("hash_jobs_active") == 1
    ]
    assert hashing_telemetry
    assert hashing_telemetry[0]["bytes_hashing"] == 4096
    assert hashing_telemetry[0]["current_path"] == str(target)
    assert hashing_telemetry[0]["current_size"] == 4096
    assert hashing_telemetry[0]["bytes_processed"] > 0
    assert hashing_telemetry[0]["current_offset"] > 0
