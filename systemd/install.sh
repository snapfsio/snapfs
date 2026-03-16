#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_UNIT="snapfs-agent.service"
SRC="${SCRIPT_DIR}/${SERVICE_UNIT}"
DST="${SYSTEMD_DIR}/${SERVICE_UNIT}"

SNAPFS_USER="${SNAPFS_USER:-snapfs}"
SNAPFS_GROUP="${SNAPFS_GROUP:-snapfs}"
STATE_DIR="${SNAPFS_STATE_DIR:-/var/lib/snapfs}"
CONFIG_DIR="${SNAPFS_CONFIG_DIR:-/etc/snapfs}"
ENV_FILE="${SNAPFS_ENV_FILE:-${CONFIG_DIR}/agent.env}"

DEFAULT_GATEWAY="${SNAPFS_GATEWAY:-}"
DEFAULT_AGENT_ID="${SNAPFS_AGENT_ID:-scanner-01}"
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

if [[ ! -f "${SRC}" ]]; then
  echo "[ERR] Missing unit file: ${SRC}" >&2
  exit 1
fi

if [[ "$AS_ROOT" == "0" ]]; then
  if [[ -f "${ENV_FILE}" ]]; then
    echo "==> Loading existing configuration from ${ENV_FILE}"
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    DEFAULT_GATEWAY="${SNAPFS_GATEWAY:-$DEFAULT_GATEWAY}"
    DEFAULT_AGENT_ID="${SNAPFS_AGENT_ID:-$DEFAULT_AGENT_ID}"
    DEFAULT_SCAN_ROOT="${SNAPFS_SCAN_ROOT:-$DEFAULT_SCAN_ROOT}"
    DEFAULT_API_KEY="${SNAPFS_API_KEY:-$DEFAULT_API_KEY}"
    DEFAULT_SCOPES="${SNAPFS_SCANNER_TOKEN_SCOPES:-$DEFAULT_SCOPES}"
    DEFAULT_ALLOW_INSECURE="${SNAPFS_ALLOW_INSECURE_GATEWAY:-$DEFAULT_ALLOW_INSECURE}"
  fi

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

  SNAPFS_BIN_VALUE="$(trim "$(prompt_value 'SnapFS executable path' "${DETECTED_SNAPFS_BIN}")")"
  validate_snapfs_bin "${SNAPFS_BIN_VALUE}"
  warn_if_user_managed_path "${SNAPFS_BIN_VALUE}"

  gateway_input="$(prompt_value 'Gateway host or URL' "$DEFAULT_GATEWAY")"
  SNAPFS_GATEWAY_VALUE="$(normalize_gateway "$gateway_input")"
  if [[ -z "$SNAPFS_GATEWAY_VALUE" ]]; then
    echo "[ERR] Gateway host or URL is required" >&2
    exit 1
  fi

  SNAPFS_AGENT_ID_VALUE="$(trim "$(prompt_value 'Agent ID' "$DEFAULT_AGENT_ID")")"
  if [[ -z "$SNAPFS_AGENT_ID_VALUE" ]]; then
    echo "[ERR] Agent ID is required" >&2
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
  echo "  snapfs bin : ${SNAPFS_BIN_VALUE}"
  echo "  gateway    : ${SNAPFS_GATEWAY_VALUE}"
  echo "  agent id   : ${SNAPFS_AGENT_ID_VALUE}"
  echo "  scan root  : ${SNAPFS_SCAN_ROOT_VALUE}"
  echo "  env file   : ${ENV_FILE}"
  echo "  unit file  : ${DST}"
  echo

  confirm_yes "Proceed with systemd installation using sudo?" "Y" || exit 0

  exec sudo \
    SNAPFS_BIN="${SNAPFS_BIN_VALUE}" \
    SNAPFS_GATEWAY="${SNAPFS_GATEWAY_VALUE}" \
    SNAPFS_AGENT_ID="${SNAPFS_AGENT_ID_VALUE}" \
    SNAPFS_SCAN_ROOT="${SNAPFS_SCAN_ROOT_VALUE}" \
    SNAPFS_API_KEY="${SNAPFS_API_KEY_VALUE}" \
    SNAPFS_SCANNER_TOKEN_SCOPES="${SNAPFS_SCANNER_TOKEN_SCOPES_VALUE}" \
    SNAPFS_ALLOW_INSECURE_GATEWAY="${SNAPFS_ALLOW_INSECURE_GATEWAY_VALUE}" \
    SNAPFS_USER="${SNAPFS_USER}" \
    SNAPFS_GROUP="${SNAPFS_GROUP}" \
    SNAPFS_STATE_DIR="${STATE_DIR}" \
    SNAPFS_CONFIG_DIR="${CONFIG_DIR}" \
    SNAPFS_ENV_FILE="${ENV_FILE}" \
    SYSTEMD_DIR="${SYSTEMD_DIR}" \
    bash "$0" --as-root
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Root privileges are required for the install phase" >&2
  exit 1
