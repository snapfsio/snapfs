# SnapFS (Python Client)

SnapFS is a file indexing and metadata system designed for large-scale production
environments such as VFX, animation, gaming, simulation, and data pipelines.

This repository contains the Python client and CLI for interacting with a SnapFS
gateway.

The client provides tools for scanning directories, publishing file metadata, and
querying indexed results through a gateway API.

## Features

- Filesystem scanning and metadata ingestion
- Cache-aware incremental hashing
- Async gateway client built on aiohttp
- Python API for querying indexed data
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

Scan a directory and publish metadata to the gateway:

```bash
snapfs scan /mnt/projects
```

## Requirements

- Python 3.8+
- A running SnapFS gateway (for ingestion and querying)

## Status

*Early development.*

APIs, schemas, and endpoints may evolve rapidly before the 1.0 release.
