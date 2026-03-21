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
import contextlib
import logging
import os
import random
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import aiohttp

from . import scanner
from .client import SnapFS
from .config import settings

logger = logging.getLogger(__name__)


def _join_ws(base: str, path: str) -> str:
    """Join base WS URL and path correctly."""
    base = base.rstrip("/")
    path = path if path.startswith("/") else f"/{path}"
    return base + path


def _backoff(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with jitter."""
    exp = min(cap, base * (2 ** max(0, attempt)))
    return exp * (0.7 + random.random() * 0.6)


async def _send(ws: aiohttp.ClientWebSocketResponse, payload: Dict[str, Any]) -> bool:
    """Send a JSON payload over the WS.

    Returns True when sent successfully, False when the socket is already closing/closed
    or a transport-level disconnect happens while sending.
    """
    if ws.closed:
        logger.debug("WS already closed; skipping send payload=%r", payload)
        return False

    try:
        await ws.send_json(payload)
        return True
    except (aiohttp.ClientConnectionError, ConnectionResetError) as e:
        logger.debug("WS send dropped during disconnect: %r payload=%r", e, payload)
        return False
    except Exception as e:
        logger.warning("WS send failed: %r payload=%r", e, payload)
        return False


def _enforce_gateway_tls(client: SnapFS) -> None:
    """Refuse insecure remote gateway URLs unless explicitly allowed."""
    if settings.allow_insecure_gateway:
        return

    parsed = urlparse(client.gateway.base_url)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()

    if host in {"localhost", "127.0.0.1", "::1"}:
        return

    if scheme != "https":
        raise RuntimeError(
            "Remote scanner gateway must use HTTPS. "
            "Set SNAPFS_ALLOW_INSECURE_GATEWAY=1 only for controlled dev environments."
        )


def _scanner_token_scopes() -> List[str]:
    """Return scanner token scopes requested from config."""
    raw = (settings.scanner_token_scopes or "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _handle_scan(
    *,
    msg: Dict[str, Any],
    client: SnapFS,
    ws: aiohttp.ClientWebSocketResponse,
    default_root: str,
    verbose: int,
    lock: asyncio.Lock,
) -> None:
    """Handle SCAN_TARGET command.

    :param msg: The SCAN_TARGET message dictionary.
    :param client: SnapFS client instance.
    :param ws: WebSocket connection to the gateway.
    :param default_root: Default scan root if not specified in the message.
    :param verbose: Verbosity level.
    :param lock: Asyncio lock to prevent concurrent scans.
    """
    command_id = msg.get("command_id")
    target = msg.get("target") or {}
    options = msg.get("options") or {}

    root = target.get("root") or default_root
    force = bool(options.get("force", False))
    trigger_type = target.get("trigger_type") or "manual"
    schedule_id = target.get("schedule_id")

    if not root:
        await _send(
            ws,
            {
                "type": "SCAN_ERROR",
                "command_id": command_id,
                "error": "No scan root provided (target.root is null and SNAPFS_SCAN_ROOT is empty).",
            },
        )
        return

    if not os.path.isdir(root):
        await _send(
            ws,
            {
                "type": "SCAN_ERROR",
                "command_id": command_id,
                "root": root,
                "error": f"Scan root does not exist or is not a directory: {root}",
            },
        )
        return

    if lock.locked():
        await _send(
            ws,
            {
                "type": "SCAN_ERROR",
                "command_id": command_id,
                "error": "Agent is busy running another scan.",
            },
        )
        return

    async with lock:
        started = time.time()
        try:
            if verbose:
                logger.info(
                    "scan command_id=%s root=%s force=%s trigger_type=%s schedule_id=%s",
                    command_id,
                    root,
                    force,
                    trigger_type,
                    schedule_id,
                )

            summary = await scanner.scan_dir(
                root,
                client,
                force=force,
                verbose=verbose,
                trigger_type=trigger_type,
                schedule_id=schedule_id,
            )

            await _send(
                ws,
                {
                    "type": "SCAN_COMPLETE",
                    "command_id": command_id,
                    "root": root,
                    "took_s": round(time.time() - started, 3),
                    "summary": summary,
                    "trigger_type": trigger_type,
                    "schedule_id": schedule_id,
                },
            )
        except Exception as e:
            logger.exception("scan failed command_id=%s root=%s", command_id, root)
            await _send(
                ws,
                {
                    "type": "SCAN_ERROR",
                    "command_id": command_id,
                    "root": root,
                    "error": str(e),
                },
            )


async def run_agent(
    client: SnapFS,
    agent_id: Optional[str] = None,
    scan_root: Optional[str] = None,
    verbose: int = 0,
) -> None:
    """
    Connect to gateway WS (/ws/agents) and execute SCAN_TARGET commands.

    :param client: SnapFS client instance
    :param agent_id: Optional agent identifier (overrides SNAPFS_AGENT_ID)
    :param scan_root: Optional default scan root (overrides SNAPFS_SCAN_ROOT)
    :param verbose: Verbosity level (0=quiet, 1=info)
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    gateway_ws = client.gateway.ws_url
    agent_id_eff = agent_id or settings.agent_id
    scan_root_eff = scan_root or settings.scan_root
    if not scan_root_eff:
        logger.warning("No default scan root set; SCAN_TARGET must specify root")

    ws_url = _join_ws(gateway_ws, settings.ws_path)

    logger.info("SnapFS agent starting agent_id=%r ws=%s", agent_id_eff, gateway_ws)

    _enforce_gateway_tls(client)

    lock = asyncio.Lock()
    attempt = 0

    while True:
        try:
            # If API key is configured, refresh scanner token before each connect/reconnect.
            if settings.api_key:
                scopes = _scanner_token_scopes()
                client.gateway.token = (
                    await client.gateway.exchange_scanner_token_async(
                        api_key=settings.api_key,
                        scopes=scopes or None,
                    )
                )

            ws_headers: Dict[str, str] = {}
            if client.gateway.token:
                ws_headers["Authorization"] = f"Bearer {client.gateway.token}"

            timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.ws_connect(
                    ws_url, heartbeat=30, headers=ws_headers
                ) as ws:
                    attempt = 0
                    heartbeat_interval = max(5, int(settings.ping_interval))
                    last_pong_mono = time.monotonic()
                    heartbeat_overdue_logged = False

                    await ws.send_json(
                        {
                            "type": "AGENT_HELLO",
                            "agent_id": agent_id_eff,
                            "agent_type": "scanner",
                            "version": "snapfs",
                            "capabilities": ["scan.fs"],
                            "root_path": scan_root_eff or settings.scanner_root or None,
                            "scanner_type": settings.scanner_type,
                            "max_concurrency": settings.scanner_max_concurrency,
                        }
                    )
                    logger.info(
                        "agent connected agent_id=%s ws=%s heartbeat_interval=%ss",
                        agent_id_eff,
                        ws_url,
                        heartbeat_interval,
                    )

                    async def pinger():
                        nonlocal last_pong_mono, heartbeat_overdue_logged
                        while True:
                            await asyncio.sleep(heartbeat_interval)
                            overdue_sec = time.monotonic() - last_pong_mono
                            if overdue_sec > (heartbeat_interval * 2):
                                if not heartbeat_overdue_logged:
                                    logger.warning(
                                        "heartbeat overdue agent_id=%s overdue_s=%.1f interval_s=%s",
                                        agent_id_eff,
                                        overdue_sec,
                                        heartbeat_interval,
                                    )
                                    heartbeat_overdue_logged = True
                            if not await _send(ws, {"type": "PING"}):
                                logger.warning(
                                    "heartbeat send failed; stopping pinger agent_id=%s",
                                    agent_id_eff,
                                )
                                return

                    ping_task = asyncio.create_task(pinger())

                    try:
                        async for msg in ws:
                            if msg.type != aiohttp.WSMsgType.TEXT:
                                continue
                            try:
                                data = msg.json()
                            except Exception:
                                continue
                            if not isinstance(data, dict):
                                continue

                            t = data.get("type")
                            if t == "PONG":
                                last_pong_mono = time.monotonic()
                                if heartbeat_overdue_logged:
                                    logger.info(
                                        "heartbeat recovered agent_id=%s",
                                        agent_id_eff,
                                    )
                                    heartbeat_overdue_logged = False
                                continue
                            if t == "SCAN_TARGET":
                                await _handle_scan(
                                    msg=data,
                                    client=client,
                                    ws=ws,
                                    default_root=scan_root_eff,
                                    verbose=verbose,
                                    lock=lock,
                                )
                                continue

                            if verbose:
                                logger.info("unhandled message: %r", data)
                    finally:
                        ping_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await ping_task

        except KeyboardInterrupt:
            raise
        except Exception as e:
            wait = _backoff(attempt)
            attempt += 1
            logger.warning("agent disconnected (%r). reconnecting in %.1fs", e, wait)
            await asyncio.sleep(wait)
