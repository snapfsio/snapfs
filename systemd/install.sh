#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_TEMPLATE_UNIT="snapfs-agent@.service"
TEMPLATE_SRC="${SCRIPT_DIR}/${SERVICE_TEMPLATE_UNIT}"
TEMPLATE_DST="${SYSTEMD_DIR}/${SERVICE_TEMPLATE_UNIT}"

SNAPFS_USER="${SNAPFS_USER:-snapfs}"
SNAPFS_GROUP="${SNAPFS_GROUP:-snapfs}"
BASE_STATE_DIR="${SNAPFS_STATE_DIR:-/var/lib/snapfs}"
CONFIG_DIR="${SNAPFS_CONFIG_DIR:-/etc/snapfs}"
DEFAULT_SCANNER_NAME="${SNAPFS_SCANNER_NAME:-${SNAPFS_AGENT_ID:-scanner-01}}"
DEFAULT_GATEWAY="${SNAPFS_GATEWAY:-}"
DEFAULT_SCAN_ROOT="${SNAPFS_SCAN_ROOT:-/data}"
DEFAULT_API_KEY="${SNAPFS_API_KEY:-}"
DEFAULT_SCOPES="${SNAPFS_SCANNER_TOKEN_SCOPES:-ingest:write}"
DEFAULT_ALLOW_INSECURE="${SNAPFS_ALLOW_INSECURE_GATEWAY:-0}"

TTY_PATH=""
if [[ -r /dev/tty && -w /dev/tty ]]; then
  TTY_PATH="/dev/tty"
fi

is_interactive() {
  [[ -n "${TTY_PATH}" ]]
}

trim() {
  local value="$1"
  value="${value#${value%%[![:space:]]*}}"
  value="${value%${value##*[![:space:]]}}"
  printf '%s' "$value"
}

