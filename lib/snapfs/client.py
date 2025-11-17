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

from typing import Any, Dict, List, Optional

from .gateway import GatewayClient


class SnapFS:
    """
    High-level SnapFS facade.

    - Owns a GatewayClient (`self.gateway`).
    - Exposes convenience methods for common operations.
    - For power users, the underlying `GatewayClient` is available as `.gateway`.
    """

    def __init__(
        self,
        gateway_url: Optional[str] = None,
        *,
        subject: Optional[str] = None,
        token: Optional[str] = None,
        gateway: Optional[GatewayClient] = None,
    ):
        # allow explicit GatewayClient injection (e.g., tests or advanced usage)
        self.gateway: GatewayClient = gateway or GatewayClient(
            base_url=gateway_url,
            subject=subject,
            token=token,
        )

    def sql(
        self,
        sql: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute raw SQL over the gateway. Intended primarily for internal
        tools / debugging; higher-level query helpers should be preferred.
        """
        return self.gateway.sql(sql, params=params)

    def files_by_path_like(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Example convenience API for querying files by path pattern.

        Initially, this can be implemented via sql(), but long-term we can
        back it with a dedicated gateway endpoint.
        """
        sql = "SELECT * FROM files WHERE path LIKE :pattern"
        return self.sql(sql, params={"pattern": pattern})
