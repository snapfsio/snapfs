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

import getpass
import hashlib
import os
import socket
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .client import SnapFS
from .config import settings

try:
    import pwd
except ImportError:  # Windows, etc.
    pwd = None  # type: ignore[assignment]

try:
    import grp
except ImportError:
    grp = None  # type: ignore[assignment]


def sha1_file(path: str) -> str:
    """Stream a file and return its SHA-1 hex digest."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
    algo: str,
    hash_hex: str,
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
    mtime = float(getattr(st, "st_mtime", 0.0))
    atime = float(getattr(st, "st_atime", 0.0))
    ctime = float(getattr(st, "st_ctime", 0.0))
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
    :return: Summary dict.
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

    # Scan session metadata
    gateway = client.gateway
    scan_id = str(uuid.uuid4())
    hostname = socket.gethostname()
    user = getpass.getuser()
    pid = os.getpid()
    started_at = float(time.time())
    trigger_type = _normalize_trigger_type(trigger_type)

    # Emit scan.started
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

    # Walk files
    files: List[str] = []
    for dirpath, _, filenames in os.walk(root):
        for name in filenames:
            files.append(os.path.join(dirpath, name))

    # seen_inodes: used to avoid re-probing / re-hashing identical content
    seen_inodes: set[Tuple[int, int, int, int]] = set()  # (dev, ino, size, mtime_int)

    # du_inodes: used to compute fsize_du for hardlinks
    # Only the first time we see a (dev, ino) pair do we "charge" size to fsize_du.
    du_inodes: set[Tuple[int, int]] = set()

    total = len(files)
    cache_hits = 0
    hashed = 0
    published = 0

    for i in range(0, total, settings.probe_batch):
        batch_paths = files[i : i + settings.probe_batch]
        probes: List[Dict[str, Any]] = []
        stats: Dict[int, os.stat_result] = {}

        # Build probes and skip duplicates within this run by inode tuple
        for _, p in enumerate(batch_paths):
            try:
                st = os.stat(p, follow_symlinks=False)
                mti = int(st.st_mtime)
                inode = int(getattr(st, "st_ino", 0))
                dev = int(getattr(st, "st_dev", 0))
                inode_key = (
                    (dev, inode, int(st.st_size), mti) if (dev and inode) else None
                )
                if inode_key and inode_key in seen_inodes:
                    continue
                if inode_key:
                    seen_inodes.add(inode_key)
                pr = {
                    "path": p,
                    "size": int(st.st_size),
                    "mtime": int(mti),
                    "inode": inode or None,
                    "dev": dev or None,
                }
                probes.append(pr)
                stats[len(probes) - 1] = st
            except FileNotFoundError:
                continue
            except Exception as e:
                print(f"[scanner] stat error: {p}: {e}", file=sys.stderr)

        if not probes:
            continue

        # Probe cache via gateway
        try:
            results = await gateway.cache_probe_batch_async(probes)

        # TODO: optionally raise on gateway connect errors
        except Exception as e:
            if _is_auth_error(e):
                raise RuntimeError(
                    "Gateway authentication failed during cache probe"
                ) from e
            print(f"[scanner] cache probe error: {e} (treating as MISS)")
            results = [{"status": "MISS"} for _ in probes]

        # For each result, decide whether to hash and/or publish
        events: List[Dict[str, Any]] = []
        for idx, res in enumerate(results):
            path = probes[idx]["path"]
            st = stats[idx]

            # Compute fsize_du with hardlink awareness
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

            status = res.get("status")
            cached_algo = res.get("algo")
            cached_hash = res.get("hash")

            if status == "HIT" and cached_hash and cached_algo and not force:
                cache_hits += 1
                if verbose > 1:
                    print(f"cache: {path} {cached_algo}:{cached_hash}")
                algo = cached_algo
                h = cached_hash
            else:
                # MISS or force re-hash
                try:
                    algo = "sha1"
                    h = sha1_file(path)
                    hashed += 1
                    if verbose > 0:
                        print(f"hash:  {path} {algo}:{h}")
                except Exception as e:
                    print(f"[scanner] hash error: {path}: {e}", file=sys.stderr)
                    continue

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

            # Publish in chunks
            if len(events) >= settings.publish_batch:
                try:
                    await gateway.publish_events_async(events)
                    published += len(events)
                    events.clear()
                except Exception as e:
                    if _is_auth_error(e):
                        raise RuntimeError(
                            "Gateway authentication failed while publishing file events"
                        ) from e
                    print(f"[scanner] publish error: {e}", file=sys.stderr)

        # Flush any remaining events in this probe batch
        if events:
            try:
                await gateway.publish_events_async(events)
                published += len(events)
                events.clear()
            except Exception as e:
                if _is_auth_error(e):
                    raise RuntimeError(
                        "Gateway authentication failed while publishing file events"
                    ) from e
                print(f"[scanner] publish error: {e}", file=sys.stderr)

    summary = {
        "files": total,
        "cache_hits": cache_hits,
        "hashed": hashed,
        "published": published,
        "scan_id": scan_id,
    }

    finished_at = float(time.time())

    # Emit scan.completed
    complete_event = {
        "type": "scan.completed",
        "data": {
            "root_path": root,
            "scan_id": scan_id,
            "hostname": hostname,
            "user": user,
            "pid": pid,
            "started_at": started_at,
            "finished_at": finished_at,
            "files_seen": total,
            "cache_hits": cache_hits,
            "hashed": hashed,
            "published": published,
            "trigger_type": trigger_type,
            "schedule_id": schedule_id,
        },
    }
    try:
        await gateway.publish_events_async([complete_event])
        if verbose:
            print(
                f"[scanner] scan.completed root={root} scan_id={scan_id} "
                f"files={total}"
            )
    except Exception as e:
        if _is_auth_error(e):
            raise RuntimeError(
                "Gateway authentication failed while publishing scan.completed"
            ) from e
        print(f"[scanner] failed to publish scan.completed: {e}", file=sys.stderr)

    print(
        f"[scanner] done. files={total} "
        f"cache_hits={cache_hits} hashed={hashed} published={published}"
    )
    return summary
