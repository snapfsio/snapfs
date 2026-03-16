__doc__ = """
Unit tests for snapfs.agent.
"""

import asyncio
import aiohttp
import pytest

from snapfs import agent as agent_module


class FakeWS:
    """A fake WebSocket object for testing purposes."""

    def __init__(self, *, closed=False, send_exception=None):
        self.closed = closed
        self.send_exception = send_exception
        self.payloads = []

    async def send_json(self, payload):
        if self.send_exception:
            raise self.send_exception
        self.payloads.append(payload)


class FakeGateway:
    """A fake gateway client for testing purposes."""

    def __init__(self):
        self.token = None


class FakeClient:
    """A fake client for testing purposes."""

    def __init__(self):
        self.gateway = FakeGateway()


def test_backoff_is_bounded_and_uses_jitter(monkeypatch):
    """Test that _backoff returns a value that increases with the attempt number, includes
    jitter, and is capped at the maximum backoff time."""
    monkeypatch.setattr(agent_module.random, "random", lambda: 0.5)

    first = agent_module._backoff(0)
    later = agent_module._backoff(4)
    capped = agent_module._backoff(20)

    assert round(first, 3) == 0.5
    assert round(later, 3) == 8.0
    assert round(capped, 3) == 30.0


def test_send_returns_false_when_ws_already_closed():
    """Test that _send returns False if the WebSocket is already closed."""
    ws = FakeWS(closed=True)

    result = asyncio.run(agent_module._send(ws, {"type": "PING"}))

    assert result is False
    assert ws.payloads == []


def test_send_returns_true_on_success():
    """Test that _send returns True and sends the payload when the WebSocket is open."""
    ws = FakeWS()

    result = asyncio.run(agent_module._send(ws, {"type": "PING"}))

    assert result is True
    assert ws.payloads == [{"type": "PING"}]


@pytest.mark.parametrize(
    "exc",
    [
        aiohttp.ClientConnectionError("gone"),
        ConnectionResetError("reset"),
        RuntimeError("boom"),
    ],
)
def test_send_returns_false_on_exceptions(exc):
    """Test that _send returns False if an exception occurs while sending, simulating a broken
    WebSocket connection."""
    ws = FakeWS(send_exception=exc)

    result = asyncio.run(agent_module._send(ws, {"type": "PING"}))

    assert result is False


