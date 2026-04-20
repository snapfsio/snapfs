# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- _No unreleased additions yet_

### Changed
- _No unreleased changes yet_

### Fixed
- _No unreleased fixes yet_

---

## [0.4.2] - 2026-04-20

### Added
- Added a first-class `--api-key` CLI option for `scan` and `agent`, backed by `SNAPFS_API_KEY`.
- Added a small `.env` example to the README to show the common gateway, API key, agent id, and scan root configuration.

### Changed
- Changed CLI gateway handling so users must provide `--gateway` or `SNAPFS_GATEWAY` explicitly instead of inheriting the localhost development default in command usage.
- Simplified gateway help text so user-facing CLI help no longer advertises the local development gateway default.
- Marked `--token` as an advanced auth path while keeping it available for explicit bearer-token workflows.

---

## [0.4.1] - 2026-03-29

### Changed
- Removed the unsupported raw SQL query surface from the SnapFS client library so command-line usage stays aligned with supported console workflows.

### Fixed
- Removed lingering gateway helper support for raw SQL query execution now that the public gateway API explicitly blocks arbitrary SQL access.

---

## [0.4.0] - 2026-03-28

### Added
- Added configurable hash algorithm selection for scans and agents, including optional `xxh64` support when the extra dependency is installed.
- Added scanner hash performance controls for worker count and hash chunk size via CLI and environment configuration.
- Added richer large-file scan telemetry, including hashing phase progress and processed-byte reporting.
- Added a local `scripts/bench_scan.py` benchmark utility plus benchmark guidance in `scripts/README.md`.

### Changed
- Changed scan execution from a fully serialized walk-then-process flow to a pipelined single-host walk/hash/publish model.
- Improved scan responsiveness on warm-cache and medium-tree workloads by overlapping walking, probing, hashing, and publishing.
- Improved running scan telemetry so large-file jobs no longer appear deceptively idle in downstream consumers.

### Fixed
- Fixed early `Ctrl+C` interrupt handling so cancelled scans publish a reliable terminal `scan.cancelled` event.
- Fixed runtime resolution of CLI hash defaults so settings-based defaults and explicit CLI overrides behave correctly.
- Tightened scanner and CLI regression coverage around multi-worker hashing, hardlink de-dupe, telemetry, cancellation, and hash-option precedence.

---

## [0.3.1] - 2026-03-27

### Added
- Added scanner heartbeat diagnostics to make agent liveness easier to monitor during long-running scans.
- Added scan telemetry for total bytes processed and calculated bytes-per-second throughput.
- Added operator-driven scan cancellation support.
- Added support for multi-instance systemd agent installs with a templated `snapfs-agent@.service` unit.

### Changed
- Kept the agent WebSocket responsive while scans are running so heartbeat processing can continue.
- Kept scans running across agent reconnects instead of dropping in-progress work.
- Improved systemd install defaults for multi-instance deployments.
- Advertised the agent version in agent connectivity flows.

### Fixed
- Kept agent scan handling backward-compatible with the existing test expectations while the new scan-control behavior landed.

---

## [0.3.0] - 2026-03-18

### Added
- Added explicit `scan.cancelled` and `scan.failed` terminal events so interrupted scans report a clear final state.
- Added broad automated test coverage for the scanner, CLI, gateway helpers, config, and agent behavior.
- Added GitHub Actions test coverage across platforms.

### Changed
- Expanded scan telemetry to include hash, walk, and permission error counts, plus an `authoritative_for_deletes` flag.
- Hardened the systemd install and uninstall scripts and refreshed the agent service defaults.
- Removed checked-in `build/lib` package artifacts from the release.

### Fixed
- Fixed Windows-stable hashing test fixtures and tightened scan error handling around cancellation and failure paths.

---

## [0.2.4] - 2026-03-09

### Added
- Added scanner and agent trigger propagation so scans can report how they were started.
- Added initial periodic scan telemetry publishing during active runs.

### Changed
- Switched gateway HTTP endpoints to `/api/*`.
- Changed the default gateway port to `8080`.
- Changed the default agent WebSocket control path to `/ws/agents`.
- Expanded agent, scanner, and CLI configuration around gateway connectivity and scan telemetry.

### Fixed
- Treated WebSocket send-on-close during reconnect and shutdown as a non-fatal condition.
- Fixed duplicate telemetry and probe payload handling in scan reporting.

---

## [0.2.2] - 2026-01-22

### Added
- Added initial `systemd` install and uninstall scripts plus a `snapfs-agent.service` unit for running the scanner agent as a service.
- Added an extra agent CLI option to improve runtime configuration.

### Changed
- Refactored CLI option handling so gateway and token flags are applied consistently per command.
- Improved gateway URL handling by deriving the WebSocket endpoint from the configured gateway URL.
- Refreshed README and inline docstrings to match the agent-based workflow.

---

## [0.2.1] - 2025-12-13

### Added
- Added agent mode with a long-lived WebSocket worker that accepts remote `SCAN_TARGET` commands.
- Added configuration for agent identity, scan root, ping interval, and gateway WebSocket connectivity.
- Added a `snapfs agent` CLI command for running the scanner agent from the command line.

### Changed
- Added `pydantic`-backed settings management for environment-driven configuration.

---

## [0.2.0] - 2025-12-08

### Added
- Added scan lifecycle events with `scan.started` and `scan.completed` payloads.
- Added per-file scan context such as `scan_id`, `root_path`, and `seen_at` metadata to published events.

### Changed
- Changed scans to always publish file metadata, even when the cache already has a matching file hash.
- Changed `--force` to re-hash files instead of only re-sending cached metadata.
- Updated CLI summary output so verbose scans print the JSON summary at `-v`.

---

## [0.1.1] - 2025-12-05

### Added
- Added repeatable `-v` and `--verbose` scan output levels.
- Added a CLI version flag wired to the packaged project version.

### Changed
- Changed scan output so hash progress is shown only when verbosity is enabled and cache-hit details require higher verbosity.
- Normalized cached file `mtime` values to integer precision in scanner probes.

---

## [0.1.0] - 2025-11-16

### Added
- Initial release of the SnapFS Python client and CLI.
- Added the core gateway client, filesystem scanner, configuration module, and command-line entrypoint.
- Added project packaging metadata, license, and README documentation.
