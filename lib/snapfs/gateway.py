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

import aiohttp

from .config import DEFAULT_GATEWAY, DEFAULT_SUBJECT, DEFAULT_TOKEN


class GatewayClient:
    """
    Low-level HTTP client for the SnapFS gateway.

    Responsibilities:
      - Base URL / subject
      - Optional Bearer token
      - POST helpers for cache, ingest, and query endpoints
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        subject: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.base_url = (base_url or DEFAULT_GATEWAY).rstrip("/")
        self.subject = subject or DEFAULT_SUBJECT
        self.token = token or DEFAULT_TOKEN

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
        """
        Helper for sync callers.

        Intended for CLI / scripts. Library users can call the `*_async`
        variants directly if they're already in an event loop.
        """
        return asyncio.run(coro)

    async def cache_probe_batch_async(
        self, probes: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Probe cache for a batch of file metadata records.

        `probes` is a list of dicts with keys like path / size / mtime / inode / dev.
        """
        result = await self._post_json_async("/cache/batch", probes)
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
        """
        params = {"subject": subject or self.subject}
        payload = {"events": events}
        return await self._post_json_async("/ingest", payload, params=params)

    def publish_events(
        self,
        events: List[Dict[str, Any]],
        *,
        subject: Optional[str] = None,
    ) -> Any:
        return self._run(self.publish_events_async(events, subject=subject))

    async def sql_async(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute raw SQL via the SnapFS gateway.

        Assumes a POST /query/sql endpoint that accepts:
            { "sql": "...", "params": {...} }

        And returns something like:
            { "rows": [ {..}, {..}, ... ] }
        """
        payload: Dict[str, Any] = {"sql": sql}
        if params:
            payload["params"] = params

        result = await self._post_json_async("/query/sql", payload)
        rows = result.get("rows", result)
        if isinstance(rows, dict):
            return [rows]
        return rows  # type: ignore[return-value]

    def sql(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        return self._run(self.sql_async(sql, params=params))
