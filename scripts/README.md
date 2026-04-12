# SnapFS Scripts

This directory contains helper scripts for local SnapFS workflows.

For benchmark methodology, dataset selection, storage notes, and result interpretation, use [`docs/benchmarks.md`](/mnt/homes/rsg/dev/snapfs/docs/benchmarks.md) as the primary reference.

## `fs_identity_probe.py`

Use `fs_identity_probe.py` to inspect how a filesystem/editor changes inode, link count, and content identity for the same logical path. This is useful when debugging `create` vs `update` behavior across local disks, NFS, and replace-write editor saves.

```bash
python3 scripts/fs_identity_probe.py /tmp/snapfs-fs-test
python3 scripts/fs_identity_probe.py /mnt/nfs/share/snapfs-fs-test --pause-for-manual-edit
```

## `bench_scan.py`

Benchmark the local scan engine without requiring a real gateway:

```bash
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --algo sha256
python3 scripts/bench_scan.py /path/to/tree --cache-mode hit --workers 2
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --json
```

## `run_benchmarks.py`

Run the benchmark matrix from [`scripts/benchmark_matrix.json`](/mnt/homes/rsg/dev/snapfs/scripts/benchmark_matrix.json):

```bash
python3 scripts/run_benchmarks.py
python3 scripts/run_benchmarks.py --list
python3 scripts/run_benchmarks.py -o tmp/benchmark-results.json
python3 scripts/run_benchmarks.py --from-json benchmark-results.json
python3 scripts/run_benchmarks.py --list --dataset large-files
```

Recommended benchmark environment setup:

```bash
pip install -e .[benchmarks]
```

The runner writes JSON results and prints an ASCII table in the terminal.
