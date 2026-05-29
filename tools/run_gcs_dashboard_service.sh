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

if [[ "${MDS_SAFE_PRODUCTION_DEMO:-false}" == "true" ]]; then
  export MDS_MODE=real
  export MDS_AGENT_ACTION_CIRCUIT_BREAKER=true
  export MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION=true
  export MDS_AGENT_ENABLED=true
  export MDS_AGENT_PROVIDER="${MDS_AGENT_PROVIDER:-openai}"
  export MDS_AGENT_OPENAI_MODEL="${MDS_AGENT_OPENAI_MODEL:-gpt-5.4-nano}"
  export MDS_AGENT_WEB_SEARCH_ENABLED="${MDS_AGENT_WEB_SEARCH_ENABLED:-true}"
  export MDS_MCP_ENABLED="${MDS_MCP_ENABLED:-true}"
  export MDS_MCP_REQUIRE_AUTH=true
  export MDS_MCP_REQUIRED_SCOPES="${MDS_MCP_REQUIRED_SCOPES:-agent,admin}"
  export MDS_AUTH_ENABLED=true
  export MDS_API_AUTH_ENABLED=false
else
  export MDS_MODE="${MDS_MODE:-real}"
  export MDS_AGENT_ACTION_CIRCUIT_BREAKER="${MDS_AGENT_ACTION_CIRCUIT_BREAKER:-true}"
  export MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION="${MDS_AGENT_ALWAYS_CONFIRM_BEFORE_ACTION:-true}"
  export MDS_AGENT_ENABLED="${MDS_AGENT_ENABLED:-true}"
  export MDS_AUTH_ENABLED="${MDS_AUTH_ENABLED:-true}"
fi

export PYTHONPATH="${ROOT_DIR}:${ROOT_DIR}/gcs-server:${ROOT_DIR}/src${PYTHONPATH:+:${PYTHONPATH}}"

STATIC_PID=""
API_PID=""
cleanup() {
  if [[ -n "${STATIC_PID}" ]]; then
    kill "${STATIC_PID}" 2>/dev/null || true
  fi
  if [[ -n "${API_PID}" ]]; then
    kill "${API_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "${ROOT_DIR}"
python3 tools/spa_static_server.py \
  --directory app/dashboard/drone-dashboard/build \
  --port "${MDS_DASHBOARD_PORT:-3030}" &
STATIC_PID="$!"

cd "${ROOT_DIR}/gcs-server"
"${MDS_GUNICORN_BIN:-/opt/mds/venv/bin/gunicorn}" \
  -w "${MDS_GCS_WORKERS:-1}" \
  -k uvicorn.workers.UvicornWorker \
  -b "0.0.0.0:${MDS_GCS_API_PORT:-5030}" \
  --timeout "${MDS_GCS_TIMEOUT_SEC:-120}" \
  --log-level "${MDS_GCS_LOG_LEVEL:-info}" \
  app_fastapi:app &
API_PID="$!"

wait "${API_PID}"
