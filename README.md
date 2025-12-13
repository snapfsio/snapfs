# SnapFS (Python Client)

SnapFS is a file indexing and metadata system designed for large-scale production
environments such as VFX, animation, gaming, simulation, and data pipelines.

### Status

*Early development.*

APIs, schemas, and endpoints may evolve rapidly before the 1.0 release.

## Features

- Filesystem scanning and metadata ingestion
- Cache-aware incremental hashing
- Async gateway client built on aiohttp
- Command-line interface for common operations

## Installation

```bash
pip install snapfs
```

or install from source:

```bash
pip install -e .
```

## Quick Start

Scan a directory and publish metadata:

```bash
snapfs scan /mnt/projects
```

## Requirements

- Python 3.8+
