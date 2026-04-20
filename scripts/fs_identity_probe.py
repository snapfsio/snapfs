#!/usr/bin/env python3
"""Probe how a filesystem/editor changes path, inode, nlink, and content identity.

This script creates a small test fixture under a target directory and records
snapshots after common operations such as hard-linking, in-place writes,
replace-write saves, and optional manual edits. It is intended to help debug
how SnapFS should classify create vs update behavior across local disks, NFS,
and different editors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class EntrySnapshot:
    path: str
    exists: bool
    kind: str
    inode: Optional[int]
    dev: Optional[int]
    nlink: Optional[int]
    size: Optional[int]
    mtime_ns: Optional[int]
    ctime_ns: Optional[int]
    sha256: Optional[str]


@dataclass
class SnapshotRecord:
    label: str
    captured_at: float
    entries: List[EntrySnapshot]
    notes: Optional[str] = None


FILES = ("A.txt", "B.txt")


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def snapshot_entry(path: Path) -> EntrySnapshot:
    if not path.exists() and not path.is_symlink():
        return EntrySnapshot(
            path=str(path),
            exists=False,
            kind="missing",
            inode=None,
            dev=None,
            nlink=None,
            size=None,
            mtime_ns=None,
            ctime_ns=None,
            sha256=None,
        )

    st = os.lstat(path)
    mode = st.st_mode
    if stat.S_ISDIR(mode):
        kind = "dir"
        digest = None
    elif stat.S_ISLNK(mode):
        kind = "symlink"
        digest = None
    else:
        kind = "file"
        digest = sha256_file(path)

    return EntrySnapshot(
        path=str(path),
        exists=True,
        kind=kind,
        inode=int(getattr(st, "st_ino", 0)) or None,
        dev=int(getattr(st, "st_dev", 0)) or None,
        nlink=int(getattr(st, "st_nlink", 0)) or None,
        size=int(getattr(st, "st_size", 0)) if kind == "file" else None,
        mtime_ns=int(getattr(st, "st_mtime_ns", 0)) or None,
        ctime_ns=int(getattr(st, "st_ctime_ns", 0)) or None,
        sha256=digest,
    )


def capture(
    label: str, paths: List[Path], notes: Optional[str] = None
) -> SnapshotRecord:
    return SnapshotRecord(
        label=label,
        captured_at=time.time(),
        entries=[snapshot_entry(p) for p in paths],
        notes=notes,
    )


def print_snapshot(record: SnapshotRecord) -> None:
    print(f"\n== {record.label} ==")
    if record.notes:
        print(record.notes)
    for entry in record.entries:
        rel = Path(entry.path).name
        if not entry.exists:
            print(f"{rel:>8}  missing")
            continue
        print(
            f"{rel:>8}  inode={entry.inode} dev={entry.dev} nlink={entry.nlink} "
            f"size={entry.size} mtime_ns={entry.mtime_ns} sha256={entry.sha256}"
        )


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    os.sync() if hasattr(os, "sync") else None


def replace_write(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
    os.sync() if hasattr(os, "sync") else None


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        if not path.is_dir():
            raise ValueError(f"Target path exists and is not a directory: {path}")
        if any(path.iterdir()):
            raise ValueError(
                f"Refusing to use non-empty target directory: {path}. "
                "Please provide a new or empty directory."
            )
        return
    path.mkdir(parents=True, exist_ok=True)


def run_probe(target_dir: Path, *, pause_for_manual_edit: bool) -> List[SnapshotRecord]:
    ensure_clean_dir(target_dir)
    a = target_dir / "A.txt"
    b = target_dir / "B.txt"

    write_text(a, "alpha\n")
    os.link(a, b)

    records = [
        capture(
            "baseline_hardlinks",
            [a, b],
            notes="A and B should share inode and nlink=2.",
        )
    ]

    write_text(a, "alpha\nin-place edit\n")
    records.append(
        capture(
            "after_in_place_write",
            [a, b],
            notes="In-place write: many filesystems keep the shared inode.",
        )
    )

    # Rebuild baseline before testing replace-write behavior.
    ensure_clean_dir(target_dir)
    a = target_dir / "A.txt"
    b = target_dir / "B.txt"
    write_text(a, "alpha\n")
    os.link(a, b)
    records.append(capture("baseline_before_replace_write", [a, b]))

    replace_write(a, "alpha\nreplace write\n")
    records.append(
        capture(
            "after_replace_write",
            [a, b],
            notes="Replace-write often gives A a new inode while B stays on the old inode.",
        )
    )

    if pause_for_manual_edit:
        print(
            "\nManual edit pause: open A.txt in your editor, save it, then press Enter to continue."
        )
        print(f"Target: {a}")
        input()
        records.append(
            capture(
                "after_manual_editor_save",
                [a, b],
                notes="Observed after a manual editor save operation.",
            )
        )

    return records


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe filesystem identity behavior for SnapFS lifecycle debugging."
    )
    parser.add_argument(
        "target", help="Directory in which to create the probe fixture."
    )
    parser.add_argument(
        "--pause-for-manual-edit",
        action="store_true",
        help="Pause after automated steps so you can save A.txt in an external editor, then capture another snapshot.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the full snapshot report as JSON.",
    )
    args = parser.parse_args(argv)

    target_dir = Path(args.target).expanduser().resolve()
    records = run_probe(target_dir, pause_for_manual_edit=args.pause_for_manual_edit)

    print(f"Probe directory: {target_dir}")
    for record in records:
        print_snapshot(record)

    if args.json_out:
        out_path = Path(args.json_out).expanduser().resolve()
        out_path.write_text(
            json.dumps([asdict(r) for r in records], indent=2), encoding="utf-8"
        )
        print(f"\nWrote JSON report to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
