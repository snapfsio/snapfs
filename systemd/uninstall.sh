#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_TEMPLATE_UNIT="snapfs-agent@.service"
TEMPLATE_PATH="${SYSTEMD_DIR}/${SERVICE_TEMPLATE_UNIT}"
SNAPFS_CONFIG_DIR="${SNAPFS_CONFIG_DIR:-/etc/snapfs}"
BASE_STATE_DIR="${SNAPFS_STATE_DIR:-/var/lib/snapfs}"
DEFAULT_SCANNER_NAME="${SNAPFS_SCANNER_NAME:-${SNAPFS_AGENT_ID:-scanner-01}}"

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

validate_scanner_name() {
  local name="$1"
  if [[ -z "$name" || ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "[ERR] Scanner name must start with an alphanumeric character and contain only letters, digits, dot, underscore, or dash" >&2
    exit 1
  fi
}

instance_env_file() {
  local scanner_name="$1"
  printf '%s/agent-%s.env' "$SNAPFS_CONFIG_DIR" "$scanner_name"
}

instance_state_dir() {
  local scanner_name="$1"
  printf '%s/%s' "$BASE_STATE_DIR" "$scanner_name"
}

instance_service_unit() {
  local scanner_name="$1"
  printf 'snapfs-agent@%s.service' "$scanner_name"
}

if [[ "$AS_ROOT" == "0" ]]; then
  SCANNER_NAME="${SNAPFS_SCANNER_NAME:-$DEFAULT_SCANNER_NAME}"
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    IFS= read -r -p "Scanner name [${SCANNER_NAME}]: " reply < /dev/tty
    if [[ -n "${reply}" ]]; then
      SCANNER_NAME="${reply}"
    fi
  fi
  validate_scanner_name "$SCANNER_NAME"

  SNAPFS_ENV_FILE="$(instance_env_file "$SCANNER_NAME")"
  INSTANCE_STATE_DIR="$(instance_state_dir "$SCANNER_NAME")"
  SERVICE_UNIT="$(instance_service_unit "$SCANNER_NAME")"

  echo "==> SnapFS agent uninstaller"
  echo "    Scanner    : ${SCANNER_NAME}"
  echo "    Service    : ${SERVICE_UNIT}"
  echo "    Config     : ${SNAPFS_ENV_FILE}"
  echo "    State dir  : ${INSTANCE_STATE_DIR}"
  echo
  echo "This will remove the systemd service instance and its config file."
  echo "The shared template unit will be left in place."
  echo "The state directory will be left in place unless you choose otherwise."
  echo

  confirm_yes "Proceed with uninstall using sudo?" "Y" || exit 0

  REMOVE_STATE="${REMOVE_STATE:-0}"
  if confirm_yes "Also remove state directory ${INSTANCE_STATE_DIR}?" "N"; then
    REMOVE_STATE=1
  fi

  exec sudo \
    SYSTEMD_DIR="${SYSTEMD_DIR}" \
    SNAPFS_CONFIG_DIR="${SNAPFS_CONFIG_DIR}" \
    SNAPFS_STATE_DIR="${BASE_STATE_DIR}" \
    SNAPFS_SCANNER_NAME="${SCANNER_NAME}" \
    REMOVE_STATE="${REMOVE_STATE}" \
    bash "$0" --as-root
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Must be run as root" >&2
  exit 1
fi

validate_scanner_name "${SNAPFS_SCANNER_NAME}"
SNAPFS_ENV_FILE="$(instance_env_file "$SNAPFS_SCANNER_NAME")"
INSTANCE_STATE_DIR="$(instance_state_dir "$SNAPFS_SCANNER_NAME")"
SERVICE_UNIT="$(instance_service_unit "$SNAPFS_SCANNER_NAME")"

echo "==> Disabling ${SERVICE_UNIT}"
systemctl disable --now "${SERVICE_UNIT}" || true

echo "==> Reloading systemd"
systemctl daemon-reload

if [[ -f "${SNAPFS_ENV_FILE}" ]]; then
  echo "==> Removing config file ${SNAPFS_ENV_FILE}"
  rm -f "${SNAPFS_ENV_FILE}"
fi

if [[ "${REMOVE_STATE:-0}" == "1" && -d "${INSTANCE_STATE_DIR}" ]]; then
  echo "==> Removing state directory ${INSTANCE_STATE_DIR}"
  rm -rf "${INSTANCE_STATE_DIR}"
else
  echo "==> Leaving state directory in place: ${INSTANCE_STATE_DIR}"
  echo "    Remove it manually if you no longer need it."
fi

if [[ -d "${SNAPFS_CONFIG_DIR}" ]]; then
  rmdir --ignore-fail-on-non-empty "${SNAPFS_CONFIG_DIR}" 2>/dev/null || true
fi

echo "[OK] Uninstalled ${SERVICE_UNIT}"
echo "     Shared template remains at ${TEMPLATE_PATH}"
