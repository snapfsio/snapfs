__doc__ = """
Unit tests for snapfs.cli.
"""

import asyncio
import pytest

import json

import click
from click.testing import CliRunner

from snapfs import cli as cli_module


class FakeGateway:
    """Simulated SnapFS gateway client with token exchange tracking."""

    def __init__(self):
        self.token = None
        self.exchange_calls = []

    async def exchange_scanner_token_async(self, *, api_key, scopes=None):
        self.exchange_calls.append({"api_key": api_key, "scopes": scopes})
        return "jwt-token"


class FakeSnapFS:
    """Simulated SnapFS client with gateway/auth tracking for CLI tests."""

    instances = []

    def __init__(self, gateway_url=None, token=None):
        self.gateway_url = gateway_url
        self.gateway = FakeGateway()
        self.gateway.token = token
        FakeSnapFS.instances.append(self)


class DummyError(Exception):
    """Generic error for testing exception handling."""

    pass


def test_require_gateway_raises_click_exception():
    """Test that _require_gateway raises a ClickException when no gateway URL is provided."""
    with pytest.raises(click.ClickException, match="Missing --gateway"):
        cli_module._require_gateway("")


def test_auto_auth_scanner_client_uses_api_key(monkeypatch):
    """Test that _auto_auth_scanner_client exchanges an API key for a token when no
    explicit token is provided."""
    client = FakeSnapFS("https://tenant.snapfs.com", None)
    monkeypatch.setattr(cli_module.settings, "api_key", "sfk_test")
    monkeypatch.setattr(
        cli_module.settings, "scanner_token_scopes", "ingest:write,events:read"
    )

    cli_module._auto_auth_scanner_client(client, explicit_token=None)

    assert client.gateway.token == "jwt-token"
    assert client.gateway.exchange_calls == [
        {"api_key": "sfk_test", "scopes": ["ingest:write", "events:read"]}
    ]


def test_auto_auth_scanner_client_skips_when_explicit_token(monkeypatch):
    """Test that _auto_auth_scanner_client does not exchange the token when an explicit token
    is provided."""
    client = FakeSnapFS("https://tenant.snapfs.com", "explicit-token")
    monkeypatch.setattr(cli_module.settings, "api_key", "sfk_test")

    cli_module._auto_auth_scanner_client(client, explicit_token="explicit-token")

    assert client.gateway.token == "explicit-token"
    assert client.gateway.exchange_calls == []


def test_scan_command_accepts_api_key_option(monkeypatch, tmp_path):
    """The scan command should accept --api-key and exchange it for a scanner token."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()
    calls = []

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        calls.append({"path": path, "client": client})
        return {"scan_id": "scan-123"}

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.setattr(cli_module.settings, "scanner_token_scopes", "ingest:write")

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path),
            "--gateway",
            "https://tenant.snapfs.com",
            "--api-key",
            "sfk_test",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"path": str(path.resolve()), "client": FakeSnapFS.instances[0]}]
    assert FakeSnapFS.instances[0].gateway.token == "jwt-token"
    assert FakeSnapFS.instances[0].gateway.exchange_calls == [
        {"api_key": "sfk_test", "scopes": ["ingest:write"]}
    ]


def test_scan_command_prefers_explicit_token_over_api_key(monkeypatch, tmp_path):
    """The scan command should not exchange the API key when an explicit token is provided."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        return {"scan_id": "scan-123"}

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path),
            "--gateway",
            "https://tenant.snapfs.com",
            "--api-key",
            "sfk_test",
            "--token",
            "explicit-token",
        ],
    )

    assert result.exit_code == 0, result.output
    assert FakeSnapFS.instances[0].gateway.token == "explicit-token"
    assert FakeSnapFS.instances[0].gateway.exchange_calls == []


def test_cli_help_does_not_list_query_command():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["--help"])

    assert result.exit_code == 0, result.output
    assert " query " not in result.output
    assert "scan" in result.output
    assert "agent" in result.output


def test_scan_help_does_not_expose_localhost_gateway_default():
    runner = CliRunner()

    result = runner.invoke(cli_module.cli, ["scan", "--help"])

    assert result.exit_code == 0, result.output
    assert "localhost:8080" not in result.output
    assert "SnapFS gateway base URL." in result.output


