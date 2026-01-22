#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Must be run as root" >&2
  exit 1
fi

SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_UNIT="snapfs-agent.service"
UNIT_PATH="${SYSTEMD_DIR}/${SERVICE_UNIT}"

echo "==> Disabling ${SERVICE_UNIT}"
systemctl disable --now "${SERVICE_UNIT}" || true

echo "==> Removing unit file"
rm -f "${UNIT_PATH}"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "[OK] Uninstalled ${SERVICE_UNIT}"
