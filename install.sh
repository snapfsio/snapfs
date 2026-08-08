#!/usr/bin/env bash
set -euo pipefail

AS_ROOT=0
if [[ "${1:-}" == "--as-root" ]]; then
  AS_ROOT=1
fi

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
REPO_OWNER="${SNAPFS_REPO_OWNER:-snapfsio}"
REPO_NAME="${SNAPFS_REPO_NAME:-snapfs}"
DEFAULT_SNAPFS_VERSION="${DEFAULT_SNAPFS_VERSION:-0.4.2}"
LATEST_RELEASE_API="https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/releases/latest"
INSTALL_ROOT="${SNAPFS_INSTALL_ROOT:-/opt/snapfs}"
VENV_DIR="${SNAPFS_VENV_DIR:-${INSTALL_ROOT}/venv}"
INSTALL_EXTRAS="${SNAPFS_INSTALL_EXTRAS:-xxhash}"
SNAPFS_VERSION="${SNAPFS_VERSION:-}"
PYTHON_BIN="${SNAPFS_PYTHON:-}"
VENV_BACKEND="${SNAPFS_VENV_BACKEND:-}"
VIRTUALENV_CMD="${SNAPFS_VIRTUALENV_CMD:-}"
SNAPFS_BIN="${VENV_DIR}/bin/snapfs"
PIP_BIN="${VENV_DIR}/bin/pip"
VENV_PYTHON_BIN="${VENV_DIR}/bin/python"
TTY_PATH=""
BOOTSTRAP_ARCHIVE_DIR="${SNAPFS_BOOTSTRAP_ARCHIVE_DIR:-}"

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

repo_has_install_assets() {
  [[ -f "${SCRIPT_DIR}/pyproject.toml" && -f "${SCRIPT_DIR}/systemd/install.sh" ]]
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

discover_fetch_tool() {
  if command -v curl >/dev/null 2>&1; then
    printf '%s' "curl"
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    printf '%s' "wget"
    return 0
  fi

  printf '%s' ""
}

fetch_url() {
  local url="$1"
  local dest="${2:-}"
  local fetch_tool=""

  fetch_tool="$(discover_fetch_tool)"
  if [[ -z "${fetch_tool}" ]]; then
    echo "[ERR] Neither curl nor wget is available, but one is required to fetch SnapFS sources." >&2
    exit 1
  fi

  case "${fetch_tool}" in
    curl)
      if [[ -n "${dest}" ]]; then
        curl -fsSL "${url}" -o "${dest}"
      else
        curl -fsSL "${url}"
      fi
      ;;
    wget)
      if [[ -n "${dest}" ]]; then
        wget -qO "${dest}" "${url}"
      else
        wget -qO- "${url}"
      fi
      ;;
  esac
}

resolve_latest_release_version() {
  local payload=""

  if ! payload="$(fetch_url "${LATEST_RELEASE_API}")"; then
    return 1
  fi

  SNAPFS_API_PAYLOAD="${payload}" python3 - <<'PY' 2>/dev/null || true
import json
import os

payload = os.environ.get("SNAPFS_API_PAYLOAD", "")
if not payload:
    raise SystemExit(1)

data = json.loads(payload)
tag_name = str(data.get("tag_name", "")).strip()
if not tag_name:
    raise SystemExit(1)
print(tag_name)
PY
}

effective_snapfs_version() {
  local resolved=""

  if [[ -n "${SNAPFS_VERSION}" ]]; then
    printf '%s' "${SNAPFS_VERSION}"
    return 0
  fi

  resolved="$(resolve_latest_release_version || true)"
  if [[ -n "${resolved}" ]]; then
    printf '%s' "${resolved}"
    return 0
  fi

  printf '%s' "${DEFAULT_SNAPFS_VERSION}"
}

bootstrap_archive_url() {
  local version="$1"
  printf 'https://github.com/%s/%s/archive/refs/tags/%s.tar.gz' "${REPO_OWNER}" "${REPO_NAME}" "${version}"
}

