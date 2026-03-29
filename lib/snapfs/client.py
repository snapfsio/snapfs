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

from typing import Optional

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
