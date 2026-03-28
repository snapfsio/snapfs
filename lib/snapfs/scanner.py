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
from concurrent.futures import ProcessPoolExecutor
import getpass
import os
import socket
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .client import SnapFS
from .config import settings
from . import hashing

try:
    import pwd
except ImportError:  # Windows, etc.
    pwd = None  # type: ignore[assignment]

try:
    import grp
except ImportError:
    grp = None  # type: ignore[assignment]


def sha1_file(path: str) -> str:
    """Backward-compatible SHA-1 helper used by tests and existing callers."""
    return hashing.hash_file(path, "sha1")


async def sha1_file_async(path: str) -> str:
    """Backward-compatible async SHA-1 helper used by tests and existing callers."""
    return await hashing.hash_file_async(path, "sha1")


def _normalize_trigger_type(value: Optional[str]) -> str:
    """Normalize scan trigger type to manual/schedule/api."""
    t = str(value or "manual").strip().lower()
    if t in {"manual", "schedule", "api"}:
        return t
    return "manual"


def _is_auth_error(exc: Exception) -> bool:
    """Return True when exception represents gateway auth failure."""
    status = getattr(exc, "status", None)
    if status in {401, 403}:
        return True
    msg = str(exc).lower()
    return "unauthorized" in msg or "forbidden" in msg


def _scan_error_category(exc: BaseException) -> str:
    """Return a coarse scan error category for operator reporting."""
    if isinstance(exc, PermissionError):
        return "permission"
    if isinstance(exc, FileNotFoundError):
        return "not_found"
    if isinstance(exc, IsADirectoryError):
        return "is_directory"
    if isinstance(exc, NotADirectoryError):
        return "not_directory"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, OSError):
        return "os_error"
    return "runtime"


def _lookup_owner_group(st: os.stat_result) -> Tuple[Any, Any]:
    """
    Best-effort lookup of owner and group names.

    Returns (owner, group) where values are usually strings (user/group name)
    but may fall back to UID/GID ints or None if not available.
    """
    uid = int(getattr(st, "st_uid", -1))
    gid = int(getattr(st, "st_gid", -1))

    owner: Any = None
    group: Any = None

    if pwd is not None and uid >= 0:
        try:
            owner = pwd.getpwuid(uid).pw_name
        except KeyError:
            owner = str(uid)
    elif uid >= 0:
        owner = str(uid)

    if grp is not None and gid >= 0:
        try:
            group = grp.getgrgid(gid).gr_name
        except KeyError:
            group = str(gid)
    elif gid >= 0:
        group = str(gid)

    return owner, group


