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

import argparse
import asyncio
import io
import json
import os
import platform
import socket
import sys
import time
from collections import Counter
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Dict, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
LIB_DIR = REPO_ROOT / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from snapfs import __version__ as snapfs_version, scanner
from snapfs.config import settings


def fmt_bytes_human(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"]
    size = float(max(0, int(value)))
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PiB"


def detect_total_memory_bytes() -> int:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        if (
            isinstance(pages, int)
            and isinstance(page_size, int)
            and pages > 0
            and page_size > 0
        ):
            return int(pages * page_size)
    except (AttributeError, OSError, ValueError):
        pass
    return 0


def detect_cpu_model() -> str:
    cpu = platform.processor().strip()
    if cpu:
        return cpu
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="ignore").splitlines():
            if ":" in line and line.lower().startswith("model name"):
                return line.split(":", 1)[1].strip()
    return "unknown"


def collect_system_metadata() -> Dict[str, Any]:
    total_memory_bytes = detect_total_memory_bytes()
    return {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "snapfs_version": snapfs_version,
        "cpu_count_logical": os.cpu_count() or 0,
        "cpu_model": detect_cpu_model(),
        "total_memory_bytes": total_memory_bytes,
        "total_memory_human": fmt_bytes_human(total_memory_bytes)
        if total_memory_bytes
        else None,
    }


class FakeGateway:
    """Gateway double that simulates cache probe behavior and discards publishes."""

    def __init__(self, cache_mode: str = "miss", cache_algo: str = "sha1"):
        self.cache_mode = cache_mode
        self.cache_algo = cache_algo
        self.event_counts: Counter[str] = Counter()
        self.published_batches = 0
        self.file_events = 0
        self.telemetry_events = 0

    async def cache_probe_batch_async(self, probes: Iterable[Dict[str, Any]]):
        probes = list(probes)
        if self.cache_mode == "hit":
            return [
                {"status": "HIT", "algo": self.cache_algo, "hash": "bench-hit"}
                for _ in probes
            ]
        return [{"status": "MISS"} for _ in probes]

    async def publish_events_async(self, events, subject=None):
        batch = list(events)
        self.published_batches += 1
        for event in batch:
            etype = event.get("type", "unknown")
            self.event_counts[etype] += 1
            if etype == "file.upsert":
                self.file_events += 1
            elif etype == "scan.telemetry":
                self.telemetry_events += 1
        return {"ok": True, "subject": subject}


class FakeClient:
    def __init__(self, gateway: FakeGateway):
        self.gateway = gateway


@contextmanager
def temporary_settings(**overrides):
    original = {name: getattr(settings, name) for name in overrides}
    try:
        for name, value in overrides.items():
            setattr(settings, name, value)
        yield
    finally:
        for name, value in original.items():
            setattr(settings, name, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark snapfs scanner.scan_dir locally without gateway auth.",
    )
    parser.add_argument("path", help="Directory to scan")
    parser.add_argument("--algo", default=settings.hash_algo, help="Hash algorithm")
    parser.add_argument(
        "--workers", type=int, default=settings.hash_workers, help="Hash worker count"
    )
    parser.add_argument(
        "--hash-chunk-size",
        type=int,
        default=settings.hash_chunk_size,
        help="Hash chunk size in bytes",
    )
    parser.add_argument(
        "--probe-batch",
        type=int,
        default=settings.probe_batch,
        help="Probe batch size",
    )
    parser.add_argument(
        "--publish-batch",
        type=int,
        default=settings.publish_batch,
        help="Publish batch size",
    )
    parser.add_argument(
        "--telemetry-interval",
        type=int,
        default=0,
        help="Telemetry interval in seconds (0 disables telemetry publishes)",
    )
    parser.add_argument(
        "--cache-mode",
        choices=["miss", "hit"],
        default="miss",
        help="Simulate gateway cache probe results",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-hash even if cache hits are simulated",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Pass through scanner verbosity",
    )
    parser.add_argument("--json", action="store_true", help="Emit summary as JSON")
    return parser.parse_args()


async def run_benchmark(args: argparse.Namespace) -> Dict[str, Any]:
    root = Path(args.path).resolve()
    if not root.is_dir():
        raise NotADirectoryError(str(root))

    gateway = FakeGateway(cache_mode=args.cache_mode, cache_algo=args.algo)
    client = FakeClient(gateway)

    started = time.perf_counter()
    scanner_stdout = io.StringIO()
    with temporary_settings(
        probe_batch=args.probe_batch,
        publish_batch=args.publish_batch,
        scan_telemetry_interval_sec=args.telemetry_interval,
    ):
        with redirect_stdout(scanner_stdout):
            summary = await scanner.scan_dir(
                str(root),
                client,
                force=args.force,
                verbose=args.verbose,
                algo=args.algo,
                hash_workers=args.workers,
                hash_chunk_size=args.hash_chunk_size,
            )
    elapsed = time.perf_counter() - started

    total_bytes = int(summary.get("bytes", 0) or 0)
    result = {
        "path": str(root),
        "elapsed_sec": round(elapsed, 3),
        "algo": args.algo,
        "workers": args.workers,
        "hash_chunk_size": args.hash_chunk_size,
        "cache_mode": args.cache_mode,
        "force": args.force,
        "summary": summary,
        "total_bytes": total_bytes,
        "total_bytes_human": fmt_bytes_human(total_bytes),
        "system": collect_system_metadata(),
        "event_counts": dict(gateway.event_counts),
        "published_batches": gateway.published_batches,
        "file_events": gateway.file_events,
        "telemetry_events": gateway.telemetry_events,
        "files_per_sec": round(float(summary.get("files", 0)) / max(elapsed, 0.001), 3),
        "published_per_sec": round(
            float(summary.get("published", 0)) / max(elapsed, 0.001), 3
        ),
    }
    return result


def main() -> int:
    args = parse_args()
    try:
        result = asyncio.run(run_benchmark(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Benchmark failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"Path:           {result['path']}")
        print(f"Elapsed:        {result['elapsed_sec']}s")
        print(f"Algo:           {result['algo']}")
        print(f"Workers:        {result['workers']}")
        print(f"Chunk size:     {result['hash_chunk_size']}")
        print(f"Cache mode:     {result['cache_mode']}")
        print(f"Force:          {result['force']}")
        print(
            f"Total bytes:    {result['total_bytes_human']} ({result['total_bytes']})"
        )
        print(f"Files/sec:      {result['files_per_sec']}")
        print(f"Published/sec:  {result['published_per_sec']}")
        print(f"Summary:        {result['summary']}")
        print(f"Events:         {result['event_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
