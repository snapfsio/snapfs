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

`run_benchmarks.py` looks for `./benchmark_matrix.json` in your current working
directory by default.

This repo includes [`example_benchmark_matrix.json`](example_benchmark_matrix.json)
as an example matrix. Copy it into the directory where you want to run the
benchmarks, then update the dataset paths, algorithms, worker counts, and other
settings for that host before running the script.

Example setup:

```bash
mkdir -p /tmp/snapfs-bench
cp scripts/example_benchmark_matrix.json /tmp/snapfs-bench/benchmark_matrix.json
$EDITOR /tmp/snapfs-bench/benchmark_matrix.json
cd /tmp/snapfs-bench
python3 /path/to/snapfs/scripts/run_benchmarks.py
```

If benchmarking or production scan throughput matters on that host, install
`xxhash` first so you can include `xxh64` in the matrix:

```bash
pip install -e .[xxhash]
```

See [`docs/benchmarks.md`](/mnt/homes/rsg/dev/snapfs/docs/benchmarks.md) for a
representative sample results table and guidance on how to interpret `xxh64`
vs SHA-based runs.

You can point at a matrix file explicitly with `--matrix`:

```bash
python3 scripts/run_benchmarks.py
python3 scripts/run_benchmarks.py --list
python3 scripts/run_benchmarks.py -o tmp/benchmark-results.json
python3 scripts/run_benchmarks.py --display benchmark-results.json
python3 scripts/run_benchmarks.py --list --dataset large-files
python3 scripts/run_benchmarks.py --matrix /path/to/benchmark_matrix.json
```

Recommended benchmark environment setup:

```bash
pip install -e .[benchmarks]
```

The runner writes JSON results and prints an ASCII table in the terminal.
