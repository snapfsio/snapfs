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
    """Client for interacting with the SnapFS gateway."""

    def __init__(
        self,
        gateway_url: Optional[str] = None,
        *,
        subject: Optional[str] = None,
        token: Optional[str] = None,
        gateway: Optional[GatewayClient] = None,
    ):
        """
        :param gateway_url: Base URL of the SnapFS gateway.
        :param subject: Optional default subject for ingest routing.
        :param token: Optional auth token for the gateway.
        :param gateway: Optional pre-configured GatewayClient instance.
        """
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

        :param sql: The SQL query string to execute.
        :param params: Optional dictionary of query parameters.
        :return: List of result rows as dictionaries.
        """
        return self.gateway.sql(sql, params=params)

    def files_by_path_like(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Example convenience API for querying files by path pattern.

        :param pattern: SQL LIKE pattern for file paths.
        :return: List of matching file records.
        """
        sql = "SELECT * FROM files WHERE path LIKE :pattern"
        return self.sql(sql, params={"pattern": pattern})
