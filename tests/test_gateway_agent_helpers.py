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
    """Test that _derive_gateway_ws correctly derives the WebSocket URL from the gateway URL."""
    assert _derive_gateway_ws(gateway) == expected


def test_derive_gateway_ws_rejects_invalid_scheme():
    """Test that _derive_gateway_ws raises a ValueError if the gateway URL has an unsupported
    scheme."""
    with pytest.raises(ValueError):
        _derive_gateway_ws("ftp://tenant.snapfs.com")


def test_join_ws_normalizes_slashes():
    """Test that _join_ws correctly joins the base WebSocket URL and path, normalizing slashes."""
    assert (
        _join_ws("wss://tenant.snapfs.com/", "/ws/agents")
        == "wss://tenant.snapfs.com/ws/agents"
    )
    assert (
        _join_ws("ws://localhost:8000", "ws/agents") == "ws://localhost:8000/ws/agents"
    )


def test_enforce_gateway_tls_allows_localhost(monkeypatch):
    """Test that _enforce_gateway_tls does not raise an error for localhost URLs."""
    monkeypatch.setattr("snapfs.agent.settings.allow_insecure_gateway", False)
    client = SnapFS(gateway_url="http://localhost:8080")
    _enforce_gateway_tls(client)


def test_enforce_gateway_tls_rejects_insecure_remote(monkeypatch):
    """Test that _enforce_gateway_tls raises a RuntimeError for non-localhost URLs when
    allow_insecure_gateway is False."""
    monkeypatch.setattr("snapfs.agent.settings.allow_insecure_gateway", False)
    client = SnapFS(gateway_url="http://tenant.snapfs.com")
    with pytest.raises(RuntimeError, match="must use HTTPS"):
        _enforce_gateway_tls(client)


def test_scanner_token_scopes_splits_csv(monkeypatch):
    """Test that _scanner_token_scopes correctly splits the CSV string from settings into
    a list of scopes."""
    monkeypatch.setattr(
        "snapfs.agent.settings.scanner_token_scopes",
        "ingest:write, events:read , , browse:read",
    )
    assert _scanner_token_scopes() == ["ingest:write", "events:read", "browse:read"]