bootstrap_repo_checkout() {
  local version=""
  local archive_url=""
  local work_dir=""
  local archive_path=""
  local extracted_dir=""

  if [[ -n "${BOOTSTRAP_ARCHIVE_DIR}" && -f "${BOOTSTRAP_ARCHIVE_DIR}/install.sh" ]]; then
    exec env \
      SNAPFS_BOOTSTRAP_ARCHIVE_DIR="${BOOTSTRAP_ARCHIVE_DIR}" \
      SNAPFS_INSTALL_ROOT="${INSTALL_ROOT}" \
      SNAPFS_VENV_DIR="${VENV_DIR}" \
      SNAPFS_INSTALL_EXTRAS="${INSTALL_EXTRAS}" \
      SNAPFS_VERSION="${SNAPFS_VERSION}" \
      SNAPFS_PYTHON="${PYTHON_BIN}" \
      SNAPFS_VENV_BACKEND="${VENV_BACKEND}" \
      SNAPFS_VIRTUALENV_CMD="${VIRTUALENV_CMD}" \
      bash "${BOOTSTRAP_ARCHIVE_DIR}/install.sh" "${@}"
  fi

  version="$(effective_snapfs_version)"
  archive_url="$(bootstrap_archive_url "${version}")"

  echo "==> Fetching SnapFS source archive"
  echo "  version : ${version}"
  echo "  url     : ${archive_url}"

  work_dir="$(mktemp -d)"
  archive_path="${work_dir}/snapfs.tar.gz"
  fetch_url "${archive_url}" "${archive_path}"
  tar -xzf "${archive_path}" -C "${work_dir}"
  extracted_dir="$(find "${work_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"

  if [[ -z "${extracted_dir}" || ! -f "${extracted_dir}/install.sh" ]]; then
    echo "[ERR] Failed to prepare SnapFS installer from ${archive_url}" >&2
    exit 1
  fi

  exec env \
    SNAPFS_BOOTSTRAP_ARCHIVE_DIR="${extracted_dir}" \
    SNAPFS_INSTALL_ROOT="${INSTALL_ROOT}" \
    SNAPFS_VENV_DIR="${VENV_DIR}" \
    SNAPFS_INSTALL_EXTRAS="${INSTALL_EXTRAS}" \
    SNAPFS_VERSION="${version}" \
    SNAPFS_PYTHON="${PYTHON_BIN}" \
    SNAPFS_VENV_BACKEND="${VENV_BACKEND}" \
    SNAPFS_VIRTUALENV_CMD="${VIRTUALENV_CMD}" \
    bash "${extracted_dir}/install.sh" "${@}"
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
    *" rocky "*|*" rhel "*|*" fedora "*|*" centos "*|*" alma "*)
      echo "      On RHEL/Rocky/Fedora-family systems, try:" >&2
      if command -v dnf >/dev/null 2>&1; then
        echo "      sudo dnf install python3-virtualenv" >&2
      else
        echo "      sudo yum install python3-virtualenv" >&2
      fi
      ;;
  esac
}

suggest_venv_backend_install() {
  local bin="$1"
  local py_mm=""
  local os_id=""
  local os_like=""
  local package_manager=""
  local package_name=""

  py_mm="$(python_major_minor "${bin}")"

  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    os_id="${ID:-}"
    os_like="${ID_LIKE:-}"
  fi

  case " ${os_id} ${os_like} " in
    *" ubuntu "*|*" debian "*)
      package_manager="apt"
      package_name="python${py_mm}-venv"
      ;;
    *" rocky "*|*" rhel "*|*" fedora "*|*" centos "*|*" alma "*)
      if command -v dnf >/dev/null 2>&1; then
        package_manager="dnf"
      elif command -v yum >/dev/null 2>&1; then
        package_manager="yum"
      fi
      package_name="python3-virtualenv"
      ;;
  esac

  if [[ -n "${package_manager}" && -n "${package_name}" ]]; then
    printf '%s|%s' "${package_manager}" "${package_name}"
  fi
}

install_venv_backend_package() {
  local package_manager="$1"
  local package_name="$2"

  case "${package_manager}" in
    apt)
      if [[ "$(id -u)" -eq 0 ]]; then
        apt install -y "${package_name}"
      else
        sudo apt install -y "${package_name}"
      fi
      ;;
    dnf)
      if [[ "$(id -u)" -eq 0 ]]; then
        dnf install -y "${package_name}"
      else
        sudo dnf install -y "${package_name}"
      fi
      ;;
    yum)
      if [[ "$(id -u)" -eq 0 ]]; then
        yum install -y "${package_name}"
      else
        sudo yum install -y "${package_name}"
      fi
      ;;
    *)
      return 1
      ;;
  esac
}

maybe_install_venv_backend() {
  local bin="$1"
  local suggestion=""
  local package_manager=""
  local package_name=""
  local install_cmd=""

  if ! is_interactive; then
    return 1
  fi

  suggestion="$(suggest_venv_backend_install "${bin}")"
  if [[ -z "${suggestion}" ]]; then
    return 1
  fi

  IFS='|' read -r package_manager package_name <<< "${suggestion}"
  if [[ -z "${package_manager}" || -z "${package_name}" ]]; then
    return 1
  fi

  case "${package_manager}" in
    apt)
      install_cmd="sudo apt install ${package_name}"
      ;;
    dnf)
      install_cmd="sudo dnf install ${package_name}"
      ;;
    yum)
      install_cmd="sudo yum install ${package_name}"
      ;;
  esac

  echo "[WARN] No usable virtual environment backend was found for: ${bin}" >&2
  echo "       SnapFS can install the required system package for you:" >&2
  echo "       ${install_cmd}" >&2

  confirm_yes "Proceed with this system package install?" "Y" || return 1

  if ! install_venv_backend_package "${package_manager}" "${package_name}"; then
    return 1
  fi

  VENV_BACKEND="$(discover_venv_backend)"
  [[ -n "${VENV_BACKEND}" ]]
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
    if maybe_install_venv_backend "${bin}"; then
      echo "Detected virtual environment backend after package install:"
      case "${VENV_BACKEND}" in
        venv)
          echo "  python3 -m venv"
          ;;
        python-virtualenv)
          echo "  python3 -m virtualenv"
          ;;
        virtualenv-cmd)
          echo "  ${VIRTUALENV_CMD}"
          ;;
      esac
      return 0
    fi
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
  :
fi

if ! repo_has_install_assets; then
  bootstrap_repo_checkout "${@}"
fi

SYSTEMD_INSTALLER="${SCRIPT_DIR}/systemd/install.sh"

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
