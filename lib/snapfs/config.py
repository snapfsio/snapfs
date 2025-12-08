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

# SnapFS gateway URL
DEFAULT_GATEWAY = os.getenv("SNAPFS_GATEWAY", "http://localhost:8000")

# Default subject for SnapFS operations
DEFAULT_SUBJECT = os.getenv("SNAPFS_SUBJECT", "snapfs.files")

# Optional authentication token for SnapFS gateway
DEFAULT_TOKEN = os.getenv("SNAPFS_TOKEN")

# Batch sizes and thresholds
PROBE_BATCH = int(os.getenv("SNAPFS_PROBE_BATCH", "200"))

# Number of items to publish in a single batch
PUBLISH_BATCH = int(os.getenv("SNAPFS_PUBLISH_BATCH", "200"))
