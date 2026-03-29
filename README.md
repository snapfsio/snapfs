# SnapFS (Python Client)

SnapFS is a file indexing and metadata system designed for large-scale production
environments such as VFX, animation, gaming, simulation, and data pipelines.

### Status

*Early development.*

APIs, schemas, and endpoints may evolve rapidly before the 1.0 release.

## Features

- Filesystem scanning and metadata ingestion
- Cache-aware incremental hashing
- Configurable hash algorithms (`sha1`, `sha256`, optional `xxh64`)
- Hash performance tuning (`--workers`, `--hash-chunk-size`)
- Large-file telemetry with phase/progress reporting
- Async gateway client built on aiohttp
- Command-line interface for common operations
- Local benchmark helper for normalized scan-engine comparisons

## Installation

```bash
pip install snapfs
```

or install from source:

```bash
pip install -e .
```

To enable optional `xxh64` hashing support:

```bash
pip install -e .[xxhash]
```

## Install The Systemd Agent

For Linux hosts that should run the SnapFS scanner agent as a service:

```bash
git clone https://github.com/snapfsio/snapfs
cd snapfs
pip install .
./systemd/install.sh
```

The installer expects the `snapfs` CLI to already be installed and available in `PATH`. Run the installer as your normal user; it will prompt for elevated privileges when it reaches the root-only systemd setup steps.

For production service installs, prefer installing `snapfs` into a stable system-level Python environment rather than a user-local virtualenv.

Current systemd installer support is Linux-only. Windows service support is planned but not available yet.

## Development

Install developer dependencies:

```bash
pip install -e .[dev]
```

Run the test suite:

```bash
pytest -q
```

## Quick Start

Scan a directory and publish metadata:

```bash
snapfs scan /mnt/projects
```

Select a hash algorithm explicitly:

```bash
snapfs scan /mnt/projects --algo sha256
```

Tune local hashing performance:

```bash
snapfs scan /mnt/projects --workers 4 --hash-chunk-size 2097152
```

## Scanner Capabilities

### Hash Algorithm Selection

SnapFS supports configurable hash algorithms for both direct scans and long-running agents.

Currently supported:
- `sha1`
- `sha256`
- `xxh64` when installed with the optional `xxhash` extra

Examples:

```bash
snapfs scan /mnt/projects --algo sha256
snapfs agent --algo sha256 --gateway https://tenant.snapfs.com
```

Environment defaults are also supported:
- `SNAPFS_HASH_ALGO`
- `SNAPFS_HASH_WORKERS`
- `SNAPFS_HASH_CHUNK_SIZE`

### Performance Tuning

You can tune hashing behavior for different hosts and datasets with:
- `--workers`
- `--hash-chunk-size`

These settings are especially useful for:
- large-file workloads
- warm-cache repeat scans
- comparing different hardware or filesystem setups

### Large-File Telemetry

Running scans now emit richer telemetry so large-file hashing work does not appear deceptively idle.
Telemetry includes phase/progress information such as:
- walking vs hashing vs publishing
- processed bytes
- hashed bytes
- active hash jobs

### Local Benchmarking

Use the local benchmark helper when you want to compare scan-engine performance without requiring a gateway URL or API key:

```bash
python3 scripts/bench_scan.py /mnt/projects --force --workers 2 --algo sha256
```

See `scripts/README.md` for benchmarking guidance and `--json` output details.

### Cross-Platform Notes

SnapFS supports Python 3.8+ and is tested across Linux, macOS, and Windows.

A few practical notes:
- Linux is currently the primary environment for service installs via systemd
- hash worker multiprocessing is designed to stay compatible with Windows spawn semantics
- service-install tooling is Linux-only today

## Documentation

Additional docs live under [`docs/`](docs/):

- [`docs/README.md`](docs/README.md)
- [`docs/scanner.md`](docs/scanner.md)

## Requirements

- Python 3.8+
