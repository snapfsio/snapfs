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
pip install snapfs[xxhash]
```

or from source:

```bash
pip install -e .[xxhash]
```

If scan performance matters on a host, especially for many-small-file trees or
warm-cache repeat scans, `xxh64` is worth testing.

## Example `.env`

For agent or CLI-based scans, a minimal environment file often looks like:

```dotenv
SNAPFS_GATEWAY=https://example.snapfs.com
SNAPFS_API_KEY=YOUR_API_KEY
SNAPFS_AGENT_ID=scanner-01
SNAPFS_SCAN_ROOT=/mnt/data
```

You can export these values in your shell, load them from a local `.env`, or translate them into your service manager configuration.

## Install The Systemd Agent

For Linux hosts that should run the SnapFS scanner agent as a service, the
preferred bootstrap flow is:

```bash
curl -fsSL https://raw.githubusercontent.com/snapfsio/snapfs/master/install.sh | bash
```

This bootstrap installer verifies `python3`, creates a managed virtual
environment under `/opt/snapfs`, installs `snapfs[xxhash]`, and then hands off
to the systemd installer for scanner-specific configuration.

If you prefer to review the script locally first, the repo-based fallback
remains available:

```bash
git clone https://github.com/snapfsio/snapfs
cd snapfs
./install.sh
```

For broader installation guidance, including the bootstrap installer and
filesystem layout, see [`docs/install.md`](docs/install.md). For ongoing service
management, including enabling, disabling, uninstalling, and legacy standalone
service cleanup, see [`docs/systemd.md`](docs/systemd.md).

## Development

Install developer dependencies:

```bash
pip install -e .[dev]
```

Install benchmark dependencies:

```bash
pip install -e .[benchmarks]
```

This installs the in-repo benchmark extras such as `tqdm` and `xxhash`.

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
snapfs scan /mnt/projects --algo xxh64
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

How to choose:
- `sha1`: current default. Use this when you want the standard out-of-the-box SnapFS behavior and do not need to optimize hash throughput yet.
- `xxh64`: best first option to test when performance matters and `xxhash` is installed. It is often much faster on CPU-limited, warm-cache, or many-small-file workloads.
- `sha256`: use this when you specifically prefer a SHA-256 hash over the default `sha1`, even if it may cost more CPU time than `xxh64`.

Examples:

```bash
snapfs scan /mnt/projects
snapfs scan /mnt/projects --algo xxh64
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
For a representative results table and interpretation notes, see
[`docs/benchmarks.md`](docs/benchmarks.md).

### Cross-Platform Notes

SnapFS supports Python 3.8+ and is tested across Linux, macOS, and Windows.

A few practical notes:
- Linux is currently the primary environment for service installs via systemd
- hash worker multiprocessing is designed to stay compatible with Windows spawn semantics
- service-install tooling is Linux-only today

## Documentation

Additional docs live under [`docs/`](docs/):

- [`docs/README.md`](docs/README.md)
- [`docs/install.md`](docs/install.md)
- [`docs/systemd.md`](docs/systemd.md)
- [`docs/scanner.md`](docs/scanner.md)

## Requirements

- Python 3.8+
