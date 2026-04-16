#!/bin/bash

#########################################
# GCS Server Launcher (FastAPI only)
#
# Project: MAVSDK Drone Show
# Version: Reads from VERSION file
#
# Legacy note:
#   Flask mode has been removed from the active deployment path.
#   This script is kept as a standalone FastAPI launcher for operators
#   who want a direct backend entrypoint outside linux_dashboard_start.sh.
#
# Usage: ./start_gcs_server.sh [MODE] [fastapi] [PORT]
#########################################

set -euo pipefail  # Strict error handling

# ===========================================
# CONFIGURATION
# ===========================================
DEFAULT_MODE="development"
DEFAULT_BACKEND="fastapi"
DEFAULT_PORT=5000
PROD_WSGI_WORKERS="${MDS_PROD_WSGI_WORKERS:-1}"
PROD_GUNICORN_TIMEOUT=120
PROD_LOG_LEVEL="info"
GCS_CONSOLE_LOG_LEVEL="${MDS_GCS_CONSOLE_LOG_LEVEL:-INFO}"
GCS_SYSTEM_CONFIG="${MDS_GCS_SYSTEM_CONFIG:-/etc/mds/gcs.env}"

# ===========================================
# PARSE ARGUMENTS
# ===========================================
MODE="${1:-$DEFAULT_MODE}"
BACKEND="${2:-$DEFAULT_BACKEND}"
PORT="${3:-$DEFAULT_PORT}"

if [[ "$BACKEND" =~ ^[0-9]+$ ]]; then
    PORT="$BACKEND"
    BACKEND="$DEFAULT_BACKEND"
fi

# ===========================================
# PATH RESOLUTION
# ===========================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VERSION_FILE="${PROJECT_ROOT}/VERSION"
VENV_PATH="${PROJECT_ROOT}/venv"
PROJECT_VERSION="unknown"

if [[ -f "$VERSION_FILE" ]]; then
    PROJECT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
fi

# ===========================================
# LOGGING FUNCTIONS
# ===========================================
log_info() { echo "[INFO] $1"; }
log_warn() { echo "[WARN] $1"; }
log_error() { echo "[ERROR] $1" >&2; }
log_success() { echo "[SUCCESS] $1"; }

enforce_fastapi_single_worker() {
    if [[ "$MODE" == "production" ]] && [[ "$BACKEND" == "fastapi" ]] && [[ "$PROD_WSGI_WORKERS" != "1" ]]; then
        log_warn "FastAPI production mode uses in-memory state for heartbeats, command tracking, and background pollers."
        log_warn "Overriding MDS_PROD_WSGI_WORKERS=$PROD_WSGI_WORKERS to 1 to prevent state divergence across workers."
        PROD_WSGI_WORKERS=1
    fi
}

apply_logging_mode_defaults() {
    export MDS_LOG_LEVEL="$GCS_CONSOLE_LOG_LEVEL"

    export MDS_LOG_FILE_LEVEL="${MDS_LOG_FILE_LEVEL:-DEBUG}"
}

# ===========================================
# DISPLAY USAGE
# ===========================================
display_usage() {
    cat << EOF
GCS Server Launcher - FastAPI

USAGE: $0 [MODE] [fastapi] [PORT]

ARGUMENTS:
  MODE      deployment mode (default: $DEFAULT_MODE)
            Options: development, production

  BACKEND   optional compatibility placeholder
            Only 'fastapi' is supported

  PORT      server port (default: $DEFAULT_PORT)

EXAMPLES:
  # Start FastAPI in development mode (default)
  $0

  # Start FastAPI in production mode
  $0 production fastapi 5000

ENVIRONMENT VARIABLES:
  GCS_ENV      Override deployment mode (development|production)
  GCS_PORT     Override server port
  GCS_BACKEND  Override backend choice (must remain 'fastapi')

EOF
    exit 0
}

# Check for help flags
if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
    display_usage
fi

# ===========================================
# ENVIRONMENT VARIABLE SUPPORT
# ===========================================
# Allow environment variables to override arguments
MODE="${GCS_ENV:-$MODE}"
BACKEND="${GCS_BACKEND:-$BACKEND}"
PORT="${GCS_PORT:-$PORT}"

if [[ "$BACKEND" == "uvicorn" || "$BACKEND" == "gunicorn" ]]; then
    log_warn "Legacy GCS_BACKEND=$BACKEND detected. Mapping to fastapi."
    BACKEND="fastapi"
fi

load_gcs_system_config() {
    if [[ "${MDS_SKIP_GCS_SYSTEM_CONFIG:-false}" == "true" ]]; then
        log_info "Skipping system GCS config load because MDS_SKIP_GCS_SYSTEM_CONFIG=true"
        return
    fi

    if [[ -f "$GCS_SYSTEM_CONFIG" ]]; then
        # shellcheck source=/dev/null
        source "$GCS_SYSTEM_CONFIG"

        PORT="${GCS_PORT:-$PORT}"
        export MDS_REPO_URL MDS_BRANCH MDS_INSTALL_DIR MDS_GIT_AUTO_PUSH 2>/dev/null || true
    else
        log_warn "System GCS config not found at $GCS_SYSTEM_CONFIG; continuing with current environment"
    fi
}

