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

If the host is missing a usable virtual environment backend, the installer can
prompt to install the required system package automatically on supported Linux
distributions such as Debian, Ubuntu, Rocky, RHEL, Fedora, CentOS, and AlmaLinux.

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

If the bootstrap path still fails on a target host, install the distro package
for the virtual environment backend and re-run the installer:

```bash
sudo apt install python3.x-venv
```

```bash
sudo dnf install python3-virtualenv
```

Replace `python3.x-venv` with the package matching your system Python version.

If you prefer not to use the bootstrap flow, you can still install `snapfs`
into your own Python environment and run the systemd installer directly.

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

## Filesystem Layout

The install Linux layout is split by responsibility:

- `/etc/snapfs`
  - configuration only
  - per-instance env files such as `agent-scanner-01.env`
- `/var/lib/snapfs`
  - mutable state
  - per-instance working directories such as `/var/lib/snapfs/scanner-01`
- `/opt/snapfs`
  - managed application runtime
  - virtual environment and installed package payload

## Related Docs

- [`systemd.md`](systemd.md) for Linux service installation and agent management
- [`scanner.md`](scanner.md) for scanner behavior, hashing, and benchmarking
