# Systemd Agent Management

This guide covers installing, enabling, disabling, and uninstalling SnapFS
scanner agents managed by `systemd` on Linux.

## Install A Scanner Agent

For Linux hosts that should run the SnapFS scanner agent as a service:

```bash
git clone https://github.com/snapfsio/snapfs
cd snapfs
pip install .[xxhash]
./systemd/install.sh
```

The installer expects the `snapfs` CLI to already be installed and available in
`PATH`. Run the installer as your normal user; it will prompt for elevated
privileges when it reaches the root-only systemd setup steps.

For production service installs, prefer installing `snapfs` into a stable
system-level Python environment rather than a user-local virtualenv.

If agent throughput matters on that host, prefer installing with `xxhash`
support and set `SNAPFS_HASH_ALGO=xxh64` during service configuration or when
re-running the installer.

Current systemd installer support is Linux-only. Windows service support is
planned but not available yet.

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

## Legacy Standalone Installs

Older installs may still use the legacy standalone service
`snapfs-agent.service` with `/etc/snapfs/agent.env` instead of the newer
instance template.

Legacy standalone paths:

- unit file: `/etc/systemd/system/snapfs-agent.service`
- enabled symlink: `/etc/systemd/system/multi-user.target.wants/snapfs-agent.service`
- config file: `/etc/snapfs/agent.env`

To disable that legacy service without uninstalling it:

```bash
sudo systemctl disable --now snapfs-agent.service
```

To remove the legacy standalone install entirely:

```bash
sudo systemctl disable --now snapfs-agent.service
sudo rm -f /etc/systemd/system/snapfs-agent.service
sudo rm -f /etc/snapfs/agent.env
sudo systemctl daemon-reload
```
