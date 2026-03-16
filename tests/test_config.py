__doc__ = """
Unit tests for snapfs.config.Settings.
"""

import importlib

import snapfs.config as config_module


def reload_settings(monkeypatch, **env):
    """Helper function to reload the Settings class with a modified environment."""
    for key in [
        "SNAPFS_GATEWAY",
        "SNAPFS_ALLOW_INSECURE_GATEWAY",
        "SNAPFS_API_KEY",
        "SNAPFS_SCANNER_TOKEN_SCOPES",
        "SNAPFS_SUBJECT",
        "SNAPFS_EVENTS_SUBJECT",
        "SNAPFS_PROBE_BATCH",
        "SNAPFS_PUBLISH_BATCH",
        "SNAPFS_SCAN_TELEMETRY_INTERVAL_SEC",
        "SNAPFS_AGENT_ID",
        "SNAPFS_SCAN_ROOT",
        "SNAPFS_SCANNER_ROOT",
        "SNAPFS_SCANNER_MAX_CONCURRENCY",
        "SNAPFS_SCANNER_TYPE",
        "SNAPFS_AGENT_WS_PATH",
        "SNAPFS_AGENT_PING_INTERVAL",
    ]:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    mod = importlib.reload(config_module)
    return mod.Settings()


def test_settings_defaults(monkeypatch):
    """Test that Settings reads the default values when no environment variables are set."""
    settings = reload_settings(monkeypatch)

    assert settings.gateway == "http://localhost:8080"
    assert settings.ws_path == "/ws/agents"
    assert settings.agent_id == "scanner-01"
    assert settings.scan_root == ""
    assert settings.scan_telemetry_interval_sec == 10


def test_settings_reads_environment(monkeypatch):
    """Test that Settings correctly reads values from environment variables."""
    settings = reload_settings(
        monkeypatch,
        SNAPFS_GATEWAY="https://tenant.snapfs.com",
        SNAPFS_AGENT_ID="scanner-99",
        SNAPFS_SCAN_ROOT="/data",
        SNAPFS_SCANNER_ROOT="/data/archive",
        SNAPFS_SCANNER_TYPE="NFS",
        SNAPFS_AGENT_WS_PATH="/ws/custom",
        SNAPFS_SCAN_TELEMETRY_INTERVAL_SEC="3",
        SNAPFS_ALLOW_INSECURE_GATEWAY="true",
    )

    assert settings.gateway == "https://tenant.snapfs.com"
    assert settings.agent_id == "scanner-99"
    assert settings.scan_root == "/data"
    assert settings.scanner_root == "/data/archive"
    assert settings.scanner_type == "nfs"
    assert settings.ws_path == "/ws/custom"
    assert settings.scan_telemetry_interval_sec == 3
    assert settings.allow_insecure_gateway is True