def test_handle_scan_requires_root(monkeypatch):
    """Test that _handle_scan sends a SCAN_ERROR if no scan root is provided in the message or
    configuration."""
    ws = FakeWS()
    sent = []

    async def fake_send(_ws, payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(agent_module, "_send", fake_send)

    async def run_case():
        await agent_module._handle_scan(
            msg={"command_id": "cmd-1", "target": {}},
            client=FakeClient(),
            ws=ws,
            default_root="",
            verbose=0,
            lock=asyncio.Lock(),
        )

    asyncio.run(run_case())

    assert sent == [
        {
            "type": "SCAN_ERROR",
            "command_id": "cmd-1",
            "error": "No scan root provided (target.root is null and SNAPFS_SCAN_ROOT is empty).",
        }
    ]


def test_handle_scan_rejects_missing_directory(monkeypatch):
    """Test that _handle_scan sends a SCAN_ERROR if the provided scan root does not exist or
    is not a directory."""
    ws = FakeWS()
    sent = []

    async def fake_send(_ws, payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(agent_module, "_send", fake_send)
    monkeypatch.setattr(agent_module.os.path, "isdir", lambda path: False)

    async def run_case():
        await agent_module._handle_scan(
            msg={"command_id": "cmd-2", "target": {"root": "/missing"}},
            client=FakeClient(),
            ws=ws,
            default_root="",
            verbose=0,
            lock=asyncio.Lock(),
        )

    asyncio.run(run_case())

    assert sent == [
        {
            "type": "SCAN_ERROR",
            "command_id": "cmd-2",
            "root": "/missing",
            "error": "Scan root does not exist or is not a directory: /missing",
        }
    ]


def test_handle_scan_rejects_when_busy(monkeypatch, tmp_path):
    """Test that _handle_scan sends a SCAN_ERROR if the agent is already running another
    scan (lock is"""
    ws = FakeWS()
    sent = []

    class BusyLock:
        def locked(self):
            return True

    async def fake_send(_ws, payload):
        sent.append(payload)
        return True

    monkeypatch.setattr(agent_module, "_send", fake_send)
    monkeypatch.setattr(agent_module.os.path, "isdir", lambda path: True)

    asyncio.run(
        agent_module._handle_scan(
            msg={"command_id": "cmd-3", "target": {"root": str(tmp_path)}},
            client=FakeClient(),
            ws=ws,
            default_root="",
            verbose=0,
            lock=BusyLock(),
        )
    )

    assert sent == [
        {
            "type": "SCAN_ERROR",
            "command_id": "cmd-3",
            "error": "Agent is busy running another scan.",
        }
    ]


def test_handle_scan_sends_complete_on_success(monkeypatch, tmp_path):
    """Test that _handle_scan sends a SCAN_COMPLETE message with the correct payload when the scan
    completes successfully."""
    ws = FakeWS()
    sent = []
    scan_calls = []
    times = iter([100.0, 104.25])

    async def fake_send(_ws, payload):
        sent.append(payload)
        return True

    async def fake_scan_dir(
        root, client, *, force=False, verbose=0, trigger_type="manual", schedule_id=None
    ):
        scan_calls.append(
            {
                "root": root,
                "client": client,
                "force": force,
                "verbose": verbose,
                "trigger_type": trigger_type,
                "schedule_id": schedule_id,
            }
        )
        return {"files": 5, "published": 5}

    monkeypatch.setattr(agent_module, "_send", fake_send)
    monkeypatch.setattr(agent_module.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(agent_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(agent_module.time, "time", lambda: next(times))

    client = FakeClient()

    async def run_case():
        await agent_module._handle_scan(
            msg={
                "command_id": "cmd-4",
                "target": {
                    "root": str(tmp_path),
                    "trigger_type": "schedule",
                    "schedule_id": "sch-1",
                },
                "options": {"force": True},
            },
            client=client,
            ws=ws,
            default_root="",
            verbose=2,
            lock=asyncio.Lock(),
        )

    asyncio.run(run_case())

    assert scan_calls == [
        {
            "root": str(tmp_path),
            "client": client,
            "force": True,
            "verbose": 2,
            "trigger_type": "schedule",
            "schedule_id": "sch-1",
        }
    ]
    assert sent == [
        {
            "type": "SCAN_COMPLETE",
            "command_id": "cmd-4",
            "root": str(tmp_path),
            "took_s": 4.25,
            "summary": {"files": 5, "published": 5},
            "trigger_type": "schedule",
            "schedule_id": "sch-1",
        }
    ]


def test_handle_scan_sends_error_on_scan_failure(monkeypatch, tmp_path):
    """Test that _handle_scan sends a SCAN_ERROR message with the error details if the
    scan_dir function raises an exception."""
    ws = FakeWS()
    sent = []

    async def fake_send(_ws, payload):
        sent.append(payload)
        return True

    async def fake_scan_dir(
        root, client, *, force=False, verbose=0, trigger_type="manual", schedule_id=None
    ):
        raise RuntimeError("hash failed")

    monkeypatch.setattr(agent_module, "_send", fake_send)
    monkeypatch.setattr(agent_module.os.path, "isdir", lambda path: True)
    monkeypatch.setattr(agent_module.scanner, "scan_dir", fake_scan_dir)

    async def run_case():
        await agent_module._handle_scan(
            msg={"command_id": "cmd-5", "target": {"root": str(tmp_path)}},
            client=FakeClient(),
            ws=ws,
            default_root="",
            verbose=0,
            lock=asyncio.Lock(),
        )

    asyncio.run(run_case())

    assert sent == [
        {
            "type": "SCAN_ERROR",
            "command_id": "cmd-5",
            "root": str(tmp_path),
            "error": "hash failed",
        }
    ]