fi

validate_snapfs_bin "${SNAPFS_BIN}"

echo "==> Ensuring snapfs system user/group exists"
if ! getent group "${SNAPFS_GROUP}" >/dev/null; then
  echo " -> Creating group '${SNAPFS_GROUP}'"
  groupadd --system "${SNAPFS_GROUP}"
fi

if ! id "${SNAPFS_USER}" >/dev/null 2>&1; then
  echo " -> Creating user '${SNAPFS_USER}'"
  useradd --system \
    --gid "${SNAPFS_GROUP}" \
    --home "${STATE_DIR}" \
    --create-home \
    --shell /usr/sbin/nologin \
    "${SNAPFS_USER}"
fi

echo "==> Creating config and state directories"
install -d -m 0755 "${CONFIG_DIR}"
install -d -m 0755 -o "${SNAPFS_USER}" -g "${SNAPFS_GROUP}" "${STATE_DIR}"

echo "==> Installing ${SERVICE_UNIT} to ${SYSTEMD_DIR}"
install -m 0644 "${SRC}" "${DST}"

echo "==> Updating ExecStart in ${DST}"
escaped_snapfs_bin="$(printf '%s\n' "${SNAPFS_BIN}" | sed 's/[\/&]/\\&/g')"
sed -i "s/__SNAPFS_EXEC__/${escaped_snapfs_bin}/g" "${DST}"

echo "==> Writing configuration to ${ENV_FILE}"
cat > "${ENV_FILE}" <<EOF
# SnapFS agent configuration
# Edit this file later if the gateway, API key, or scan root changes,
# then run: sudo systemctl restart ${SERVICE_UNIT%.service}
SNAPFS_GATEWAY=${SNAPFS_GATEWAY}
SNAPFS_AGENT_ID=${SNAPFS_AGENT_ID}
SNAPFS_SCAN_ROOT=${SNAPFS_SCAN_ROOT}
SNAPFS_API_KEY=${SNAPFS_API_KEY}
EOF

if [[ -n "${SNAPFS_SCANNER_TOKEN_SCOPES:-}" ]]; then
  printf 'SNAPFS_SCANNER_TOKEN_SCOPES=%s\n' "${SNAPFS_SCANNER_TOKEN_SCOPES}" >> "${ENV_FILE}"
fi
printf 'SNAPFS_ALLOW_INSECURE_GATEWAY=%s\n' "${SNAPFS_ALLOW_INSECURE_GATEWAY:-0}" >> "${ENV_FILE}"

chown root:"${SNAPFS_GROUP}" "${ENV_FILE}"
chmod 0640 "${ENV_FILE}"

echo "==> Reloading systemd"
systemctl daemon-reload

echo "==> Enabling and restarting ${SERVICE_UNIT}"
systemctl enable --now "${SERVICE_UNIT}"
systemctl restart "${SERVICE_UNIT}"

echo
echo "[OK] Installed and started ${SERVICE_UNIT}"
echo "    Service unit : ${DST}"
echo "    Config file  : ${ENV_FILE}"
echo "    SnapFS bin   : ${SNAPFS_BIN}"
echo
echo "To update the gateway, API key, or scan root later:"
echo "  1. Edit ${ENV_FILE}"
echo "  2. Run: sudo systemctl restart ${SERVICE_UNIT%.service}"
echo
systemctl --no-pager status "${SERVICE_UNIT}" || true