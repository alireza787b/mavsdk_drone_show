#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MDS_GCS_ENV_FILE:-/etc/mds/gcs.env}"

if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "${ENV_FILE}"
  set +a
fi

DEMO_PROFILE="${MDS_SAFE_PRODUCTION_DEMO:-false}"
case "${DEMO_PROFILE,,}" in
  false | 0 | no | "")
    ;;
  *)
    printf '%s\n' \
      "MDS_SAFE_PRODUCTION_DEMO is no longer supported. Configure mode, auth, MCP, and Simurgh settings explicitly in ${ENV_FILE}." \
      >&2
    exit 64
    ;;
esac
unset MDS_SAFE_PRODUCTION_DEMO

export MDS_MODE="${MDS_MODE:-real}"
export MDS_AGENT_ACTION_CIRCUIT_BREAKER="${MDS_AGENT_ACTION_CIRCUIT_BREAKER:-true}"
export MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION="${MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION:-true}"
export MDS_AGENT_ENABLED="${MDS_AGENT_ENABLED:-true}"
export MDS_AUTH_ENABLED="${MDS_AUTH_ENABLED:-false}"

case "${MDS_AUTH_ENABLED,,}" in
  true | 1 | yes | on)
    ;;
  *)
    printf '%s\n' \
      "WARNING: MDS dashboard authentication is disabled. Use this plug-and-play posture only on a trusted lab/SITL network; enable auth before shared, field, or commercial deployment." \
      >&2
    ;;
esac

resolve_command() {
  local candidate="$1"

  if [[ "${candidate}" == */* ]]; then
    if [[ -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
    return 1
  fi

  command -v "${candidate}"
}

resolve_python() {
  local candidate=""

  if [[ -n "${MDS_PYTHON_BIN:-}" ]]; then
    resolve_command "${MDS_PYTHON_BIN}"
    return
  fi

  if [[ -n "${MDS_VENV_PATH:-}" ]]; then
    for candidate in "${MDS_VENV_PATH}/bin/python3" "${MDS_VENV_PATH}/bin/python"; do
      if [[ -x "${candidate}" ]]; then
        printf '%s\n' "${candidate}"
        return 0
      fi
    done
    return 1
  fi

  if [[ -n "${VIRTUAL_ENV:-}" ]]; then
    for candidate in "${VIRTUAL_ENV}/bin/python3" "${VIRTUAL_ENV}/bin/python"; do
      if [[ -x "${candidate}" ]]; then
        printf '%s\n' "${candidate}"
        return 0
      fi
    done
    return 1
  fi

  resolve_command python3 || resolve_command python
}

if ! PYTHON_BIN="$(resolve_python)"; then
  printf '%s\n' \
    "Unable to resolve Python. Set MDS_VENV_PATH to a valid virtualenv or MDS_PYTHON_BIN to an executable." \
    >&2
  exit 69
fi

GCS_WORKERS="${MDS_GCS_WORKERS:-1}"
if [[ ! "${GCS_WORKERS}" =~ ^[0-9]+$ ]] || [[ "${GCS_WORKERS}" != "1" ]]; then
  printf '%s\n' \
    "MDS_GCS_WORKERS must be 1: the current GCS keeps authoritative live and Simurgh session state in one process." \
    >&2
  exit 64
fi

GUNICORN_COMMAND=()
if [[ -n "${MDS_GUNICORN_BIN:-}" ]]; then
  if ! GUNICORN_BIN="$(resolve_command "${MDS_GUNICORN_BIN}")"; then
    printf 'Configured MDS_GUNICORN_BIN is not executable: %s\n' "${MDS_GUNICORN_BIN}" >&2
    exit 69
  fi
  GUNICORN_COMMAND=("${GUNICORN_BIN}")
elif [[ -x "$(dirname "${PYTHON_BIN}")/gunicorn" ]]; then
  GUNICORN_COMMAND=("$(dirname "${PYTHON_BIN}")/gunicorn")
else
  GUNICORN_COMMAND=("${PYTHON_BIN}" -m gunicorn)
fi

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/gcs-server:${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

STATIC_PID=""
API_PID=""
cleanup() {
  local exit_status=$?

  trap - EXIT INT TERM
  if [[ -n "${STATIC_PID}" ]] && kill -0 "${STATIC_PID}" 2>/dev/null; then
    kill "${STATIC_PID}" 2>/dev/null || true
  fi
  if [[ -n "${API_PID}" ]] && kill -0 "${API_PID}" 2>/dev/null; then
    kill "${API_PID}" 2>/dev/null || true
  fi
  if [[ -n "${STATIC_PID}" ]]; then
    wait "${STATIC_PID}" 2>/dev/null || true
  fi
  if [[ -n "${API_PID}" ]]; then
    wait "${API_PID}" 2>/dev/null || true
  fi

  exit "${exit_status}"
}
handle_signal() {
  local exit_status="$1"

  trap - INT TERM
  exit "${exit_status}"
}
trap cleanup EXIT
trap 'handle_signal 130' INT
trap 'handle_signal 143' TERM

cd "${ROOT_DIR}"
"${PYTHON_BIN}" tools/spa_static_server.py \
  --directory app/dashboard/drone-dashboard/build \
  --port "${MDS_DASHBOARD_PORT:-3030}" &
STATIC_PID="$!"

cd "${ROOT_DIR}/gcs-server"
"${GUNICORN_COMMAND[@]}" \
  -w "${GCS_WORKERS}" \
  -k uvicorn.workers.UvicornWorker \
  -b "0.0.0.0:${MDS_GCS_API_PORT:-5030}" \
  --timeout "${MDS_GCS_TIMEOUT_SEC:-120}" \
  --log-level "${MDS_GCS_LOG_LEVEL:-info}" \
  app_fastapi:app &
API_PID="$!"

set +e
wait -n "${STATIC_PID}" "${API_PID}"
SERVICE_STATUS=$?
set -e

if [[ "${SERVICE_STATUS}" -eq 0 ]]; then
  printf '%s\n' "A GCS service process exited unexpectedly." >&2
  exit 1
fi

exit "${SERVICE_STATUS}"
