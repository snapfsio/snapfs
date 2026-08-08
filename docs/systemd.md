# Systemd Agent Management

This guide covers installing, enabling, disabling, and uninstalling SnapFS
scanner agents managed by `systemd` on Linux.

## Install A Scanner Agent

For Linux hosts that should run the SnapFS scanner agent as a service, the
preferred flow is:

```bash
curl -fsSL https://raw.githubusercontent.com/snapfsio/snapfs/master/install.sh | bash
```

The bootstrap installer verifies `python3`, creates a managed virtual
environment under `/opt/snapfs`, resolves the latest GitHub release, downloads
the corresponding source archive, installs `snapfs[xxhash]`, and then launches
the systemd installer for scanner-specific configuration.

If the host is missing a usable virtual environment backend, the installer can
prompt to install the required system package automatically on supported Linux
distributions such as Debian, Ubuntu, Rocky, RHEL, Fedora, CentOS, and AlmaLinux.

To pin a specific release version, set `SNAPFS_VERSION`:

```bash
curl -fsSL https://raw.githubusercontent.com/snapfsio/snapfs/master/install.sh | \
  SNAPFS_VERSION=0.4.2 bash
```

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
sudo apt install python3-venv
```

```bash
sudo dnf install python3-virtualenv
```

If your host uses a non-default system Python, install the matching
`python3.<minor>-venv` package instead.

If you prefer to manage the Python environment yourself, the manual path is
still available:

```bash
pip install .[xxhash]
./systemd/install.sh
```

For production service installs, prefer installing `snapfs` into a stable
system-level Python environment rather than a user-local virtualenv.

If agent throughput matters on that host, prefer installing with `xxhash`
support and set `SNAPFS_HASH_ALGO=xxh64` during service configuration or when
re-running the installer.

Current systemd installer support is Linux-only. Windows service support is
planned but not available yet.

When choosing the hash algorithm interactively, the installer presents a
numbered list of the algorithms supported by the selected `snapfs` runtime. For
example, `xxh64` is listed when the managed install includes the optional
`xxhash` dependency.

## Current Install Style

The current installer creates named systemd instance units such as
`snapfs-agent@scanner-01.service`, backed by per-instance config files like
`/etc/snapfs/agent-scanner-01.env`.

Typical per-instance paths:

- systemd template: `/etc/systemd/system/snapfs-agent@.service`
- enabled instance: `/etc/systemd/system/multi-user.target.wants/snapfs-agent@scanner-01.service`
- config file: `/etc/snapfs/agent-scanner-01.env`
- state directory: `/var/lib/snapfs/scanner-01`

## Disable Or Re-Enable A Scanner

To temporarily stop a scanner and prevent it from starting at boot without
removing its config:

```bash
sudo systemctl disable --now snapfs-agent@scanner-01.service
```

To start it again later:

```bash
sudo systemctl enable --now snapfs-agent@scanner-01.service
```

Useful inspection commands:

```bash
sudo systemctl status snapfs-agent@scanner-01.service
sudo journalctl -u snapfs-agent@scanner-01.service -f
find /etc/systemd/system -name 'snapfs-agent*'
```

## Uninstall A Scanner Instance

To uninstall an installed scanner instance, run the uninstaller and choose one
of the discovered scanner names such as `scanner-01`:

```bash
./systemd/uninstall.sh
```

Example non-interactive uninstall:

```bash
sudo SNAPFS_SCANNER_NAME=scanner-01 ./systemd/uninstall.sh --as-root
```

If you also want to remove that instance's state directory:

```bash
sudo SNAPFS_SCANNER_NAME=scanner-01 REMOVE_STATE=1 ./systemd/uninstall.sh --as-root
```

The uninstaller removes:

- the systemd instance `snapfs-agent@scanner-01.service`
- the per-instance config file `/etc/snapfs/agent-scanner-01.env`

By default it leaves the instance state directory in place unless you opt in to
removing it.