load_gcs_system_config

# ===========================================
# VALIDATION
# ===========================================
if [[ "$MODE" != "development" && "$MODE" != "production" ]]; then
    log_error "Invalid MODE: $MODE. Must be 'development' or 'production'"
    exit 1
fi

if [[ "$BACKEND" != "fastapi" ]]; then
    log_error "Invalid BACKEND: $BACKEND. Flask mode has been removed; use 'fastapi'."
    exit 1
fi

# ===========================================
# DEPENDENCY CHECK
# ===========================================
load_virtualenv() {
    if [[ -f "$VENV_PATH/bin/activate" ]]; then
        # shellcheck disable=SC1090
        source "$VENV_PATH/bin/activate"
        log_info "Activated virtual environment: $VENV_PATH"
    else
        log_warn "Virtual environment activation script not found at $VENV_PATH/bin/activate; using current Python interpreter"
    fi
}

check_dependencies() {
    log_info "Checking dependencies..."
    load_virtualenv

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    if ! python3 -c "import fastapi" 2>/dev/null; then
        log_error "FastAPI is not installed in the active interpreter."
        log_error "Install dependencies with: bash tools/mds_gcs_init.sh or pip install -r requirements.txt inside the venv."
        exit 1
    fi

    if [[ "$MODE" == "production" ]]; then
        if ! python3 -c "import gunicorn" 2>/dev/null; then
            log_error "Gunicorn is required for production mode but is not installed in the active interpreter."
            exit 1
        fi
    elif ! python3 -c "import uvicorn" 2>/dev/null; then
        log_error "Uvicorn is required for development mode but is not installed in the active interpreter."
        exit 1
    fi

    log_success "Dependencies check complete"
}

# ===========================================
# START SERVER
# ===========================================
start_server() {
    log_info "Starting GCS Server..."
    apply_logging_mode_defaults
    log_info "  Mode: $MODE"
    log_info "  Backend: $BACKEND"
    log_info "  Port: $PORT"
    log_info "  Directory: $SCRIPT_DIR"

    # Change to GCS server directory
    cd "$SCRIPT_DIR"

    # Export environment variables for the server
    export GCS_ENV="$MODE"
    export GCS_PORT="$PORT"
    export GCS_BACKEND="$BACKEND"
    export PYTHONPATH="${PROJECT_ROOT}:${PROJECT_ROOT}/src:${PYTHONPATH:-}"

    start_fastapi
}

start_fastapi() {
    log_info "Starting FastAPI server..."
    enforce_fastapi_single_worker
    local enable_access_logs="${MDS_GCS_ACCESS_LOGS:-false}"

    if [[ "$MODE" == "production" ]]; then
        # Production: keep a single worker until API state is moved out of process memory
        log_info "Running FastAPI with Gunicorn + Uvicorn worker ($PROD_WSGI_WORKERS worker)"
        log_info "Production optimizations: single-worker Gunicorn, worker recycling, graceful timeout"
        if [[ "${enable_access_logs,,}" == "true" ]]; then
            exec gunicorn app_fastapi:app \
                -w "$PROD_WSGI_WORKERS" \
                -k uvicorn.workers.UvicornWorker \
                -b "0.0.0.0:$PORT" \
                --timeout "$PROD_GUNICORN_TIMEOUT" \
                --log-level "$PROD_LOG_LEVEL" \
                --access-logfile - \
                --error-logfile - \
                --max-requests 1000 \
                --max-requests-jitter 50 \
                --graceful-timeout 30 \
                --keep-alive 5
        fi
        exec gunicorn app_fastapi:app \
            -w "$PROD_WSGI_WORKERS" \
            -k uvicorn.workers.UvicornWorker \
            -b "0.0.0.0:$PORT" \
            --timeout "$PROD_GUNICORN_TIMEOUT" \
            --log-level "$PROD_LOG_LEVEL" \
            --error-logfile - \
            --max-requests 1000 \
            --max-requests-jitter 50 \
            --graceful-timeout 30 \
            --keep-alive 5
    else
        # Development: Use Uvicorn directly with auto-reload
        # NOTE: Auto-reload spawns 2 processes (reloader + worker), so startup code runs twice
        log_info "Running FastAPI with Uvicorn (auto-reload enabled)"
        log_warn "Development mode: Server will auto-reload on file changes"
        if [[ "${enable_access_logs,,}" == "true" ]]; then
            exec uvicorn app_fastapi:app \
                --host 0.0.0.0 \
                --port "$PORT" \
                --reload \
                --log-level info
        fi
        exec uvicorn app_fastapi:app \
            --host 0.0.0.0 \
            --port "$PORT" \
            --reload \
            --log-level info \
            --no-access-log
    fi
}

# ===========================================
# MAIN
# ===========================================
main() {
    log_info "============================================"
    log_info "GCS Server Launcher v${PROJECT_VERSION}"
    log_info "============================================"

    check_dependencies
    start_server
}

# Run main function
main