def test_scan_command_requires_gateway(monkeypatch, tmp_path):
    runner = CliRunner()
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.delenv("SNAPFS_GATEWAY", raising=False)
    monkeypatch.delenv("SNAPFS_API_KEY", raising=False)
    monkeypatch.delenv("SNAPFS_TOKEN", raising=False)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(cli_module.cli, ["scan", str(path)])

    assert result.exit_code != 0
    assert "Missing --gateway (or SNAPFS_GATEWAY)." in result.output


def test_scan_command_passes_flags_and_prints_summary(monkeypatch, tmp_path):
    """Test that the 'scan' command passes the correct flags to scan_dir and prints the
    summary as JSON."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()
    calls = []

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        calls.append(
            {
                "path": path,
                "client": client,
                "force": force,
                "verbose": verbose,
                "trigger_type": trigger_type,
                "schedule_id": schedule_id,
                "algo": algo,
                "hash_workers": hash_workers,
                "hash_chunk_size": hash_chunk_size,
            }
        )
        return {
            "files": 2,
            "cache_hits": 1,
            "hashed": 1,
            "published": 2,
            "scan_id": "scan-123",
        }

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        ["scan", str(path), "--gateway", "https://tenant.snapfs.com", "--force", "-v"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output.strip()) == {
        "cache_hits": 1,
        "files": 2,
        "hashed": 1,
        "published": 2,
        "scan_id": "scan-123",
    }
    assert calls == [
        {
            "path": str(path.resolve()),
            "client": FakeSnapFS.instances[0],
            "force": True,
            "verbose": 1,
            "trigger_type": "manual",
            "schedule_id": None,
            "algo": "sha1",
            "hash_workers": 1,
            "hash_chunk_size": 1048576,
        }
    ]


def test_scan_command_wraps_not_a_directory(monkeypatch, tmp_path):
    """Test that the 'scan' command wraps NotADirectoryError and prints an error message."""
    runner = CliRunner()

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        raise NotADirectoryError(path)

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        ["scan", str(path), "--gateway", "https://tenant.snapfs.com"],
    )

    assert result.exit_code != 0
    assert f"Not a directory: {path.resolve()}" in result.output


def test_agent_command_passes_values(monkeypatch):
    """Test that the 'agent' command passes the correct values to run_agent."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()
    calls = []

    async def fake_run_agent(*, client, agent_id=None, scan_root=None, verbose=0):
        calls.append(
            {
                "client": client,
                "agent_id": agent_id,
                "scan_root": scan_root,
                "verbose": verbose,
            }
        )

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    result = runner.invoke(
        cli_module.cli,
        [
            "agent",
            "--gateway",
            "https://tenant.snapfs.com",
            "--agent-id",
            "scanner-42",
            "--root",
            "/data",
            "-vv",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "client": FakeSnapFS.instances[0],
            "agent_id": "scanner-42",
            "scan_root": "/data",
            "verbose": 2,
        }
    ]
    assert cli_module.settings.hash_algo == "sha1"
    assert cli_module.settings.hash_workers == 1
    assert cli_module.settings.hash_chunk_size == 1048576


