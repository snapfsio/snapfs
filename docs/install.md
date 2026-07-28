# Installation Guide

This guide describes the current SnapFS installation flows and the Linux
bootstrap installer used for managed service installs.

## Current Install Modes

Today SnapFS supports two main installation patterns:

- CLI or development installs using `pip`
- Linux service installs using the bootstrap and `systemd` helper scripts in this repo

Examples:

```bash
pip install snapfs
```

```bash
pip install -e .
```

```bash
pip install snapfs[xxhash]
```

For Linux service installs, the preferred flow is:

```bash
curl -fsSL https://raw.githubusercontent.com/snapfsio/snapfs/master/install.sh | bash
```

The bootstrap script verifies a supported `python3`, creates a managed virtual
environment under `/opt/snapfs`, resolves the latest GitHub release, downloads
the corresponding source archive, installs `snapfs[xxhash]`, and then launches
the systemd installer with the resolved `snapfs` binary.

To pin a specific release version, set `SNAPFS_VERSION`:

```bash
curl -fsSL https://raw.githubusercontent.com/snapfsio/snapfs/master/install.sh | \
  SNAPFS_VERSION=0.4.2 bash
```

If the latest-release lookup fails, the bootstrap falls back to a pinned
default release.

If you prefer to review the script locally before running it, the repo-based
fallback remains available:

```bash
git clone https://github.com/snapfsio/snapfs
cd snapfs
./install.sh
```

The manual fallback remains available when you want to manage the Python
environment yourself:

```bash
pip install .[xxhash]
./systemd/install.sh
```

## Bootstrap Goals

The Linux bootstrap installer is designed to:

- verify a supported Python runtime is available
- resolve a release version or accept `SNAPFS_VERSION` explicitly
- fetch a SnapFS source archive when not already running from a repo checkout
- create a stable managed virtual environment
- install the `snapfs` CLI into that managed environment
- invoke the systemd service installer with the resolved `snapfs` binary

The intent is to make the host bootstrap experience simpler while keeping the
systemd-specific logic focused and reusable.

## Linux Bootstrap Flow

The entrypoint is the root-level `install.sh` in the repository root.

Responsibility split:

- `install.sh`
  - bootstrap host prerequisites
  - resolve the target SnapFS release
  - fetch and unpack the SnapFS source archive when needed
  - verify `python3` version compatibility
  - create a managed virtual environment
  - install `snapfs` into that environment
  - invoke `systemd/install.sh` with `SNAPFS_BIN`
- `systemd/install.sh`
  - collect scanner configuration
  - install the systemd unit template
  - write per-instance agent config
  - enable and start the selected scanner instance

This keeps the top-level installer responsible for environment setup and keeps
the systemd installer responsible for service configuration.

## Recommended Filesystem Layout

The intended Linux layout is split by responsibility rather than placing
everything under a single directory.

- `/etc/snapfs`
  - configuration only
  - per-instance env files such as `agent-scanner-01.env`
- `/var/lib/snapfs`
  - mutable state
  - per-instance working directories such as `/var/lib/snapfs/scanner-01`
- `/opt/snapfs`
  - managed application runtime
  - virtual environment and installed package payload

This layout aligns with normal Linux expectations:

- `/etc` for configuration
- `/var/lib` for service state
- `/opt` for self-contained application installs

The installer should avoid introducing extra metadata files unless they become
necessary. Prefer deriving current state from:

- the managed runtime location
- the installed systemd unit files
- the agent env files under `/etc/snapfs`
- `snapfs --version`

## Current Bootstrap Scope

The current bootstrap installer stays conservative and portable:

- require an existing `python3` on the host
- require `python3 >= 3.8`
- fail early with a clear message if Python is missing or too old
- fetch the latest GitHub release by default, with a pinned fallback if lookup fails
- create a managed environment under `/opt/snapfs/venv`
- install from the fetched archive or local repo checkout
- include `xxhash` by default
- pass the resolved binary path into `systemd/install.sh`

During the handoff, the systemd installer uses the managed `snapfs` binary from
`/opt/snapfs/venv/bin/snapfs` and offers an interactive numbered menu for hash
algorithm selection based on the algorithms available in that runtime.

This improves the operator experience without trying to solve distro-specific
package installation on day one.

## Future Enhancements

Possible later improvements:

- install from published releases instead of only a local checkout
- support wheel or source tarball installs for offline environments
- provide a Windows bootstrap path such as `install.ps1`
- optionally auto-install missing Python packages on supported Linux distros

Windows support should be treated as a later phase. Today Linux and `systemd`
remain the primary service-install target.

## Related Docs

- [`systemd.md`](systemd.md) for Linux service installation and agent management
- [`scanner.md`](scanner.md) for scanner behavior, hashing, and benchmarking
