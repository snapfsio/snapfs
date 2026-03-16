__doc__ = """
Unit tests for snapfs.agent.helpers.
"""

import pytest

from snapfs.agent import _enforce_gateway_tls, _join_ws, _scanner_token_scopes
from snapfs.client import SnapFS
from snapfs.gateway import _derive_gateway_ws


@pytest.mark.parametrize(
    ("gateway", "expected"),
    [
        ("http://localhost:8080", "ws://localhost:8080"),
        ("https://tenant.snapfs.com", "wss://tenant.snapfs.com"),
        ("ws://localhost:8000", "ws://localhost:8000"),
        ("wss://tenant.snapfs.com", "wss://tenant.snapfs.com"),
    ],
)
def test_derive_gateway_ws(gateway, expected):
    assert _derive_gateway_ws(gateway) == expected


def test_derive_gateway_ws_rejects_invalid_scheme():
    with pytest.raises(ValueError):
        _derive_gateway_ws("ftp://tenant.snapfs.com")


def test_join_ws_normalizes_slashes():
    assert (
        _join_ws("wss://tenant.snapfs.com/", "/ws/agents")
        == "wss://tenant.snapfs.com/ws/agents"
    )
    assert (
        _join_ws("ws://localhost:8000", "ws/agents") == "ws://localhost:8000/ws/agents"
    )


def test_enforce_gateway_tls_allows_localhost(monkeypatch):
    monkeypatch.setattr("snapfs.agent.settings.allow_insecure_gateway", False)
    client = SnapFS(gateway_url="http://localhost:8080")
    _enforce_gateway_tls(client)


def test_enforce_gateway_tls_rejects_insecure_remote(monkeypatch):
    monkeypatch.setattr("snapfs.agent.settings.allow_insecure_gateway", False)
    client = SnapFS(gateway_url="http://tenant.snapfs.com")
    with pytest.raises(RuntimeError, match="must use HTTPS"):
        _enforce_gateway_tls(client)


def test_scanner_token_scopes_splits_csv(monkeypatch):
    monkeypatch.setattr(
        "snapfs.agent.settings.scanner_token_scopes",
        "ingest:write, events:read , , browse:read",
    )
    assert _scanner_token_scopes() == ["ingest:write", "events:read", "browse:read"]
