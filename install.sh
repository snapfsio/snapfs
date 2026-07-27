#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_INSTALLER="${SCRIPT_DIR}/systemd/install.sh"
INSTALL_ROOT="${SNAPFS_INSTALL_ROOT:-/opt/snapfs}"
VENV_DIR="${SNAPFS_VENV_DIR:-${INSTALL_ROOT}/venv}"
INSTALL_EXTRAS="${SNAPFS_INSTALL_EXTRAS:-xxhash}"
PYTHON_BIN="${SNAPFS_PYTHON:-}"
VENV_BACKEND="${SNAPFS_VENV_BACKEND:-}"
VIRTUALENV_CMD="${SNAPFS_VIRTUALENV_CMD:-}"
SNAPFS_BIN="${VENV_DIR}/bin/snapfs"
PIP_BIN="${VENV_DIR}/bin/pip"
VENV_PYTHON_BIN="${VENV_DIR}/bin/python"
TTY_PATH=""

if [[ -t 0 && -r /dev/tty && -w /dev/tty ]]; then
  TTY_PATH="/dev/tty"
fi

is_interactive() {
  [[ -n "${TTY_PATH}" ]]
}

is_user_managed_path() {
  local path="$1"

  case "${path}" in
    /home/*|*/.venv/*|*/venv/*|*/miniconda/*|*/anaconda/*|*/.local/*)
      return 0
      ;;
  esac

  return 1
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

discover_python() {
  local candidate=""

  if [[ -n "${PYTHON_BIN}" ]]; then
    printf '%s' "${PYTHON_BIN}"
    return 0
  fi

  candidate="$(command -v python3 || true)"
  if [[ -z "${candidate}" ]]; then
    return 0
  fi

  if [[ -n "${VIRTUAL_ENV:-}" && -x /usr/bin/python3 ]]; then
    printf '%s' "/usr/bin/python3"
    return 0
  fi

  printf '%s' "${candidate}"
}

python_major_minor() {
  local bin="$1"

  "${bin}" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
}

has_stdlib_venv() {
  local bin="$1"

  "${bin}" - <<'PY' >/dev/null 2>&1
import ensurepip
import venv
PY
}

has_python_virtualenv_module() {
  local bin="$1"

  "${bin}" - <<'PY' >/dev/null 2>&1
import virtualenv
PY
}

discover_virtualenv_cmd() {
  command -v virtualenv || true
}

python_virtualenv_module_path() {
  local bin="$1"

  "${bin}" - <<'PY' 2>/dev/null || true
import virtualenv
print(virtualenv.__file__)
PY
}

can_use_python_virtualenv_module() {
  local bin="$1"
  local module_path=""

  if ! has_python_virtualenv_module "${bin}"; then
    return 1
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi

  module_path="$(python_virtualenv_module_path "${bin}")"
  if [[ -z "${module_path}" ]]; then
    return 1
  fi

  if is_user_managed_path "${module_path}"; then
    return 1
  fi

  return 0
}

can_use_virtualenv_cmd() {
  local cmd_path="$1"

  if [[ -z "${cmd_path}" || ! -x "${cmd_path}" ]]; then
    return 1
  fi

  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi

  if is_user_managed_path "${cmd_path}"; then
    return 1
  fi

  return 0
}

discover_venv_backend() {
  if [[ -n "${VENV_BACKEND}" ]]; then
    printf '%s' "${VENV_BACKEND}"
    return 0
  fi

  if has_stdlib_venv "${PYTHON_BIN}"; then
    printf '%s' "venv"
    return 0
  fi

  if can_use_python_virtualenv_module "${PYTHON_BIN}"; then
    printf '%s' "python-virtualenv"
    return 0
  fi

  if can_use_virtualenv_cmd "${VIRTUALENV_CMD}"; then
    printf '%s' "virtualenv-cmd"
    return 0
  fi

  VIRTUALENV_CMD="$(discover_virtualenv_cmd)"
  if can_use_virtualenv_cmd "${VIRTUALENV_CMD}"; then
    printf '%s' "virtualenv-cmd"
    return 0
  fi

  printf '%s' ""
}

warn_if_user_managed_python() {
  local bin="$1"

  if is_user_managed_path "${bin}"; then
    echo "[WARN] The selected python3 appears to live in a user-managed environment:"
    echo "       ${bin}"
    echo "       Managed service installs are more stable with a system Python."
    confirm_yes "Continue anyway?" "N" || exit 1
  fi
}

print_venv_backend_hint() {
  local bin="$1"
  local py_mm=""
  local os_id=""
  local os_like=""

  py_mm="$(python_major_minor "${bin}")"

  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    os_id="${ID:-}"
    os_like="${ID_LIKE:-}"
  fi

  case " ${os_id} ${os_like} " in
    *" ubuntu "*|*" debian "*)
      echo "      On Debian/Ubuntu, try:" >&2
      echo "      sudo apt install python${py_mm}-venv" >&2
      ;;
  esac
}

validate_python() {
  local bin="$1"
  local version=""

  if [[ -z "${bin}" ]]; then
    echo "[ERR] python3 is required but was not found in PATH." >&2
    exit 1
  fi

  if [[ ! -x "${bin}" ]]; then
    echo "[ERR] python3 is not executable: ${bin}" >&2
    exit 1
  fi

  if ! version="$("${bin}" - <<'PY'
import sys
if sys.version_info < (3, 8):
    raise SystemExit(1)
print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
PY
)"; then
    echo "[ERR] SnapFS requires python3 >= 3.8: ${bin}" >&2
    exit 1
  fi

  VENV_BACKEND="$(discover_venv_backend)"
  if [[ -z "${VENV_BACKEND}" ]]; then
    echo "[ERR] No usable virtual environment backend was found for: ${bin}" >&2
    echo "      Install one of the following and try again:" >&2
    echo "      - python3-venv (or the distro-specific python3.x-venv package)" >&2
    echo "      - a system-wide virtualenv install" >&2
    print_venv_backend_hint "${bin}"
    exit 1
  fi

  echo "Detected python3:"
  echo "  ${bin} (${version})"
  case "${VENV_BACKEND}" in
    venv)
      echo "Detected virtual environment backend:"
      echo "  python3 -m venv"
      ;;
    python-virtualenv)
      echo "Detected virtual environment backend:"
      echo "  python3 -m virtualenv"
      ;;
    virtualenv-cmd)
      echo "Detected virtual environment backend:"
      echo "  ${VIRTUALENV_CMD}"
      ;;
  esac
}

install_spec() {
  if [[ -n "${INSTALL_EXTRAS}" ]]; then
    printf '.[%s]' "${INSTALL_EXTRAS}"
  else
    printf '.'
  fi
}

existing_snapfs_version() {
  if [[ -x "${SNAPFS_BIN}" ]]; then
    "${SNAPFS_BIN}" --version 2>/dev/null || true
  fi
}

venv_has_pip() {
  if [[ ! -x "${VENV_PYTHON_BIN}" ]]; then
    return 1
  fi

  "${VENV_PYTHON_BIN}" -m pip --version >/dev/null 2>&1
}

create_virtualenv() {
  case "${VENV_BACKEND}" in
    venv)
      "${PYTHON_BIN}" -m venv "${VENV_DIR}"
      ;;
    python-virtualenv)
      "${PYTHON_BIN}" -m virtualenv "${VENV_DIR}"
      ;;
    virtualenv-cmd)
      "${VIRTUALENV_CMD}" -p "${PYTHON_BIN}" "${VENV_DIR}"
      ;;
    *)
      echo "[ERR] Unsupported virtual environment backend: ${VENV_BACKEND}" >&2
      exit 1
      ;;
  esac
}

bootstrap_runtime() {
  echo "==> Creating managed install root at ${INSTALL_ROOT}"
  install -d -m 0755 "${INSTALL_ROOT}"

  if [[ ! -x "${VENV_PYTHON_BIN}" ]]; then
    echo "==> Creating virtual environment at ${VENV_DIR}"
    create_virtualenv
  else
    echo "==> Reusing existing virtual environment at ${VENV_DIR}"
  fi

  if ! venv_has_pip; then
    echo "[WARN] Managed virtual environment is incomplete or missing pip:"
    echo "       ${VENV_DIR}"
    echo "       Recreating it now."
    rm -rf "${VENV_DIR}"
    echo "==> Creating virtual environment at ${VENV_DIR}"
    create_virtualenv
  fi

  echo "==> Upgrading packaging tools"
  PIP_DISABLE_PIP_VERSION_CHECK=1 "${VENV_PYTHON_BIN}" -m pip install --upgrade pip setuptools wheel

  echo "==> Installing SnapFS into managed virtual environment"
  (
    cd "${SCRIPT_DIR}"
    PIP_DISABLE_PIP_VERSION_CHECK=1 "${PIP_BIN}" install --upgrade "$(install_spec)"
  )

  if [[ ! -x "${SNAPFS_BIN}" ]]; then
    echo "[ERR] SnapFS install did not produce ${SNAPFS_BIN}" >&2
    exit 1
  fi

  echo "==> Installed SnapFS:"
  "${SNAPFS_BIN}" --version
}

if [[ ! -f "${SCRIPT_DIR}/pyproject.toml" ]]; then
  echo "[ERR] Missing pyproject.toml in ${SCRIPT_DIR}" >&2
  exit 1
fi

if [[ ! -x "${SYSTEMD_INSTALLER}" ]]; then
  echo "[ERR] Missing systemd installer: ${SYSTEMD_INSTALLER}" >&2
  exit 1
fi

PYTHON_BIN="$(discover_python)"

if [[ "${AS_ROOT}" == "0" ]]; then
  echo "==> SnapFS bootstrap installer"
  validate_python "${PYTHON_BIN}"
  warn_if_user_managed_python "${PYTHON_BIN}"

  if [[ -x "${SNAPFS_BIN}" ]]; then
    echo "Existing managed SnapFS install detected:"
    echo "  ${SNAPFS_BIN}"
    version="$(existing_snapfs_version)"
    if [[ -n "${version}" ]]; then
      echo "  version: ${version}"
    fi
  fi

  echo
  echo "Summary:"
  echo "  install root : ${INSTALL_ROOT}"
  echo "  virtualenv   : ${VENV_DIR}"
  echo "  snapfs bin   : ${SNAPFS_BIN}"
  echo "  python3      : ${PYTHON_BIN}"
  echo "  venv backend : ${VENV_BACKEND}"
  echo "  install spec : $(install_spec)"
  echo

  if [[ "$(id -u)" -ne 0 ]]; then
    confirm_yes "Proceed with bootstrap install using sudo?" "Y" || exit 0
    exec sudo \
      SNAPFS_PYTHON="${PYTHON_BIN}" \
      SNAPFS_VENV_BACKEND="${VENV_BACKEND}" \
      SNAPFS_VIRTUALENV_CMD="${VIRTUALENV_CMD}" \
      SNAPFS_INSTALL_ROOT="${INSTALL_ROOT}" \
      SNAPFS_VENV_DIR="${VENV_DIR}" \
      SNAPFS_INSTALL_EXTRAS="${INSTALL_EXTRAS}" \
      bash "$0" --as-root
  fi

  confirm_yes "Proceed with bootstrap install?" "Y" || exit 0
fi

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERR] Root privileges are required for the install phase" >&2
  exit 1
fi

validate_python "${PYTHON_BIN}"
bootstrap_runtime

echo
echo "==> Handing off to systemd installer"
exec env \
  SNAPFS_BIN="${SNAPFS_BIN}" \
  bash "${SYSTEMD_INSTALLER}"
