# Scanner Guide

This guide covers the current SnapFS scanner capabilities added in the 0.4.x scanner work.

## Hash Algorithms

SnapFS supports configurable hash algorithms for scans and agents.

Available now:
- `sha1`
- `sha256`
- `xxh64` with the optional `xxhash` dependency installed

Examples:

```bash
snapfs scan /mnt/projects --algo sha256
snapfs agent --algo sha256 --gateway https://tenant.snapfs.example
```

Optional `xxhash` install:

```bash
pip install snapfs[xxhash]
```

or from source:

```bash
pip install -e .[xxhash]
```

If scan throughput matters on a host, especially for many-small-file trees,
install `xxhash` and benchmark `xxh64`. It is often materially faster than the
SHA-based options when hashing cost is the bottleneck.

## Performance Controls

SnapFS exposes two primary scan tuning knobs:
- hash workers
- hash chunk size

CLI examples:

```bash
snapfs scan /mnt/projects --workers 4 --hash-chunk-size 2097152
```

Environment variables:
- `SNAPFS_HASH_ALGO`
- `SNAPFS_HASH_WORKERS`
- `SNAPFS_HASH_CHUNK_SIZE`

These controls are useful when comparing:
- small-file vs large-file trees
- CPU-limited vs IO-limited hosts
- warm-cache vs cold-cache behavior

## Scan Telemetry

Recent scanner updates improve telemetry for large-file scans.

Telemetry now includes richer progress data such as:
- phase (`walking`, `probing`, `hashing`, `publishing`)
- files discovered
- bytes processed
- bytes hashed
- active hash jobs

This helps downstream consumers show progress even when a scan is hashing a small number of very large files.

## Local Benchmarking

Use `scripts/bench_scan.py` to benchmark the scan engine locally without a real gateway or API key.

Example:

```bash
python3 scripts/bench_scan.py /mnt/projects --force --workers 2 --algo sha256
```

Warm-cache comparison:

```bash
python3 scripts/bench_scan.py /mnt/projects --cache-mode hit --workers 2
```

JSON output:

```bash
python3 scripts/bench_scan.py /mnt/projects --force --workers 2 --json
```

The JSON output includes lightweight system metadata to help compare runs later, but the benchmark should still be interpreted as a like-for-like comparison tool rather than a mathematically normalized score.

## Platform Notes

SnapFS supports Python 3.8+ and is tested across Linux, macOS, and Windows.

Notes:
- Linux is the primary environment for systemd-based service installs
- Windows multiprocessing uses spawn semantics, so SnapFS avoids relying on shared mutable state between worker processes
- service-install scripts are currently Linux-only
