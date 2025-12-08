# SnapFS (Python Client)

SnapFS is a modern, scalable file indexing and metadata system designed for large-scale
production environments such as VFX, animation, gaming, simulation, and machine learning
pipelines.

This repository contains the **Python client and CLI** for interacting with a SnapFS
gateway, including:

- Directory scanning and metadata ingestion  
- Cache-aware incremental hashing  
- File queries  
- Gateway API access  

SnapFS Python client communicates with a running SnapFS gateway and provides a simple
domain-centric interface for querying files, snapshots, and related metadata.

---

## Features (Current)

- Async gateway client using `aiohttp`
- Domain-focused Python API (`snapfs.files`, `snapfs.events`, …)
- Filesystem scanner with:
  - Incremental hashing
  - Cache probing
  - Rich metadata collection (mtime, ctime, owners, permissions, links, etc.)
  - Hardlink-aware disk usage (`fsize_du`)
- CLI commands:
  - `snapfs scan <path>`  
  - `snapfs query "<SQL>"`

---

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
