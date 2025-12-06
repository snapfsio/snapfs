#!/usr/bin/env python3
#
# Copyright (c) 2025 SnapFS. All rights reserved.
#

import hashlib
import os
import sys
from typing import Any, Dict, List, Tuple

from .config import HASH_SMALL_MAX, PROBE_BATCH, PUBLISH_BATCH
from .gateway import GatewayClient

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
) -> Dict[str, Any]:
    """
    Build an ingest event payload from a file stat + hash, including extended metadata.
    """
    mtime = float(int(st.st_mtime))
    atime = float(int(getattr(st, "st_atime", 0)))
    ctime = float(int(getattr(st, "st_ctime", 0)))
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

    return {
        "type": "file.upsert",
        "data": {
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
    gateway: GatewayClient,
    *,
    force: bool = False,
    verbose: bool = False,
) -> Dict[str, int]:
    """
    Scan a directory tree and publish file.upsert events via the given gateway.

    Args:
        root:   Root directory to scan.
        gateway: GatewayClient instance.
        force:  If True, publish events even for cache HITs (reusing cache hash).
        verbose: If True, print progress info.

    Returns a summary dict:
        {
          "files": total_files_seen,
          "cache_hits": n_cache_hits,
          "hashed": n_hashed,
          "published": n_published,
        }
    """
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)

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

    for i in range(0, total, PROBE_BATCH):
        batch_paths = files[i : i + PROBE_BATCH]
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
        except Exception as e:
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

            if status == "HIT" and cached_hash and cached_algo:
                cache_hits += 1
                if verbose > 1:
                    print(f"cache: {path} {cached_algo}:{cached_hash}")

                if not force:
                    # old behavior: skip publish entirely
                    continue

                # force=True: reuse cached hash but still publish updated metadata
                algo = cached_algo
                h = cached_hash
            else:
                # MISS or missing hash/algo -> hash now
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
                )
            )

            # Publish in chunks
            if len(events) >= PUBLISH_BATCH:
                try:
                    await gateway.publish_events_async(events)
                    published += len(events)
                    events.clear()
                except Exception as e:
                    print(f"[scanner] publish error: {e}", file=sys.stderr)

        # Flush any remaining events in this probe batch
        if events:
            try:
                await gateway.publish_events_async(events)
                published += len(events)
                events.clear()
            except Exception as e:
                print(f"[scanner] publish error: {e}", file=sys.stderr)

    summary = {
        "files": total,
        "cache_hits": cache_hits,
        "hashed": hashed,
        "published": published,
    }
    print(
        f"[scanner] done. files={total} "
        f"cache_hits={cache_hits} hashed={hashed} published={published}"
    )
    return summary