normalize_gateway() {
  local raw
  raw="$(trim "$1")"
  if [[ -z "$raw" ]]; then
    printf '%s' ""
    return 0
  fi

  if [[ "$raw" =~ ^https?:// ]]; then
    printf '%s' "$raw"
    return 0
  fi

  printf 'https://%s' "$raw"
}

prompt_value() {
  local prompt="$1"
  local default="$2"
  local secret="${3:-0}"
  local reply=""
  local prompt_text=""

  if ! is_interactive; then
    printf '%s' "$default"
    return 0
  fi

  if [[ "$secret" == "1" ]]; then
    if [[ -n "$default" ]]; then
      prompt_text="$prompt [configured]: "
    else
      prompt_text="$prompt: "
    fi
    IFS= read -r -s -p "$prompt_text" reply < "${TTY_PATH}"
    printf '\n' > "${TTY_PATH}"
  else
    if [[ -n "$default" ]]; then
      prompt_text="$prompt [$default]: "
    else
      prompt_text="$prompt: "
    fi
    IFS= read -r -p "$prompt_text" reply < "${TTY_PATH}"
  fi

  if [[ -z "$reply" ]]; then
    reply="$default"
  fi

  printf '%s' "$reply"
}

confirm_yes() {
  local prompt="$1"
  local default="${2:-Y}"
  local reply=""

  if ! is_interactive; then
    return 0
  fi

  if [[ "$default" == "Y" ]]; then
    IFS= read -r -p "$prompt [Y/n]: " reply < "${TTY_PATH}"
    reply="${reply:-Y}"
  else
    IFS= read -r -p "$prompt [y/N]: " reply < "${TTY_PATH}"
    reply="${reply:-N}"
  fi

  [[ "$reply" =~ ^[Yy]$ ]]
}

validate_snapfs_bin() {
  local bin="$1"

  if [[ -z "$bin" ]]; then
    echo "[ERR] snapfs executable path is required" >&2
    exit 1
  fi

  if [[ ! -e "$bin" ]]; then
    echo "[ERR] snapfs executable does not exist: $bin" >&2
    exit 1
  fi

  if [[ ! -x "$bin" ]]; then
    echo "[ERR] snapfs executable is not executable: $bin" >&2
    exit 1
  fi

  if ! "$bin" --version >/dev/null 2>&1; then
    echo "[ERR] Failed to run: $bin --version" >&2
    exit 1
  fi
}

warn_if_user_managed_path() {
  local bin="$1"

  case "$bin" in
    /home/*|*/.venv/*|*/miniconda/*|*/anaconda/*|*/.local/bin/*)
      echo "[WARN] The selected snapfs executable appears to live in a user-managed environment:"
      echo "       $bin"
      echo "       This may be fragile for a long-running systemd service."
      confirm_yes "Continue anyway?" "N" || exit 1
      ;;
  esac
}

discover_snapfs() {
  command -v snapfs || true
}

validate_scanner_name() {
  local name="$1"

  if [[ -z "$name" ]]; then
    echo "[ERR] Scanner name is required" >&2
    exit 1
  fi

  if [[ ! "$name" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    echo "[ERR] Scanner name must start with an alphanumeric character and contain only letters, digits, dot, underscore, or dash" >&2
    exit 1
  fi
}

load_existing_defaults() {
  local env_file="$1"
  if [[ -f "$env_file" ]]; then
    echo "==> Loading existing configuration from ${env_file}"
    # shellcheck disable=SC1090
    source "$env_file"
    DEFAULT_GATEWAY="${SNAPFS_GATEWAY:-$DEFAULT_GATEWAY}"
    DEFAULT_SCAN_ROOT="${SNAPFS_SCAN_ROOT:-$DEFAULT_SCAN_ROOT}"
    DEFAULT_API_KEY="${SNAPFS_API_KEY:-$DEFAULT_API_KEY}"
    DEFAULT_SCOPES="${SNAPFS_SCANNER_TOKEN_SCOPES:-$DEFAULT_SCOPES}"
    DEFAULT_ALLOW_INSECURE="${SNAPFS_ALLOW_INSECURE_GATEWAY:-$DEFAULT_ALLOW_INSECURE}"
    if [[ -n "${SNAPFS_AGENT_ID:-}" ]]; then
      DEFAULT_SCANNER_NAME="${SNAPFS_AGENT_ID}"
    fi
  fi
}

instance_env_file() {
  local scanner_name="$1"
  printf '%s/agent-%s.env' "$CONFIG_DIR" "$scanner_name"
}

instance_state_dir() {
  local scanner_name="$1"
  printf '%s/%s' "$BASE_STATE_DIR" "$scanner_name"
}

instance_service_unit() {
  local scanner_name="$1"
  printf 'snapfs-agent@%s.service' "$scanner_name"
}

if [[ ! -f "${TEMPLATE_SRC}" ]]; then
  echo "[ERR] Missing unit file: ${TEMPLATE_SRC}" >&2
  exit 1
fi

if [[ "$AS_ROOT" == "0" ]]; then
  echo "==> SnapFS agent installer"

  DETECTED_SNAPFS_BIN="$(discover_snapfs)"
  if [[ -n "${DETECTED_SNAPFS_BIN}" ]]; then
    echo "Detected snapfs executable:"
    echo "  ${DETECTED_SNAPFS_BIN}"
  else
    echo "[WARN] 'snapfs' was not found in your current PATH."
    echo "       Install it first, for example with:"
    echo "       pipx install snapfs"
    echo "       or"
    echo "       pip install snapfs"
  fi

  SCANNER_NAME_VALUE="$(trim "$(prompt_value 'Scanner name' "$DEFAULT_SCANNER_NAME")")"
  validate_scanner_name "$SCANNER_NAME_VALUE"

  ENV_FILE="$(instance_env_file "$SCANNER_NAME_VALUE")"
  STATE_DIR="$(instance_state_dir "$SCANNER_NAME_VALUE")"
  SERVICE_UNIT="$(instance_service_unit "$SCANNER_NAME_VALUE")"
  load_existing_defaults "$ENV_FILE"

  SNAPFS_BIN_VALUE="$(trim "$(prompt_value 'SnapFS executable path' "${SNAPFS_BIN:-$DETECTED_SNAPFS_BIN}")")"
  validate_snapfs_bin "${SNAPFS_BIN_VALUE}"
  warn_if_user_managed_path "${SNAPFS_BIN_VALUE}"

  gateway_input="$(prompt_value 'Gateway host or URL' "$DEFAULT_GATEWAY")"
  SNAPFS_GATEWAY_VALUE="$(normalize_gateway "$gateway_input")"
  if [[ -z "$SNAPFS_GATEWAY_VALUE" ]]; then
    echo "[ERR] Gateway host or URL is required" >&2
    exit 1
  fi

  SNAPFS_SCAN_ROOT_VALUE="$(trim "$(prompt_value 'Scan root path' "$DEFAULT_SCAN_ROOT")")"
  if [[ -z "$SNAPFS_SCAN_ROOT_VALUE" ]]; then
    echo "[ERR] Scan root path is required" >&2
    exit 1
  fi

  SNAPFS_API_KEY_VALUE="$(trim "$(prompt_value 'API key' "$DEFAULT_API_KEY" 1)")"
  if [[ -z "$SNAPFS_API_KEY_VALUE" ]]; then
    echo "[ERR] API key is required" >&2
    exit 1
  fi

  SNAPFS_SCANNER_TOKEN_SCOPES_VALUE="$(trim "$(prompt_value 'Scanner token scopes' "$DEFAULT_SCOPES")")"
  SNAPFS_ALLOW_INSECURE_GATEWAY_VALUE="$(trim "$(prompt_value 'Allow insecure HTTP for remote gateways? (0/1)' "$DEFAULT_ALLOW_INSECURE")")"

  if [[ "$SNAPFS_GATEWAY_VALUE" =~ ^http:// ]]; then
    gateway_host="${SNAPFS_GATEWAY_VALUE#http://}"
    gateway_host="${gateway_host%%/*}"
    case "$gateway_host" in
      localhost|127.0.0.1|[::1]|::1|localhost:*) ;;
      *)
        if [[ "$SNAPFS_ALLOW_INSECURE_GATEWAY_VALUE" != "1" ]]; then
          echo "[ERR] Remote gateways should use HTTPS. Re-run with an https:// URL or explicitly allow insecure mode." >&2
          exit 1
        fi
        ;;
    esac
  fi

  echo
  echo "Summary:"
  echo "  scanner    : ${SCANNER_NAME_VALUE}"
  echo "  snapfs bin : ${SNAPFS_BIN_VALUE}"
  echo "  gateway    : ${SNAPFS_GATEWAY_VALUE}"
  echo "  agent id   : ${SCANNER_NAME_VALUE}"
  echo "  scan root  : ${SNAPFS_SCAN_ROOT_VALUE}"
  echo "  env file   : ${ENV_FILE}"
  echo "  state dir  : ${STATE_DIR}"
  echo "  service    : ${SERVICE_UNIT}"
  echo

  confirm_yes "Proceed with systemd installation using sudo?" "Y" || exit 0

  exec sudo \
    SNAPFS_BIN="${SNAPFS_BIN_VALUE}" \
    SNAPFS_GATEWAY="${SNAPFS_GATEWAY_VALUE}" \
    SNAPFS_AGENT_ID="${SCANNER_NAME_VALUE}" \
    SNAPFS_SCAN_ROOT="${SNAPFS_SCAN_ROOT_VALUE}" \
    SNAPFS_API_KEY="${SNAPFS_API_KEY_VALUE}" \
    SNAPFS_SCANNER_TOKEN_SCOPES="${SNAPFS_SCANNER_TOKEN_SCOPES_VALUE}" \
    SNAPFS_ALLOW_INSECURE_GATEWAY="${SNAPFS_ALLOW_INSECURE_GATEWAY_VALUE}" \
    SNAPFS_SCANNER_NAME="${SCANNER_NAME_VALUE}" \
    SNAPFS_USER="${SNAPFS_USER}" \
    SNAPFS_GROUP="${SNAPFS_GROUP}" \
    SNAPFS_STATE_DIR="${BASE_STATE_DIR}" \
    SNAPFS_CONFIG_DIR="${CONFIG_DIR}" \
    SYSTEMD_DIR="${SYSTEMD_DIR}" \
    bash "$0" --as-root
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Root privileges are required for the install phase" >&2
  exit 1
fi

validate_snapfs_bin "${SNAPFS_BIN}"
validate_scanner_name "${SNAPFS_SCANNER_NAME}"

SERVICE_UNIT="$(instance_service_unit "$SNAPFS_SCANNER_NAME")"
ENV_FILE="$(instance_env_file "$SNAPFS_SCANNER_NAME")"
STATE_DIR="$(instance_state_dir "$SNAPFS_SCANNER_NAME")"

config_tmp="$(mktemp)"
cat > "$config_tmp" <<CFG
# SnapFS agent configuration
# Edit this file later if the gateway, API key, or scan root changes,
# then run: sudo systemctl restart ${SERVICE_UNIT}
SNAPFS_BIN=${SNAPFS_BIN}
SNAPFS_GATEWAY=${SNAPFS_GATEWAY}
SNAPFS_AGENT_ID=${SNAPFS_AGENT_ID}
SNAPFS_SCAN_ROOT=${SNAPFS_SCAN_ROOT}
SNAPFS_API_KEY=${SNAPFS_API_KEY}
CFG

if [[ -n "${SNAPFS_SCANNER_TOKEN_SCOPES:-}" ]]; then
  printf 'SNAPFS_SCANNER_TOKEN_SCOPES=%s\n' "${SNAPFS_SCANNER_TOKEN_SCOPES}" >> "$config_tmp"
fi
printf 'SNAPFS_ALLOW_INSECURE_GATEWAY=%s\n' "${SNAPFS_ALLOW_INSECURE_GATEWAY:-0}" >> "$config_tmp"

unit_changed=0
config_changed=0

if [[ ! -f "$TEMPLATE_DST" ]] || ! cmp -s "$TEMPLATE_SRC" "$TEMPLATE_DST"; then
  echo "==> Installing ${SERVICE_TEMPLATE_UNIT} to ${SYSTEMD_DIR}"
  install -m 0644 "$TEMPLATE_SRC" "$TEMPLATE_DST"
  unit_changed=1
else
  echo "==> ${SERVICE_TEMPLATE_UNIT} already up to date"
fi

echo "==> Ensuring snapfs system user/group exists"
if ! getent group "${SNAPFS_GROUP}" >/dev/null; then
  echo " -> Creating group '${SNAPFS_GROUP}'"
  groupadd --system "${SNAPFS_GROUP}"
fi

if ! id "${SNAPFS_USER}" >/dev/null 2>&1; then
  echo " -> Creating user '${SNAPFS_USER}'"
  useradd --system \
    --gid "${SNAPFS_GROUP}" \
    --home "${BASE_STATE_DIR}" \
    --create-home \
    --shell /usr/sbin/nologin \
    "${SNAPFS_USER}"
fi

echo "==> Creating config and state directories"
install -d -m 0755 "${CONFIG_DIR}"
install -d -m 0755 -o "${SNAPFS_USER}" -g "${SNAPFS_GROUP}" "${BASE_STATE_DIR}"
install -d -m 0755 -o "${SNAPFS_USER}" -g "${SNAPFS_GROUP}" "${STATE_DIR}"

if [[ ! -f "$ENV_FILE" ]] || ! cmp -s "$config_tmp" "$ENV_FILE"; then
  echo "==> Writing configuration to ${ENV_FILE}"
  install -m 0640 -o root -g "${SNAPFS_GROUP}" "$config_tmp" "$ENV_FILE"
  config_changed=1
else
  echo "==> Configuration already matches ${ENV_FILE}"
fi
rm -f "$config_tmp"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling ${SERVICE_UNIT}"
systemctl enable "$SERVICE_UNIT"

if [[ "$unit_changed" == "1" || "$config_changed" == "1" ]]; then
  echo "==> Restarting ${SERVICE_UNIT}"
  systemctl restart "$SERVICE_UNIT"
else
  echo "==> Starting ${SERVICE_UNIT} if needed"
  systemctl start "$SERVICE_UNIT"
fi

echo
if [[ "$unit_changed" == "0" && "$config_changed" == "0" ]]; then
  echo "[OK] ${SERVICE_UNIT} already matched the requested configuration"
else
  echo "[OK] Installed and started ${SERVICE_UNIT}"
fi
echo "    Template unit: ${TEMPLATE_DST}"
echo "    Config file  : ${ENV_FILE}"
echo "    State dir    : ${STATE_DIR}"
echo "    SnapFS bin   : ${SNAPFS_BIN}"
echo
echo "To update this scanner later:"
echo "  1. Edit ${ENV_FILE}"
echo "  2. Run: sudo systemctl restart ${SERVICE_UNIT}"
echo
systemctl --no-pager status "${SERVICE_UNIT}" || true
