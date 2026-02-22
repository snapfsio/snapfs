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
    """Configuration settings for SnapFS components, loaded from environment variables."""

    # Gateway URL
    gateway: str = os.getenv("SNAPFS_GATEWAY", "http://localhost:8000").strip()

    # Optional auth token (JWT).
    token: Optional[str] = os.getenv("SNAPFS_TOKEN")

    # Allow HTTP gateway for non-local hosts (not recommended).
    allow_insecure_gateway: bool = os.getenv("SNAPFS_ALLOW_INSECURE_GATEWAY", "0") in {
        "1",
        "true",
        "True",
    }

    # API key used to mint short-lived scanner JWTs via /auth/token.
    api_key: Optional[str] = os.getenv("SNAPFS_API_KEY")

    # Optional CSV list of scanner token scopes requested from /auth/token.
    scanner_token_scopes: str = os.getenv("SNAPFS_SCANNER_TOKEN_SCOPES", "ingest:write")

    # Default subject for ingest routing
    subject: str = os.getenv("SNAPFS_SUBJECT", "snapfs.files")

    # Scanner batching knobs
    probe_batch: int = int(os.getenv("SNAPFS_PROBE_BATCH", "200"))
    publish_batch: int = int(os.getenv("SNAPFS_PUBLISH_BATCH", "200"))

    # Agent identity
    agent_id: str = os.getenv("SNAPFS_AGENT_ID", "scanner-01")

    # Default filesystem scan root (client machine path)
    scan_root: str = os.getenv("SNAPFS_SCAN_ROOT", "")

    # TODO(v1): Use this as advertised scanner root capability in AGENT_HELLO.
    # Keep aligned with scan_root for now.
    scanner_root: str = os.getenv("SNAPFS_SCANNER_ROOT", "").strip()

    # TODO(v1): Reserve for future parallel scan support per scanner process.
    # Current runtime still executes one scan at a time.
    scanner_max_concurrency: int = int(os.getenv("SNAPFS_SCANNER_MAX_CONCURRENCY", "1"))

    # TODO(v1): Optional scanner class/capability label for scheduling.
    # Examples: fs, nfs, s3, gcs
    scanner_type: str = os.getenv("SNAPFS_SCANNER_TYPE", "fs").strip().lower()

    # WS path for agent control
    ws_path: str = os.getenv("SNAPFS_AGENT_WS_PATH", "/agents")

    # Optional ping interval for WS keepalive
    ping_interval: int = int(os.getenv("SNAPFS_AGENT_PING_INTERVAL", "30"))


settings = Settings()
