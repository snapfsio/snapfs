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

import os
from typing import Optional

from pydantic import BaseModel


class Settings(BaseModel):
    # Gateway endpoints (aligned with other agents)
    gateway_ws: str = os.getenv("GATEWAY_WS", "ws://localhost:8000")
    gateway_http: str = os.getenv("GATEWAY_HTTP", "http://localhost:8000")

    # Optional auth token
    token: Optional[str] = os.getenv("SNAPFS_TOKEN")

    # Default subject for ingest routing
    subject: str = os.getenv("SNAPFS_SUBJECT", "snapfs.files")

    # Scanner batching knobs
    probe_batch: int = int(os.getenv("SNAPFS_PROBE_BATCH", "200"))
    publish_batch: int = int(os.getenv("SNAPFS_PUBLISH_BATCH", "200"))

    # Agent identity
    agent_id: str = os.getenv("SNAPFS_AGENT_ID", "scanner-01")

    # Default filesystem scan root (client machine path)
    scan_root: str = os.getenv("SNAPFS_SCAN_ROOT", "")

    # WS path for agent control (gateway exposes /agents)
    ws_path: str = os.getenv("SNAPFS_AGENT_WS_PATH", "/agents")

    # Optional ping interval for WS keepalive
    ping_interval: int = int(os.getenv("SNAPFS_AGENT_PING_INTERVAL", "30"))


settings = Settings()
