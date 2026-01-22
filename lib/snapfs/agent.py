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
from typing import Any, Dict, Optional

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


async def _send(ws: aiohttp.ClientWebSocketResponse, payload: Dict[str, Any]) -> None:
    """Send a JSON payload over the WS, with error handling."""
    try:
        await ws.send_json(payload)
    except Exception as e:
        logger.warning("WS send failed: %r payload=%r", e, payload)


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
                    "scan command_id=%s root=%s force=%s", command_id, root, force
                )

            summary = await scanner.scan_dir(
                root,
                client,
                force=force,
                verbose=verbose,
            )

            await _send(
                ws,
                {
                    "type": "SCAN_COMPLETE",
                    "command_id": command_id,
                    "root": root,
                    "took_s": round(time.time() - started, 3),
                    "summary": summary,
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
    Connect to gateway WS (/agents) and execute SCAN_TARGET commands.

    :param agent_id: Optional agent identifier (overrides SNAPFS_AGENT_ID)
    :param scan_root: Optional default scan root (overrides SNAPFS_SCAN_ROOT)
    :param gateway: Optional gateway URL (overrides SNAPFS_GATEWAY)
    :param verbose: Verbosity level (0=quiet, 1=info)
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)

    gateway_ws = client.gateway.ws_url
    agent_id_eff = agent_id or settings.agent_id
    scan_root_eff = scan_root or settings.scan_root
    if not scan_root_eff:
        logger.warning("No default scan root set; SCAN_TARGET must specify root")

    ws_url = _join_ws(gateway_ws, settings.ws_path)

    logger.info("SnapFS agent starting agent_id=%r ws=%s", agent_id_eff, gateway_ws)

    lock = asyncio.Lock()
    attempt = 0

    while True:
        try:
            timeout = aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=None)
            async with aiohttp.ClientSession(timeout=timeout) as sess:
                async with sess.ws_connect(ws_url, heartbeat=30) as ws:
                    attempt = 0

                    await ws.send_json(
                        {
                            "type": "AGENT_HELLO",
                            "agent_id": agent_id_eff,
                            "agent_type": "scanner",
                            "version": "snapfs",
                            "capabilities": ["scan.fs"],
                        }
                    )

                    async def pinger():
                        while True:
                            await asyncio.sleep(max(5, int(settings.ping_interval)))
                            try:
                                await ws.send_json({"type": "PING"})
                            except Exception:
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
                        with contextlib.suppress(Exception):
                            await ping_task

        except KeyboardInterrupt:
            raise
        except Exception as e:
            wait = _backoff(attempt)
            attempt += 1
            logger.warning("agent disconnected (%r). reconnecting in %.1fs", e, wait)
            await asyncio.sleep(wait)
