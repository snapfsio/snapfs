__doc__ = """
Unit tests for snapfs.gateway.
"""

import asyncio

import pytest

from snapfs import gateway as gateway_module
from snapfs.gateway import GatewayClient


class FakeResponse:
    """A fake response object that mimics aiohttp.ClientResponse for testing purposes."""

    def __init__(self, payload):
        self.payload = payload
        self.raise_called = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        self.raise_called = True

    async def json(self):
        return self.payload


class FakeSession:
    """A fake session object that mimics aiohttp.ClientSession for testing purposes."""

    def __init__(self, payload, calls):
        self.payload = payload
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse(self.payload)


def test_post_json_async_sets_bearer_header(monkeypatch):
    """Test that _post_json_async includes the Authorization header when a token is provided."""
    calls = []
    monkeypatch.setattr(
        gateway_module.aiohttp,
        "ClientSession",
        lambda: FakeSession({"ok": True}, calls),
    )

    client = GatewayClient(base_url="https://tenant.snapfs.com", token="jwt-token")
    result = asyncio.run(
        client._post_json_async(
            "/api/cache/batch", {"hello": "world"}, params={"x": "1"}
        )
    )

    assert result == {"ok": True}
    assert calls == [
        {
            "url": "https://tenant.snapfs.com/api/cache/batch",
            "json": {"hello": "world"},
            "params": {"x": "1"},
            "headers": {"Authorization": "Bearer jwt-token"},
            "timeout": 30.0,
        }
    ]


def test_post_json_async_omits_auth_without_token(monkeypatch):
    """Test that _post_json_async does not include the Authorization header when no token
    is provided."""
    calls = []
    monkeypatch.setattr(
        gateway_module.aiohttp,
        "ClientSession",
        lambda: FakeSession({"ok": True}, calls),
    )

    client = GatewayClient(base_url="https://tenant.snapfs.com", token=None)
    asyncio.run(client._post_json_async("/api/cache/batch", {"hello": "world"}))

    assert calls[0]["headers"] == {}


def test_cache_probe_batch_async_uses_cache_endpoint(monkeypatch):
    """Test that cache_probe_batch_async sends the correct payload to the cache batch endpoint."""
    recorded = {}

    async def fake_post_json_async(path, payload, timeout=30.0, params=None):
        recorded["path"] = path
        recorded["payload"] = payload
        recorded["params"] = params
        return [{"status": "HIT"}]

    client = GatewayClient(base_url="https://tenant.snapfs.com")
    monkeypatch.setattr(client, "_post_json_async", fake_post_json_async)

    probes = [{"path": "/data/file.txt", "size": 1, "mtime": 2}]
    result = asyncio.run(client.cache_probe_batch_async(probes))

    assert result == [{"status": "HIT"}]
    assert recorded == {
        "path": "/api/cache/batch",
        "payload": probes,
        "params": None,
    }


def test_publish_events_async_uses_subject_override(monkeypatch):
    """Test that publish_events_async sends events to the specified subject when provided."""
    recorded = {}

    async def fake_post_json_async(path, payload, timeout=30.0, params=None):
        recorded["path"] = path
        recorded["payload"] = payload
        recorded["params"] = params
        return {"accepted": 1}

    client = GatewayClient(base_url="https://tenant.snapfs.com", subject="snapfs.files")
    monkeypatch.setattr(client, "_post_json_async", fake_post_json_async)

    events = [{"type": "file.upsert"}]
    result = asyncio.run(client.publish_events_async(events, subject="snapfs.events"))

    assert result == {"accepted": 1}
    assert recorded == {
        "path": "/api/ingest",
        "payload": {"events": events},
        "params": {"subject": "snapfs.events"},
    }


def test_exchange_scanner_token_async_uses_api_key_bearer(monkeypatch):
    """Test that exchange_scanner_token_async sends the API key in the Authorization header
    and returns the access token."""
    calls = []
    monkeypatch.setattr(
        gateway_module.aiohttp,
        "ClientSession",
        lambda: FakeSession({"accessToken": "scanner-jwt"}, calls),
    )

    client = GatewayClient(base_url="https://tenant.snapfs.com")
    token = asyncio.run(
        client.exchange_scanner_token_async(api_key="sfk_test", scopes=["ingest:write"])
    )

    assert token == "scanner-jwt"
    assert calls == [
        {
            "url": "https://tenant.snapfs.com/api/auth/token",
            "json": {"scopes": ["ingest:write"]},
            "headers": {"Authorization": "Bearer sfk_test"},
            "timeout": 15.0,
        }
    ]


def test_exchange_scanner_token_async_requires_access_token(monkeypatch):
    """Test that exchange_scanner_token_async raises an error if the response does not contain
    an accessToken."""
    monkeypatch.setattr(
        gateway_module.aiohttp,
        "ClientSession",
        lambda: FakeSession({"token": "missing"}, []),
    )

    client = GatewayClient(base_url="https://tenant.snapfs.com")
    with pytest.raises(RuntimeError, match="missing accessToken"):
        asyncio.run(client.exchange_scanner_token_async(api_key="sfk_test"))
