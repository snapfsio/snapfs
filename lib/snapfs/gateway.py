#!/usr/bin/env python3
#
# Copyright (c) 2025 SnapFS, LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import asyncio
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import aiohttp

from .config import settings


def _derive_gateway_ws(gateway: str) -> str:
    """Derive the WebSocket gateway URL from a single gateway URL."""
    u = urlparse(gateway)

    if not u.scheme or not u.netloc:
        raise ValueError(f"Invalid gateway URL: {gateway!r}")

    scheme = u.scheme.lower()
    if scheme == "http":
        ws_scheme = "ws"
    elif scheme == "https":
        ws_scheme = "wss"
    elif scheme in ("ws", "wss"):
        ws_scheme = scheme
    else:
        raise ValueError(f"Unsupported gateway scheme: {scheme!r}")

    # Preserve netloc exactly (including explicit port if provided).
    # Drop path/query/fragment because ws_path is configured separately.
    return urlunparse((ws_scheme, u.netloc, "", "", "", ""))


class GatewayClient:
    """
    Low-level HTTP client for the SnapFS gateway.

    Responsibilities:
      - Base URL / subject
      - Optional Bearer token
      - POST helpers for cache and ingest endpoints
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        subject: Optional[str] = None,
        token: Optional[str] = None,
    ):
        """
        :param base_url: Base URL of the SnapFS gateway.
        :param subject: Optional default subject for ingest routing.
        :param token: Optional auth token for the gateway.
        """
        self.base_url = (base_url or settings.gateway).rstrip("/")
        self.ws_url = _derive_gateway_ws(self.base_url)
        self.subject = subject or settings.subject
        self.token = token if token is not None else settings.token

    async def _post_json_async(
        self,
        path: str,
        payload: Any,
        timeout: float = 30.0,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        headers: Dict[str, str] = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                url,
                json=payload,
                params=params,
                headers=headers,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                return await resp.json()

    def _run(self, coro):
        """Helper to run an async coroutine in a synchronous context."""
        return asyncio.run(coro)

    async def cache_probe_batch_async(
        self, probes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Probe cache for a batch of file metadata records.

        :param probes: List of file metadata probe dicts.
        """
        result = await self._post_json_async("/api/cache/batch", probes)
        # expect result to already be a list[dict]
        return result  # type: ignore[return-value]

    def cache_probe_batch(self, probes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self._run(self.cache_probe_batch_async(probes))

    async def publish_events_async(
        self,
        events: List[Dict[str, Any]],
        *,
        subject: Optional[str] = None,
    ) -> Any:
        """
        Publish a list of events to the ingest endpoint.

        :param events: List of event dicts to publish.
        :param subject: Optional subject for routing (overrides default).
        """
        params = {"subject": subject or self.subject}
        payload = {"events": events}
        return await self._post_json_async("/api/ingest", payload, params=params)

    def publish_events(
        self,
        events: List[Dict[str, Any]],
        *,
        subject: Optional[str] = None,
    ) -> Any:
        """
        Publish a list of events to the ingest endpoint.

        :param events: List of event dicts to publish.
        :param subject: Optional subject for routing (overrides default).
        """
        return self._run(self.publish_events_async(events, subject=subject))

    async def exchange_scanner_token_async(
        self,
        *,
        api_key: str,
        scopes: Optional[List[str]] = None,
        timeout: float = 15.0,
    ) -> str:
        """Exchange an API key for a short-lived scanner JWT.

        :param api_key: Raw API key used as bearer credential.
        :param scopes: Optional scope narrowing list.
        :param timeout: HTTP timeout in seconds.
        :return: Scanner JWT access token.
        """
        payload: Dict[str, Any] = {}
        if scopes:
            payload["scopes"] = scopes

        url = f"{self.base_url}/api/auth/token"
        headers = {"Authorization": f"Bearer {api_key}"}

        async with aiohttp.ClientSession() as sess:
            async with sess.post(
                url,
                json=payload,
                headers=headers,
                timeout=timeout,
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        token = body.get("accessToken")
        if not token:
            raise RuntimeError("Gateway /api/auth/token response missing accessToken")
        return str(token)
