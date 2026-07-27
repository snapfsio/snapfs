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
TTY_PATH=""
if [[ -t 0 && -r /dev/tty && -w /dev/tty ]]; then
  TTY_PATH="/dev/tty"
fi

is_interactive() {
  [[ -n "${TTY_PATH}" ]]
}

confirm_yes() {
  local prompt="$1"
  local default="${2:-N}"
  local reply=""

  if is_interactive; then
    if [[ "$default" == "Y" ]]; then
      IFS= read -r -p "$prompt [Y/n]: " reply < "${TTY_PATH}"
      reply="${reply:-Y}"
    else
      IFS= read -r -p "$prompt [y/N]: " reply < "${TTY_PATH}"
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

list_installed_scanners() {
  local env_file
  local scanner_name

  if [[ ! -d "$SNAPFS_CONFIG_DIR" ]]; then
    return 0
  fi

  for env_file in "$SNAPFS_CONFIG_DIR"/agent-*.env; do
    if [[ ! -e "$env_file" ]]; then
      continue
    fi
    scanner_name="${env_file##*/agent-}"
    scanner_name="${scanner_name%.env}"
    if [[ -n "$scanner_name" ]]; then
      printf '%s\n' "$scanner_name"
    fi
  done | sort
}

select_scanner_name() {
  local default_name="$1"
  local scanners=()
  local scanner=""
  local reply=""
  local index=1

  if ! is_interactive; then
    printf '%s' "$default_name"
    return 0
  fi

  while IFS= read -r scanner; do
    scanners+=("$scanner")
  done < <(list_installed_scanners)

  if [[ "${#scanners[@]}" -gt 0 ]]; then
    echo "Installed scanner instances:" > "${TTY_PATH}"
    for scanner in "${scanners[@]}"; do
      printf '  %d. %s\n' "$index" "$scanner" > "${TTY_PATH}"
      index=$((index + 1))
    done
    echo > "${TTY_PATH}"
    echo "Choose a number or type a scanner name." > "${TTY_PATH}"
  else
    echo "No installed scanner instances were discovered in ${SNAPFS_CONFIG_DIR}." > "${TTY_PATH}"
    echo "Type a scanner name to uninstall anyway." > "${TTY_PATH}"
  fi

  IFS= read -r -p "Scanner name [${default_name}]: " reply < "${TTY_PATH}"
  reply="${reply:-$default_name}"

  if [[ "$reply" =~ ^[0-9]+$ ]] && [[ "$reply" -ge 1 ]] && [[ "$reply" -le "${#scanners[@]}" ]]; then
    printf '%s' "${scanners[$((reply - 1))]}"
    return 0
  fi

  printf '%s' "$reply"
}

if [[ "$AS_ROOT" == "0" ]]; then
  SCANNER_NAME="${SNAPFS_SCANNER_NAME:-$(select_scanner_name "$DEFAULT_SCANNER_NAME")}"
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
