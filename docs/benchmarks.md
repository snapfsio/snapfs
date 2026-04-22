# Benchmarks

This page defines a practical benchmark suite for SnapFS and a shared format for recording results.

The goal is not to produce a single universal score. The goal is to make it easy to compare:

- SnapFS runs against other runs of SnapFS
- large-file behavior against small-file behavior
- cold-path hashing against cache-hit scans

## Scope

The benchmark suite should answer a few concrete questions:

- Is SnapFS in the right performance range for large-file scans?
- Is SnapFS in the right performance range for many-small-file scans?
- How much does the selected hash algorithm matter on a given dataset?
- How much does worker count matter on a given dataset?
- How much overhead comes from the full SnapFS scan path beyond raw hashing?

## Benchmark Environment

Install benchmark-specific Python dependencies with:

```bash
pip install -e .[benchmarks]
```

This extra is intended for local benchmark execution and currently includes:

- `tqdm` for optional progress bars in the benchmark runner
- `xxhash` for `xxh64` SnapFS benchmark coverage

If scan throughput matters on a host, prefer installing `xxhash` support before
benchmarking so you can compare `xxh64` against the SHA-based defaults:

```bash
pip install snapfs[xxhash]
```

## Storage Notes

Benchmark results depend heavily on where the dataset lives.

Preferred benchmark targets:

- local disks or local filesystems
- stable dataset roots with consistent permissions
- datasets that are not being modified during the run

Be careful with network-mounted or layered filesystems such as:

- NFS
- SMB/CIFS
- FUSE-based mounts
- merger or overlay filesystems

These can introduce large first-read penalties, metadata-cache effects, mount-level read-ahead differences, and other behaviors that make repeated runs less stable. If you benchmark on NFS or another remote/shared mount, record that fact clearly and expect the first full-read run on a dataset to be much slower than later runs.

## Repository Layout

Use the repository this way:

- [`scripts/bench_scan.py`](/mnt/homes/rsg/dev/snapfs/scripts/bench_scan.py) remains the core local SnapFS benchmark entrypoint.
- [`scripts/example_benchmark_matrix.json`](/mnt/homes/rsg/dev/snapfs/scripts/example_benchmark_matrix.json) is the example matrix to copy and customize per host.
- [`scripts/run_benchmarks.py`](/mnt/homes/rsg/dev/snapfs/scripts/run_benchmarks.py) lists or executes the benchmark suite locally.
- [`docs/benchmarks.md`](/mnt/homes/rsg/dev/snapfs/docs/benchmarks.md) defines the benchmark matrix, commands, and result format.
- Future benchmark helpers or wrappers should live in [`scripts/`](/mnt/homes/rsg/dev/snapfs/scripts).

That keeps the benchmark definition in documentation and the runnable harness in `scripts/`, which is a good fit for this repo.

## Datasets

At minimum, benchmark two dataset shapes.

### Large-File Dataset

Use a tree with a small number of large files.

What it measures:

- sequential read throughput
- hash throughput on large files
- scaling with worker count when files are large enough to overlap usefully

Useful metrics:

- elapsed seconds
- MiB/s

### Small-File Dataset

Use a tree with many small files.

What it measures:

- directory walking cost
- `stat` cost
- per-file scheduling overhead
- batching and event construction overhead
- whether extra workers help or hurt on tiny files

Useful metrics:

- elapsed seconds
- files/sec

## Benchmark Matrix

Use this matrix as the default suite.

### Required SnapFS Runs

For each dataset:

- algorithms: `sha256`, `xxh64` when available
- workers: `1`, `2`, `4`, `8`
- modes:
  - `--force`
  - `--cache-mode hit`
- repeats: `3`

If `xxh64` is available, include it in the default matrix. Many hosts will see
substantially better throughput on CPU-limited or many-small-file workloads.

## Commands

### SnapFS

Large or small dataset, forced hash:

```bash
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --algo xxh64
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --algo sha256
```

Cache-hit comparison:

```bash
python3 scripts/bench_scan.py /path/to/tree --cache-mode hit --workers 2
```

### sha256sum

If you want a simple system baseline for `sha256`, record it separately and note the command used for traversal. For example:

```bash
find /path/to/tree -type f -print0 | xargs -0 sha256sum >/dev/null
```

This is not identical to SnapFS scan behavior, so keep it labeled as a rough external baseline.

## Notes On Interpretation

Interpret large-file and small-file results differently.

Large-file runs usually emphasize:

- storage throughput
- read-ahead behavior
- whether hashing is CPU-bound or I/O-bound

Small-file runs usually emphasize:

- metadata overhead
- per-file dispatch overhead
- batching strategy
- scheduler and process-pool costs

If `xxh64` is only slightly faster than `sha256`, that usually suggests the benchmark is not hash-CPU-bound on that dataset and host.

If `xxh64` is much faster than `sha256` on a small-file or warm-cache run, that
usually means hashing overhead is a meaningful part of the scan cost on that
host. In that situation, enabling `xxhash` for production scanner installs is
usually worth trying.

When benchmarking on NFS or other remote/shared mounts, the first force scan of a dataset may reflect storage warmup more than steady-state scan performance. In that situation, compare like-for-like warmed runs and record the mount type in your notes.

## Sample Result Table

This is a representative example of what a useful comparison table can look
like. The exact numbers are host- and dataset-dependent, but this shape is what
you should expect to compare:

| Dataset | Tool | Mode | Algo | Workers | Files | Bytes | Elapsed s | MiB/s | Files/s | Repeat | Notes |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| small-files | snapfs | force | sha1 | 4 | 717 | 0.69 GiB | 0.813 | 872.5 | 881.827 | 2 | warmed run |
| small-files | snapfs | force | xxh64 | 4 | 717 | 0.69 GiB | 0.319 | 2223.5 | 2249.476 | 1 | warmed run |
| large-files | snapfs | force | sha1 | 4 | 129 | 27.20 GiB | 258.104 | 107.9 | 0.500 | 2 | storage-limited |
| large-files | snapfs | force | xxh64 | 4 | 129 | 27.20 GiB | 256.301 | 108.7 | 0.503 | 3 | storage-limited |

In this example, `xxh64` clearly improves the small-file case, while the
large-file case stays near the same MiB/s because the storage path is the
bottleneck. That is a common pattern and a good reason to benchmark both
dataset shapes before choosing defaults.

## Result Table

Use one shared table for your actual SnapFS runs.

| Dataset | Tool | Mode | Algo | Workers | Files | Bytes | Elapsed s | MiB/s | Files/s | Repeat | Notes |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| large-files | snapfs | force | xxh64 | 2 | 286 | 67.7 GiB | 675.7 | 102.7 | 0.423 | 1 | full scan path |
| large-files | snapfs | force | sha256 | 2 | 286 | 67.7 GiB | 692.0 | 100.3 | 0.413 | 1 | same dataset |

## Summary Template

After filling in the raw table, write a short summary under it:

- Best worker count for large-file dataset:
- Best worker count for small-file dataset:
- Large-file result appears:
- Small-file result appears:
- `xxh64` vs `sha256` conclusion:
- Open questions:

## Future Script Placement

The current benchmark suite files live in [`scripts/run_benchmarks.py`](/mnt/homes/rsg/dev/snapfs/scripts/run_benchmarks.py) and [`scripts/example_benchmark_matrix.json`](/mnt/homes/rsg/dev/snapfs/scripts/example_benchmark_matrix.json).

The runner can:

- execute the SnapFS matrix
- emit JSON plus a terminal table for the shared results view
