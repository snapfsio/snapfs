# SnapFS Scripts

## `bench_scan.py`

`bench_scan.py` is the recommended way to benchmark normalized SnapFS scan-engine performance locally without requiring a gateway URL, API key, or event publishing.

What it measures:
- directory walking
- stat/probe flow
- hashing
- local publish/event construction overhead against an in-memory fake gateway

What it does not measure:
- real gateway network latency
- API authentication overhead
- Elasticsearch ingestion/query overhead
- console rendering latency

### Basic usage

```bash
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --algo sha256
```

Warm-cache style run:

```bash
python3 scripts/bench_scan.py /path/to/tree --cache-mode hit --workers 2
```

Structured JSON output:

```bash
python3 scripts/bench_scan.py /path/to/tree --force --workers 2 --json
```

### Benchmark guidance

For comparisons, keep these inputs stable:
- dataset/path
- hash algorithm
- worker count
- hash chunk size
- cache mode (`hit` vs `miss`)
- `--force` usage

Recommended practice:
- warm both tools before comparing them
- record whether the run is cold or warm
- compare several runs, not just one
- capture the JSON output if you want to publish or collate results later

### Captured metadata

The script captures a small amount of system context in JSON output so runs are easier to compare later:
- timestamp
- hostname
- platform
- Python version
- SnapFS version
- logical CPU count
- CPU model
- total memory

This metadata is intended for context, not for mathematically "normalizing" the score. For filesystem scanners, the most honest approach is to keep the benchmark command stable and compare like-for-like runs.