def event_from_stat(
    path: str,
    st: os.stat_result,
    algo: Optional[str],
    hash_hex: Optional[str],
    *,
    fsize_du: int,
    root_path: str,
    scan_id: str,
) -> Dict[str, Any]:
    """
    Build an ingest event payload from a file stat + hash, including extended metadata.

    :param path: Full file path.
    :param st: os.stat_result for the file.
    :param algo: Hash algorithm name (e.g. "sha1").
    :param hash_hex: Hex digest of the file hash.
    :param fsize_du: Disk usage size for the file (hardlink-aware).
    :param root_path: Root path of the scan.
    :param scan_id: Scan session identifier.
    :return: Event dict suitable for publishing.
    """
    # Normalize stat times to epoch milliseconds at source.
    mtime = int(getattr(st, "st_mtime_ns", 0) // 1_000_000)
    atime = int(getattr(st, "st_atime_ns", 0) // 1_000_000)
    ctime = int(getattr(st, "st_ctime_ns", 0) // 1_000_000)
    size = int(st.st_size)
    inode = int(getattr(st, "st_ino", 0)) or None
    dev = int(getattr(st, "st_dev", 0)) or None
    nlinks = int(getattr(st, "st_nlink", 1) or 1)

    dir_name = os.path.dirname(path)
    base_name = os.path.basename(path)
    _, ext = os.path.splitext(base_name)

    owner, group = _lookup_owner_group(st)

    uid = int(getattr(st, "st_uid", -1))
    gid = int(getattr(st, "st_gid", -1))
    mode = int(getattr(st, "st_mode", 0)) & 0o7777  # include type bits + perms

    # Full-resolution event time
    seen_at = float(time.time())

    return {
        "type": "file.upsert",
        "data": {
            # scan context
            "root_path": root_path,
            "scan_id": scan_id,
            "seen_at": seen_at,
            # identity / path
            "path": path,
            "dir": dir_name,
            "name": base_name,
            "ext": ext,
            "type": "file",
            # basic stat info
            "size": size,
            "fsize_du": int(fsize_du),
            "mtime": mtime,
            "atime": atime,
            "ctime": ctime,
            "nlinks": nlinks,
            "inode": inode,
            "dev": dev,
            # ownership
            "owner": owner,
            "group": group,
            "uid": uid if uid >= 0 else None,
            "gid": gid if gid >= 0 else None,
            "mode": mode,
            # hash info
            "algo": algo,
            "hash": hash_hex,
        },
    }


async def scan_dir(
    root: str,
    client: SnapFS,
    *,
    force: bool = False,
    verbose: int = 0,
    trigger_type: str = "manual",
    schedule_id: Optional[str] = None,
    scan_id: Optional[str] = None,
    algo: Optional[str] = None,
    hash_workers: Optional[int] = None,
    hash_chunk_size: Optional[int] = None,
) -> Dict[str, int]:
    """
    Scan a directory tree and publish file.upsert events via the given gateway.

    Returns a summary dict:
        {
          "files": total_files_seen,
          "cache_hits": n_cache_hits,
          "hashed": n_hashed,
          "published": n_published,
        }

    :param root: Root directory path to scan.
    :param client: SnapFS client instance.
    :param force: If True, re-hash files even when cache reports a hit.
    :param verbose: Verbosity level (0=quiet, 1=info)
    :param trigger_type: Scan trigger source (manual/schedule/api).
    :param schedule_id: Optional schedule id when trigger_type is schedule.
    :param scan_id: Optional externally assigned scan id.
    :param algo: Hash algorithm override (defaults to SNAPFS_HASH_ALGO or sha1).
    :param hash_workers: Optional number of hash worker processes.
    :param hash_chunk_size: Optional read chunk size in bytes for hashing.
    :return: Summary dict.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

    gateway = client.gateway
    scan_id = str(scan_id or uuid.uuid4())
    hostname = socket.gethostname()
    user = getpass.getuser()
    pid = os.getpid()
    started_at = float(time.time())
    trigger_type = _normalize_trigger_type(trigger_type)
    selected_algo = hashing.resolve_algorithm(algo or settings.hash_algo)
    selected_hash_workers = max(1, int(hash_workers or settings.hash_workers))
    selected_hash_chunk_size = max(1, int(hash_chunk_size or settings.hash_chunk_size))

    files: List[str] = []
    walk_errors = 0
    permission_errors = 0
    total = 0
    cache_hits = 0
    hashed = 0
    hash_errors = 0
    published = 0
    bytes_published = 0
    pending_scan_errors: List[Dict[str, Any]] = []

    start_event = {
        "type": "scan.started",
        "data": {
            "root_path": root,
            "scan_id": scan_id,
            "hostname": hostname,
            "user": user,
            "pid": pid,
            "started_at": started_at,
            "trigger_type": trigger_type,
            "schedule_id": schedule_id,
            "hash_algo": selected_algo,
            "hash_workers": selected_hash_workers,
            "hash_chunk_size": selected_hash_chunk_size,
        },
    }
    try:
        await gateway.publish_events_async([start_event])
        if verbose:
            print(f"[scanner] scan.started root={root} scan_id={scan_id}")
    except Exception as e:
        if _is_auth_error(e):
            raise RuntimeError(
                "Gateway authentication failed while publishing scan.started"
            ) from e
        print(f"[scanner] failed to publish scan.started: {e}", file=sys.stderr)

    async def emit_scan_telemetry(*, status: str, force_emit: bool = False) -> None:
        nonlocal last_telemetry_at
        if telemetry_interval_sec <= 0:
            return

        now_mono = time.monotonic()
        if not force_emit and (now_mono - last_telemetry_at) < telemetry_interval_sec:
            return
        last_telemetry_at = now_mono

        elapsed = max(0.001, float(time.time() - started_at))
        telemetry_event = {
            "type": "scan.telemetry",
            "data": {
                "root_path": root,
                "scan_id": scan_id,
                "hostname": hostname,
                "user": user,
                "pid": pid,
                "started_at": started_at,
                "trigger_type": trigger_type,
                "schedule_id": schedule_id,
                "status": status,
                "hash_algo": selected_algo,
                "hash_workers": selected_hash_workers,
                "hash_chunk_size": selected_hash_chunk_size,
                "files_total": total,
                "cache_hits": cache_hits,
                "hashed": hashed,
                "published": published,
                "bytes_published": bytes_published,
                "hash_errors": hash_errors,
                "walk_errors": walk_errors,
                "permission_errors": permission_errors,
                "authoritative_for_deletes": (walk_errors + permission_errors) == 0,
                "elapsed_sec": round(elapsed, 3),
                "files_per_sec": round(float(published) / elapsed, 3),
                "bytes_per_sec": round(float(bytes_published) / elapsed, 3),
            },
        }

        try:
            await gateway.publish_events_async(
                [telemetry_event],
                subject=settings.events_subject,
            )
        except Exception as e:
            if _is_auth_error(e):
                raise RuntimeError(
                    "Gateway authentication failed while publishing scan.telemetry"
                ) from e
            if verbose > 0:
                print(f"[scanner] telemetry publish error: {e}", file=sys.stderr)

    def queue_scan_error(
        *, stage: str, path: Optional[str], exc: BaseException
    ) -> None:
        pending_scan_errors.append(
            {
                "type": "scan.error",
                "data": {
                    "root_path": root,
                    "scan_id": scan_id,
                    "hostname": hostname,
                    "user": user,
                    "pid": pid,
                    "started_at": started_at,
                    "trigger_type": trigger_type,
                    "schedule_id": schedule_id,
                    "observed_at": float(time.time()),
                    "stage": stage,
                    "path": str(path or root),
                    "category": _scan_error_category(exc),
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                    "errno": getattr(exc, "errno", None),
                },
            }
        )

    async def flush_scan_errors() -> None:
        nonlocal pending_scan_errors
        if not pending_scan_errors:
            return
        batch = pending_scan_errors
        pending_scan_errors = []
        try:
            await gateway.publish_events_async(batch, subject=settings.events_subject)
        except Exception as e:
            if _is_auth_error(e):
                raise RuntimeError(
                    "Gateway authentication failed while publishing scan.error"
                ) from e
            if verbose > 0:
                print(f"[scanner] scan.error publish error: {e}", file=sys.stderr)
            pending_scan_errors = batch + pending_scan_errors

    async def emit_terminal_event(
        event_type: str, *, error_message: Optional[str] = None
    ) -> None:
        payload = {
            "root_path": root,
            "scan_id": scan_id,
            "hostname": hostname,
            "user": user,
            "pid": pid,
            "started_at": started_at,
            "finished_at": float(time.time()),
            "files_seen": total,
            "bytes_seen": bytes_published,
            "cache_hits": cache_hits,
            "hashed": hashed,
            "published": published,
            "hash_errors": hash_errors,
            "walk_errors": walk_errors,
            "permission_errors": permission_errors,
            "authoritative_for_deletes": (walk_errors + permission_errors) == 0,
            "trigger_type": trigger_type,
            "schedule_id": schedule_id,
            "hash_algo": selected_algo,
            "hash_workers": selected_hash_workers,
            "hash_chunk_size": selected_hash_chunk_size,
        }
        if error_message:
            payload["error"] = error_message

        terminal_event = {"type": event_type, "data": payload}
        try:
            await gateway.publish_events_async([terminal_event])
            if verbose:
                print(
                    f"[scanner] {event_type} root={root} scan_id={scan_id} "
                    f"files={total}"
                )
        except Exception as e:
            if _is_auth_error(e):
                raise RuntimeError(
                    f"Gateway authentication failed while publishing {event_type}"
                ) from e
            print(f"[scanner] failed to publish {event_type}: {e}", file=sys.stderr)

    def _on_walk_error(err: OSError) -> None:
        nonlocal walk_errors, permission_errors
        walk_errors += 1
        if isinstance(err, PermissionError):
            permission_errors += 1
        err_path = getattr(err, "filename", root) or root
        queue_scan_error(stage="walk", path=str(err_path), exc=err)
        print(
            f"[scanner] walk error: {err_path}: {err}",
            file=sys.stderr,
        )

    for dirpath, _, filenames in os.walk(root, onerror=_on_walk_error):
        for name in filenames:
            files.append(os.path.join(dirpath, name))

    seen_inodes: set[Tuple[int, int, int, int]] = set()
    du_inodes: set[Tuple[int, int]] = set()

    total = len(files)
    telemetry_interval_sec = max(0, int(settings.scan_telemetry_interval_sec))
    last_telemetry_at = time.monotonic()

    hash_executor = (
        ProcessPoolExecutor(max_workers=selected_hash_workers)
        if selected_hash_workers > 1
        else None
    )

    try:
        await emit_scan_telemetry(status="running", force_emit=True)

        for i in range(0, total, settings.probe_batch):
            batch_paths = files[i : i + settings.probe_batch]
            probes: List[Dict[str, Any]] = []
            stats: Dict[int, os.stat_result] = {}

            for p in batch_paths:
                try:
                    st = os.stat(p, follow_symlinks=False)
                    mti = int(st.st_mtime * 1000)
                    inode = int(getattr(st, "st_ino", 0))
                    dev = int(getattr(st, "st_dev", 0))
                    inode_key = (
                        (dev, inode, int(st.st_size), mti) if (dev and inode) else None
                    )
                    if inode_key and inode_key in seen_inodes:
                        continue
                    if inode_key:
                        seen_inodes.add(inode_key)
                    probes.append(
                        {
                            "path": p,
                            "size": int(st.st_size),
                            "mtime": int(mti),
                            "inode": inode or None,
                            "dev": dev or None,
                        }
                    )
                    stats[len(probes) - 1] = st
                except FileNotFoundError:
                    continue
                except PermissionError as e:
                    permission_errors += 1
                    queue_scan_error(stage="stat", path=p, exc=e)
                    print(f"[scanner] stat permission error: {p}: {e}", file=sys.stderr)
                except Exception as e:
                    queue_scan_error(stage="stat", path=p, exc=e)
                    print(f"[scanner] stat error: {p}: {e}", file=sys.stderr)

            if not probes:
                continue

            try:
                results = await gateway.cache_probe_batch_async(probes)
            except Exception as e:
                if _is_auth_error(e):
                    raise RuntimeError(
                        "Gateway authentication failed during cache probe"
                    ) from e
                queue_scan_error(stage="cache_probe", path=root, exc=e)
                print(f"[scanner] cache probe error: {e} (treating as MISS)")
                results = [{"status": "MISS"} for _ in probes]

            hash_results: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
            hash_jobs: List[Tuple[int, str]] = []

            for idx, res in enumerate(results):
                status = res.get("status")
                cached_algo = res.get("algo")
                cached_hash = res.get("hash")
                path = probes[idx]["path"]

                if (
                    status == "HIT"
                    and cached_hash
                    and cached_algo == selected_algo
                    and not force
                ):
                    cache_hits += 1
                    if verbose > 1:
                        print(f"cache: {path} {cached_algo}:{cached_hash}")
                    hash_results[idx] = (cached_algo, cached_hash)
                else:
                    hash_jobs.append((idx, path))

            if hash_jobs:
                hash_outputs = await asyncio.gather(
                    *(
                        hashing.hash_file_async(
                            path,
                            selected_algo,
                            chunk_size=selected_hash_chunk_size,
                            executor=hash_executor,
                        )
                        for _, path in hash_jobs
                    ),
                    return_exceptions=True,
                )
                for (idx, path), output in zip(hash_jobs, hash_outputs):
                    if isinstance(output, Exception):
                        queue_scan_error(stage="hash", path=path, exc=output)
                        print(
                            f"[scanner] hash error: {path}: {output}", file=sys.stderr
                        )
                        hash_errors += 1
                        hash_results[idx] = (None, None)
                    else:
                        hashed += 1
                        if verbose > 0:
                            print(f"hash:  {path} {selected_algo}:{output}")
                        hash_results[idx] = (selected_algo, output)

            events: List[Dict[str, Any]] = []
            for idx, _res in enumerate(results):
                path = probes[idx]["path"]
                st = stats[idx]

                size = int(st.st_size)
                inode = int(getattr(st, "st_ino", 0) or 0)
                dev = int(getattr(st, "st_dev", 0) or 0)
                nlinks = int(getattr(st, "st_nlink", 1) or 1)

                fsize_du = size
                if inode and dev and nlinks > 1:
                    inode_du_key = (dev, inode)
                    if inode_du_key in du_inodes:
                        fsize_du = 0
                    else:
                        du_inodes.add(inode_du_key)

                algo, h = hash_results.get(idx, (None, None))

                events.append(
                    event_from_stat(
                        path,
                        st,
                        algo,
                        h,
                        fsize_du=fsize_du,
                        root_path=root,
                        scan_id=scan_id,
                    )
                )

                if len(events) >= settings.publish_batch:
                    try:
                        await gateway.publish_events_async(events)
                        published += len(events)
                        bytes_published += sum(
                            int(
                                ev.get("data", {}).get("fsize_du")
                                or ev.get("data", {}).get("size")
                                or 0
                            )
                            for ev in events
                        )
                        events.clear()
                    except Exception as e:
                        if _is_auth_error(e):
                            raise RuntimeError(
                                "Gateway authentication failed while publishing file events"
                            ) from e
                        print(f"[scanner] publish error: {e}", file=sys.stderr)

            if events:
                try:
                    await gateway.publish_events_async(events)
                    published += len(events)
                    bytes_published += sum(
                        int(
                            ev.get("data", {}).get("fsize_du")
                            or ev.get("data", {}).get("size")
                            or 0
                        )
                        for ev in events
                    )
                    events.clear()
                except Exception as e:
                    if _is_auth_error(e):
                        raise RuntimeError(
                            "Gateway authentication failed while publishing file events"
                        ) from e
                    print(f"[scanner] publish error: {e}", file=sys.stderr)

            await flush_scan_errors()
            await emit_scan_telemetry(status="running")

        await flush_scan_errors()
        await emit_scan_telemetry(status="completed", force_emit=True)
        summary = {
            "files": total,
            "bytes": bytes_published,
            "cache_hits": cache_hits,
            "hashed": hashed,
            "published": published,
            "scan_id": scan_id,
        }
        await emit_terminal_event("scan.completed")
        print(
            f"[scanner] done. files={total} "
            f"cache_hits={cache_hits} hashed={hashed} hash_errors={hash_errors} "
            f"walk_errors={walk_errors} permission_errors={permission_errors} published={published} "
            f"bytes_published={bytes_published}"
        )
        return summary
    except (KeyboardInterrupt, asyncio.CancelledError) as e:
        cancel_message = str(e).strip() or "scan interrupted"
        lower_cancel_message = cancel_message.lower()
        explicit_cancel = (
            "operator" in lower_cancel_message and "cancel" in lower_cancel_message
        ) or "cancel requested" in lower_cancel_message
        try:
            await flush_scan_errors()
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish queued scan errors: {emit_err}",
                    file=sys.stderr,
                )
        try:
            await emit_scan_telemetry(
                status="canceled" if explicit_cancel else "failed",
                force_emit=True,
            )
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish {'canceled' if explicit_cancel else 'failed'} telemetry: {emit_err}",
                    file=sys.stderr,
                )
        try:
            await emit_terminal_event(
                "scan.cancelled" if explicit_cancel else "scan.failed",
                error_message=cancel_message,
            )
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish {'scan.cancelled' if explicit_cancel else 'scan.failed'}: {emit_err}",
                    file=sys.stderr,
                )
        raise
    except Exception as e:
        try:
            await flush_scan_errors()
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish queued scan errors: {emit_err}",
                    file=sys.stderr,
                )
        try:
            await emit_scan_telemetry(status="failed", force_emit=True)
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish failed telemetry: {emit_err}",
                    file=sys.stderr,
                )
        try:
            await emit_terminal_event("scan.failed", error_message=str(e))
        except Exception as emit_err:
            if verbose > 0:
                print(
                    f"[scanner] failed to publish scan.failed: {emit_err}",
                    file=sys.stderr,
                )
        raise
    finally:
        if hash_executor is not None:
            hash_executor.shutdown(wait=True)