def test_agent_command_accepts_api_key_option(monkeypatch):
    """The agent command should accept --api-key and exchange it for a scanner token."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()
    calls = []

    async def fake_run_agent(*, client, agent_id=None, scan_root=None, verbose=0):
        calls.append(
            {
                "client": client,
                "agent_id": agent_id,
                "scan_root": scan_root,
                "verbose": verbose,
            }
        )

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.setattr(cli_module.settings, "scanner_token_scopes", "ingest:write")

    result = runner.invoke(
        cli_module.cli,
        [
            "agent",
            "--gateway",
            "https://tenant.snapfs.com",
            "--api-key",
            "sfk_test",
            "--agent-id",
            "scanner-42",
            "--root",
            "/data",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        {
            "client": FakeSnapFS.instances[0],
            "agent_id": "scanner-42",
            "scan_root": "/data",
            "verbose": 0,
        }
    ]
    assert FakeSnapFS.instances[0].gateway.token == "jwt-token"
    assert FakeSnapFS.instances[0].gateway.exchange_calls == [
        {"api_key": "sfk_test", "scopes": ["ingest:write"]}
    ]


def test_agent_command_prefers_explicit_token_over_api_key(monkeypatch):
    """The agent command should not exchange the API key when an explicit token is provided."""
    runner = CliRunner()
    FakeSnapFS.instances.clear()

    async def fake_run_agent(*, client, agent_id=None, scan_root=None, verbose=0):
        return None

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    result = runner.invoke(
        cli_module.cli,
        [
            "agent",
            "--gateway",
            "https://tenant.snapfs.com",
            "--api-key",
            "sfk_test",
            "--token",
            "explicit-token",
            "--root",
            "/data",
        ],
    )

    assert result.exit_code == 0, result.output
    assert FakeSnapFS.instances[0].gateway.token == "explicit-token"
    assert FakeSnapFS.instances[0].gateway.exchange_calls == []


def test_scan_command_accepts_algo_override(monkeypatch, tmp_path):
    """The scan command should forward a selected hash algorithm to the scanner."""
    runner = CliRunner()
    calls = []

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        calls.append(
            {
                "algo": algo,
                "hash_workers": hash_workers,
                "hash_chunk_size": hash_chunk_size,
            }
        )
        return {
            "files": 0,
            "cache_hits": 0,
            "hashed": 0,
            "published": 0,
            "scan_id": "scan-0",
        }

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path),
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "sha256",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"algo": "sha256", "hash_workers": 1, "hash_chunk_size": 1048576}]


def test_scan_command_rejects_unknown_algo(monkeypatch, tmp_path):
    """The CLI should fail fast on an unsupported hash algorithm."""
    runner = CliRunner()
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path),
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "bogus",
        ],
    )

    assert result.exit_code != 0
    assert "Unsupported hash algorithm 'bogus'" in result.output


def test_scan_command_accepts_hash_performance_overrides(monkeypatch, tmp_path):
    """The scan command should forward worker and chunk-size overrides."""
    runner = CliRunner()
    calls = []

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        calls.append(
            {
                "algo": algo,
                "hash_workers": hash_workers,
                "hash_chunk_size": hash_chunk_size,
            }
        )
        return {
            "files": 0,
            "cache_hits": 0,
            "hashed": 0,
            "published": 0,
            "scan_id": "scan-0",
        }

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path),
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "sha256",
            "--workers",
            "3",
            "--hash-chunk-size",
            "2097152",
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [{"algo": "sha256", "hash_workers": 3, "hash_chunk_size": 2097152}]


def test_agent_command_sets_hash_performance_settings(monkeypatch):
    """The agent command should store hash tuning overrides in settings."""
    runner = CliRunner()

    async def fake_run_agent(*, client, agent_id=None, scan_root=None, verbose=0):
        return None

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cli_module.settings, "api_key", None)

    result = runner.invoke(
        cli_module.cli,
        [
            "agent",
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "sha256",
            "--workers",
            "4",
            "--hash-chunk-size",
            "2097152",
        ],
    )

    assert result.exit_code == 0, result.output
    assert cli_module.settings.hash_algo == "sha256"
    assert cli_module.settings.hash_workers == 4
    assert cli_module.settings.hash_chunk_size == 2097152


def test_scan_command_uses_settings_defaults_until_cli_overridden(
    monkeypatch, tmp_path
):
    """Scan should use current settings defaults unless explicit CLI overrides are provided."""
    runner = CliRunner()
    calls = []

    async def fake_scan_dir(
        path,
        client,
        *,
        force=False,
        verbose=0,
        trigger_type="manual",
        schedule_id=None,
        algo=None,
        hash_workers=None,
        hash_chunk_size=None,
    ):
        calls.append(
            {
                "algo": algo,
                "hash_workers": hash_workers,
                "hash_chunk_size": hash_chunk_size,
            }
        )
        return {
            "files": 0,
            "cache_hits": 0,
            "hashed": 0,
            "published": 0,
            "scan_id": "scan-0",
        }

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.scanner, "scan_dir", fake_scan_dir)
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.setattr(cli_module.settings, "hash_algo", "sha256")
    monkeypatch.setattr(cli_module.settings, "hash_workers", 3)
    monkeypatch.setattr(cli_module.settings, "hash_chunk_size", 2097152)

    path_arg = tmp_path / "root"
    path_arg.mkdir()

    default_result = runner.invoke(
        cli_module.cli,
        ["scan", str(path_arg), "--gateway", "https://tenant.snapfs.com"],
    )
    override_result = runner.invoke(
        cli_module.cli,
        [
            "scan",
            str(path_arg),
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "sha1",
            "--workers",
            "5",
            "--hash-chunk-size",
            "4096",
        ],
    )

    assert default_result.exit_code == 0, default_result.output
    assert override_result.exit_code == 0, override_result.output
    assert calls == [
        {"algo": "sha256", "hash_workers": 3, "hash_chunk_size": 2097152},
        {"algo": "sha1", "hash_workers": 5, "hash_chunk_size": 4096},
    ]


def test_agent_command_uses_settings_defaults_until_cli_overridden(monkeypatch):
    """Agent should persist current settings defaults unless explicit CLI overrides are provided."""
    runner = CliRunner()

    async def fake_run_agent(*, client, agent_id=None, scan_root=None, verbose=0):
        return None

    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)
    monkeypatch.setattr(cli_module.agent_mod, "run_agent", fake_run_agent)
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.setattr(cli_module.settings, "hash_algo", "sha256")
    monkeypatch.setattr(cli_module.settings, "hash_workers", 3)
    monkeypatch.setattr(cli_module.settings, "hash_chunk_size", 2097152)

    default_result = runner.invoke(
        cli_module.cli,
        ["agent", "--gateway", "https://tenant.snapfs.com"],
    )

    assert default_result.exit_code == 0, default_result.output
    assert cli_module.settings.hash_algo == "sha256"
    assert cli_module.settings.hash_workers == 3
    assert cli_module.settings.hash_chunk_size == 2097152

    override_result = runner.invoke(
        cli_module.cli,
        [
            "agent",
            "--gateway",
            "https://tenant.snapfs.com",
            "--algo",
            "sha1",
            "--workers",
            "5",
            "--hash-chunk-size",
            "4096",
        ],
    )

    assert override_result.exit_code == 0, override_result.output
    assert cli_module.settings.hash_algo == "sha1"
    assert cli_module.settings.hash_workers == 5
    assert cli_module.settings.hash_chunk_size == 4096


def test_run_cancellable_waits_for_cancel_cleanup():
    """Ctrl+C handling should let coroutine cancellation cleanup finish before exiting."""
    cleanup = {"started": False, "finished": False}

    async def job():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cleanup["started"] = True
            await asyncio.sleep(0)
            cleanup["finished"] = True
            raise

    original_new_event_loop = cli_module.asyncio.new_event_loop
    original_all_tasks = cli_module.asyncio.all_tasks

    class InterruptingLoop:
        def __init__(self):
            self._loop = original_new_event_loop()
            self._calls = 0

        def create_task(self, coro):
            return self._loop.create_task(coro)

        def run_until_complete(self, arg):
            self._calls += 1
            if self._calls == 1:
                self._loop.call_soon(arg.cancel)
                self._loop.run_until_complete(asyncio.sleep(0))
                raise KeyboardInterrupt()
            return self._loop.run_until_complete(arg)

        def shutdown_asyncgens(self):
            return self._loop.shutdown_asyncgens()

        def close(self):
            return self._loop.close()

    holder = {}

    def fake_new_event_loop():
        wrapper = InterruptingLoop()
        holder["wrapper"] = wrapper
        return wrapper

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(cli_module.asyncio, "new_event_loop", fake_new_event_loop)
    monkeypatch.setattr(cli_module.asyncio, "set_event_loop", lambda loop: None)
    monkeypatch.setattr(
        cli_module.asyncio,
        "all_tasks",
        lambda loop: original_all_tasks(holder["wrapper"]._loop),
    )

    try:
        with pytest.raises(KeyboardInterrupt):
            cli_module._run_cancellable(job())
    finally:
        monkeypatch.undo()

    assert cleanup == {"started": True, "finished": True}


def test_scan_command_wraps_keyboard_interrupt(monkeypatch, tmp_path):
    """The scan command should report a clean interruption instead of leaving a traceback."""
    runner = CliRunner()

    def fake_run_cancellable(_coro):
        _coro.close()
        raise KeyboardInterrupt()

    monkeypatch.setattr(cli_module, "_run_cancellable", fake_run_cancellable)
    monkeypatch.setattr(cli_module.settings, "api_key", None)
    monkeypatch.setattr(cli_module, "SnapFS", FakeSnapFS)

    path = tmp_path / "root"
    path.mkdir()

    result = runner.invoke(
        cli_module.cli,
        ["scan", str(path), "--gateway", "https://tenant.snapfs.com"],
    )

    assert result.exit_code != 0
    assert "Scan interrupted." in result.output
