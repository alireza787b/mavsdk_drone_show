#!/bin/bash

#########################################
# GCS Server Launcher (Flask or FastAPI)
#
# Project: MAVSDK Drone Show
# Version: 2.0.0
#
# Supports both Flask and FastAPI backends
# with proper environment configuration
#
# Usage: ./start_gcs_server.sh [OPTIONS]
#########################################

set -euo pipefail  # Strict error handling

# ===========================================
# CONFIGURATION
# ===========================================
DEFAULT_MODE="development"
DEFAULT_BACKEND="fastapi"  # Options: flask, fastapi
DEFAULT_PORT=5000
PROD_WSGI_WORKERS=4
PROD_GUNICORN_TIMEOUT=120
PROD_LOG_LEVEL="info"

# ===========================================
# PARSE ARGUMENTS
# ===========================================
MODE="${1:-$DEFAULT_MODE}"
BACKEND="${2:-$DEFAULT_BACKEND}"
PORT="${3:-$DEFAULT_PORT}"

# ===========================================
# PATH RESOLUTION
# ===========================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ===========================================
# LOGGING FUNCTIONS
# ===========================================
log_info() { echo "[INFO] $1"; }
log_warn() { echo "[WARN] $1"; }
log_error() { echo "[ERROR] $1" >&2; }
log_success() { echo "[SUCCESS] $1"; }

# ===========================================
# DISPLAY USAGE
# ===========================================
display_usage() {
    cat << EOF
GCS Server Launcher - Flask or FastAPI

USAGE: $0 [MODE] [BACKEND] [PORT]

ARGUMENTS:
  MODE      deployment mode (default: $DEFAULT_MODE)
            Options: development, production

  BACKEND   server backend (default: $DEFAULT_BACKEND)
            Options: flask, fastapi

  PORT      server port (default: $DEFAULT_PORT)

EXAMPLES:
  # Start FastAPI in development mode (default)
  $0

  # Start FastAPI in production mode
  $0 production fastapi 5000

  # Start Flask in development mode
  $0 development flask 5000

  # Start Flask in production mode with gunicorn
  $0 production flask 5000

ENVIRONMENT VARIABLES:
  GCS_ENV      Override deployment mode (development|production)
  GCS_PORT     Override server port
  GCS_BACKEND  Override backend choice (flask|fastapi)

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

# ===========================================
# VALIDATION
# ===========================================
if [[ "$MODE" != "development" && "$MODE" != "production" ]]; then
    log_error "Invalid MODE: $MODE. Must be 'development' or 'production'"
    exit 1
fi

if [[ "$BACKEND" != "flask" && "$BACKEND" != "fastapi" ]]; then
    log_error "Invalid BACKEND: $BACKEND. Must be 'flask' or 'fastapi'"
    exit 1
fi

# ===========================================
# DEPENDENCY CHECK
# ===========================================
check_dependencies() {
    log_info "Checking dependencies..."

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 is not installed"
        exit 1
    fi

    # Check for FastAPI dependencies if using FastAPI
    if [[ "$BACKEND" == "fastapi" ]]; then
        if ! python3 -c "import fastapi" 2>/dev/null; then
            log_warn "FastAPI not installed. Installing dependencies..."
            pip3 install -r "${SCRIPT_DIR}/../requirements.txt"
        fi
    fi

    # Check for gunicorn in production mode
    if [[ "$MODE" == "production" ]]; then
        if ! python3 -c "import gunicorn" 2>/dev/null; then
            log_warn "Gunicorn not installed. Installing..."
            pip3 install gunicorn
        fi
    fi

    log_success "Dependencies check complete"
}

# ===========================================
# START SERVER
# ===========================================
start_server() {
    log_info "Starting GCS Server..."
    log_info "  Mode: $MODE"
    log_info "  Backend: $BACKEND"
    log_info "  Port: $PORT"
    log_info "  Directory: $SCRIPT_DIR"

    # Change to GCS server directory
    cd "$SCRIPT_DIR"

    # Export environment variables for the server
    export GCS_ENV="$MODE"
    export GCS_PORT="$PORT"

    # Also export legacy FLASK_* variables for backward compatibility
    export FLASK_ENV="$MODE"
    export FLASK_PORT="$PORT"

    if [[ "$BACKEND" == "fastapi" ]]; then
        start_fastapi
    else
        start_flask
    fi
}

start_fastapi() {
    log_info "Starting FastAPI server..."

    if [[ "$MODE" == "production" ]]; then
        # Production: Use Gunicorn with Uvicorn workers (optimized for performance)
        log_info "Running FastAPI with Gunicorn + Uvicorn workers ($PROD_WSGI_WORKERS workers)"
        log_info "Production optimizations: preload app, worker recycling, graceful timeout"
        exec gunicorn app_fastapi:app \
            -w "$PROD_WSGI_WORKERS" \
            -k uvicorn.workers.UvicornWorker \
            -b "0.0.0.0:$PORT" \
            --timeout "$PROD_GUNICORN_TIMEOUT" \
            --log-level "$PROD_LOG_LEVEL" \
            --access-logfile - \
            --error-logfile - \
            --preload-app \
            --max-requests 1000 \
            --max-requests-jitter 50 \
            --graceful-timeout 30 \
            --keep-alive 5
    else
        # Development: Use Uvicorn directly with auto-reload
        # NOTE: Auto-reload spawns 2 processes (reloader + worker), so startup code runs twice
        log_info "Running FastAPI with Uvicorn (auto-reload enabled)"
        log_warn "Development mode: Server will auto-reload on file changes"
        exec uvicorn app_fastapi:app \
            --host 0.0.0.0 \
            --port "$PORT" \
            --reload \
            --log-level info
    fi
}

start_flask() {
    log_info "Starting Flask server..."

    if [[ "$MODE" == "production" ]]; then
        # Production: Use Gunicorn WSGI server
        log_info "Running Flask with Gunicorn"
        exec gunicorn app:app \
            -w "$PROD_WSGI_WORKERS" \
            -b "0.0.0.0:$PORT" \
            --timeout "$PROD_GUNICORN_TIMEOUT" \
            --log-level "$PROD_LOG_LEVEL" \
            --access-logfile - \
            --error-logfile -
    else
        # Development: Use Flask development server
        log_info "Running Flask development server"
        exec python3 app.py
    fi
}

# ===========================================
# MAIN
# ===========================================
main() {
    log_info "============================================"
    log_info "GCS Server Launcher v2.0.0"
    log_info "============================================"

    check_dependencies
    start_server
}

# Run main function
main
