#!/usr/bin/env bash
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Must be run as root (try: sudo systemd/install.sh)" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"

SERVICE_UNIT="snapfs-agent.service"
SRC="${SCRIPT_DIR}/${SERVICE_UNIT}"
DST="${SYSTEMD_DIR}/${SERVICE_UNIT}"
BIN="$(command -v snapfs || true)"

SNAPFS_USER="snapfs"
SNAPFS_GROUP="snapfs"

echo "==> Ensuring snapfs system user/group exists"
if ! getent group "${SNAPFS_GROUP}" >/dev/null; then
  echo " -> Creating group '${SNAPFS_GROUP}'"
  groupadd --system "${SNAPFS_GROUP}"
fi

if ! id "${SNAPFS_USER}" >/dev/null 2>&1; then
  echo " -> Creating user '${SNAPFS_USER}'"
  useradd --system \
    --gid "${SNAPFS_GROUP}" \
    --home /var/lib/snapfs \
    --create-home \
    --shell /usr/sbin/nologin \
    "${SNAPFS_USER}"
fi

if [[ -z "${BIN}" ]]; then
  echo "[ERR] snapfs not found in PATH" >&2
  exit 1
fi

echo "==> Installing ${SERVICE_UNIT} to ${SYSTEMD_DIR}"
if [[ ! -f "${SRC}" ]]; then
  echo "[ERR] Missing unit file: ${SRC}" >&2
  exit 1
fi

install -m 0644 "${SRC}" "${DST}"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling and starting ${SERVICE_UNIT}"
systemctl enable --now "${SERVICE_UNIT}"

echo ""
echo "[OK] Installed and started ${SERVICE_UNIT}"
echo ""
systemctl --no-pager status "${SERVICE_UNIT}" || true
