#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_UNIT="snapfs-agent.service"
UNIT_PATH="${SYSTEMD_DIR}/${SERVICE_UNIT}"

SNAPFS_CONFIG_DIR="${SNAPFS_CONFIG_DIR:-/etc/snapfs}"
SNAPFS_ENV_FILE="${SNAPFS_ENV_FILE:-${SNAPFS_CONFIG_DIR}/agent.env}"
SNAPFS_STATE_DIR="${SNAPFS_STATE_DIR:-/var/lib/snapfs}"

confirm_yes() {
  local prompt="$1"
  local default="${2:-N}"
  local reply=""

  if [[ -r /dev/tty && -w /dev/tty ]]; then
    if [[ "$default" == "Y" ]]; then
      IFS= read -r -p "$prompt [Y/n]: " reply < /dev/tty
      reply="${reply:-Y}"
    else
      IFS= read -r -p "$prompt [y/N]: " reply < /dev/tty
      reply="${reply:-N}"
    fi
  else
    reply="$default"
  fi

  [[ "$reply" =~ ^[Yy]$ ]]
}

if [[ "$AS_ROOT" == "0" ]]; then
  echo "==> SnapFS agent uninstaller"
  echo "    Unit file : ${UNIT_PATH}"
  echo "    Config    : ${SNAPFS_ENV_FILE}"
  echo "    State dir : ${SNAPFS_STATE_DIR}"
  echo
  echo "This will remove the systemd unit and config file."
  echo "The state directory will be left in place unless you choose otherwise."
  echo

  confirm_yes "Proceed with uninstall using sudo?" "Y" || exit 0

  REMOVE_STATE="${REMOVE_STATE:-0}"
  if confirm_yes "Also remove state directory ${SNAPFS_STATE_DIR}?" "N"; then
    REMOVE_STATE=1
  fi

  exec sudo \
    SYSTEMD_DIR="${SYSTEMD_DIR}" \
    SNAPFS_CONFIG_DIR="${SNAPFS_CONFIG_DIR}" \
    SNAPFS_ENV_FILE="${SNAPFS_ENV_FILE}" \
    SNAPFS_STATE_DIR="${SNAPFS_STATE_DIR}" \
    REMOVE_STATE="${REMOVE_STATE}" \
    bash "$0" --as-root
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Must be run as root" >&2
  exit 1
fi

echo "==> Disabling ${SERVICE_UNIT}"
systemctl disable --now "${SERVICE_UNIT}" || true

echo "==> Removing unit file"
rm -f "${UNIT_PATH}"

echo "==> Reloading systemd"
systemctl daemon-reload

if [[ -f "${SNAPFS_ENV_FILE}" ]]; then
  echo "==> Removing config file ${SNAPFS_ENV_FILE}"
  rm -f "${SNAPFS_ENV_FILE}"
fi

if [[ -d "${SNAPFS_CONFIG_DIR}" ]]; then
  rmdir --ignore-fail-on-non-empty "${SNAPFS_CONFIG_DIR}" 2>/dev/null || true
fi

if [[ "${REMOVE_STATE:-0}" == "1" && -d "${SNAPFS_STATE_DIR}" ]]; then
  echo "==> Removing state directory ${SNAPFS_STATE_DIR}"
  rm -rf "${SNAPFS_STATE_DIR}"
else
  echo "==> Leaving state directory in place: ${SNAPFS_STATE_DIR}"
  echo "    Remove it manually if you no longer need it."
fi

echo "[OK] Uninstalled ${SERVICE_UNIT}"