#!/bin/bash

#########################################
# Final Production-Ready Drone Services Launcher
#
# Project: Drone Show GCS Server
# Version: Production Final
#
# CRITICAL FIXES APPLIED:
# - FastAPI backend (Flask legacy removed)
# - Absolute path resolution for any execution directory
# - Clean bash commands (NO Unicode/emojis)
# - Robust virtual environment handling
# - Production-grade error handling
#
# Usage: ./linux_dashboard_start.sh [OPTIONS]
#########################################

# =============================================================================
# IMPORTANT: MAVLink Routing (External)
# =============================================================================
# This application expects MAVLink routing to be handled EXTERNALLY.
#
# For Raspberry Pi (Real Hardware):
#   1. Install mavlink-anywhere: git clone https://github.com/alireza787b/mavlink-anywhere
#   2. Run: cd mavlink-anywhere && sudo ./install_mavlink_router.sh
#   3. Configure: sudo ./configure_mavlink_router.sh
#      - Input: /dev/ttyS0:<baud> (your serial port and baudrate)
#        Holybro Pixhawk RPi CM4 baseboard typically uses /dev/ttyS0:921600 via FC TELEM2
#      - Local outputs: 127.0.0.1:14540, 127.0.0.1:12550, 127.0.0.1:14569
#      - Default GCS listener: device_ip:14550
#      - Optional remote push endpoint: GCS_IP:24550
#   4. Enable: sudo systemctl enable mavlink-router
#   5. Start: sudo systemctl start mavlink-router
#
# For SITL: Routing is handled automatically by startup_sitl.sh
#
# See docs/guides/mavlink-routing-setup.md for detailed instructions.
# =============================================================================

set -euo pipefail  # Strict error handling

# ===========================================
# CONFIGURATION
# ===========================================
DEFAULT_MODE="development"
PROD_WSGI_WORKERS="${MDS_PROD_WSGI_WORKERS:-1}"
PROD_WSGI_BIND="0.0.0.0:5030"
PROD_GUNICORN_TIMEOUT=120
PROD_LOG_LEVEL="info"
DEV_BACKEND_RELOAD="${MDS_GCS_BACKEND_RELOAD:-false}"
DEV_REACT_PORT=3030
DEV_GCS_PORT=5030  # GCS Server port for development
SESSION_NAME="MDS-GCS"
REACT_BUILD_MAX_OLD_SPACE_SIZE="${MDS_REACT_BUILD_MAX_OLD_SPACE_SIZE:-4096}"
NPM_ALLOW_INSTALL_FALLBACK="${MDS_ALLOW_NPM_INSTALL_FALLBACK:-false}"
ENABLE_GCS_ACCESS_LOGS="${MDS_GCS_ACCESS_LOGS:-false}"
GCS_CONSOLE_LOG_LEVEL="${MDS_GCS_CONSOLE_LOG_LEVEL:-INFO}"
NODE_BIN_PATH=""
NPM_BIN_PATH=""

enforce_fastapi_single_worker() {
    if [[ "$DEPLOYMENT_MODE" == "production" ]] && [[ "$PROD_WSGI_WORKERS" != "1" ]]; then
        log_warn "FastAPI production mode uses in-memory heartbeat, command, and background service state."
        log_warn "Overriding MDS_PROD_WSGI_WORKERS=$PROD_WSGI_WORKERS to 1 to avoid split state across workers."
        PROD_WSGI_WORKERS=1
    fi
}

apply_logging_mode_defaults() {
    export MDS_LOG_LEVEL="$GCS_CONSOLE_LOG_LEVEL"

    export MDS_LOG_FILE_LEVEL="${MDS_LOG_FILE_LEVEL:-DEBUG}"
}

backend_reload_enabled() {
    local normalized="${DEV_BACKEND_RELOAD,,}"
    [[ "$normalized" == "1" || "$normalized" == "true" || "$normalized" == "yes" || "$normalized" == "on" ]]
}

# ===========================================
# PATH RESOLUTION (ABSOLUTE PATHS ONLY)
# ===========================================
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"

# The script is in PROJECT_ROOT/app/, so PARENT_DIR is PROJECT_ROOT
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$PARENT_DIR"
MDS_REPO_ROOT="$PROJECT_ROOT"
DEPLOYMENT_PROFILE_LOADER="$PROJECT_ROOT/tools/load_deployment_profile.sh"
if [[ -f "$DEPLOYMENT_PROFILE_LOADER" ]]; then
    # shellcheck disable=SC1090
    source "$DEPLOYMENT_PROFILE_LOADER"
    DEV_GCS_PORT="${MDS_DEFAULT_GCS_API_PORT:-$DEV_GCS_PORT}"
    DEV_REACT_PORT="${MDS_DEFAULT_DASHBOARD_PORT:-$DEV_REACT_PORT}"
    PROD_WSGI_BIND="0.0.0.0:${DEV_GCS_PORT}"
fi

# All paths are relative to PROJECT_ROOT (the repository root)
REACT_APP_DIR="$PROJECT_ROOT/app/dashboard/drone-dashboard"
GCS_SERVER_DIR="$PROJECT_ROOT/gcs-server"
VENV_PATH="$PROJECT_ROOT/venv"

# Final path validation
if [[ ! -d "$GCS_SERVER_DIR" ]]; then
    echo "ERROR: GCS server directory not found at $GCS_SERVER_DIR"
    echo "Script location: $SCRIPT_DIR"
    echo "Parent directory: $PARENT_DIR"
    exit 1
fi

ENV_FILE_PATH="$REACT_APP_DIR/.env"
BUILD_DIR="$REACT_APP_DIR/build"
UPDATE_SCRIPT_PATH="$PROJECT_ROOT/tools/update_repo_ssh.sh"
VERSION_FILE_PATH="$PROJECT_ROOT/VERSION"
SPA_SERVER_SCRIPT="$PROJECT_ROOT/tools/spa_static_server.py"

# ===========================================
# VARIABLES
# ===========================================
DEPLOYMENT_MODE="$DEFAULT_MODE"
FORCE_REBUILD=false
CHECK_ONLY=false
RUN_GCS_SERVER=true
RUN_GUI_APP=true
USE_TMUX=true
COMBINED_VIEW=true
USE_SITL=false
USE_REAL=false
STATUS_ONLY=false
OVERWRITE_IP=""
SKIP_DEPENDENCY_CHECK=false
# Repository Configuration: Environment Variable Support (MDS v3.1+)
# This script now supports custom branches via environment variables
# Default behavior unchanged for normal users
BRANCH_NAME="${MDS_BRANCH:-${MDS_DEFAULT_BRANCH:-main}}"
PROJECT_VERSION="unknown"

if [[ -f "$VERSION_FILE_PATH" ]]; then
    PROJECT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE_PATH")"
fi

# ===========================================
# SYSTEM CONFIGURATION (MDS GCS Init Integration)
# ===========================================
GCS_SYSTEM_CONFIG="/etc/mds/gcs.env"

load_gcs_system_config() {
    if [[ -f "$GCS_SYSTEM_CONFIG" ]]; then
        # Export every key from the managed env file. Keeping this generic
        # prevents new runtime/security settings from being silently ignored.
        set -a
        # shellcheck source=/dev/null
        source "$GCS_SYSTEM_CONFIG"
        set +a

        # Apply config values (respect CLI overrides)
        [[ -z "${VENV_PATH_OVERRIDE:-}" ]] && [[ -n "${VENV_PATH:-}" ]] && VENV_PATH="$VENV_PATH"
        [[ -z "${BRANCH_OVERRIDE:-}" ]] && [[ -n "${MDS_BRANCH:-}" ]] && BRANCH_NAME="$MDS_BRANCH"
        if [[ -n "${MDS_GCS_API_PORT:-}" ]]; then
            DEV_GCS_PORT="$MDS_GCS_API_PORT"
        fi
        if [[ -n "${MDS_DASHBOARD_PORT:-}" ]]; then
            DEV_REACT_PORT="$MDS_DASHBOARD_PORT"
        fi
        PROD_WSGI_BIND="0.0.0.0:${DEV_GCS_PORT}"

        # Export repo/runtime settings so Python/runtime helpers inherit them
        export \
            MDS_REPO_URL \
            MDS_BRANCH \
            MDS_INSTALL_DIR \
            MDS_GIT_AUTO_PUSH \
            MDS_GIT_AUTH_TOKEN_FILE \
            MDS_GIT_AUTH_USERNAME \
            MDS_GIT_SSH_KEY_FILE \
            MDS_GIT_KNOWN_HOSTS_FILE \
            MDS_DOCKER_IMAGE \
            MDS_SITL_GIT_SYNC \
            MDS_SITL_GIT_SYNC_PREFLIGHT \
            MDS_SITL_REQUIREMENTS_SYNC \
            MDS_SITL_USE_HOST_STARTUP_SCRIPT \
            2>/dev/null || true
        return 0
    fi
    return 1
}

# ===========================================
# LOGGING FUNCTIONS
# ===========================================
log_info() { echo "[INFO] $1"; }
log_warn() { echo "[WARN] $1"; }
log_error() { echo "[ERROR] $1" >&2; }
log_success() { echo "[SUCCESS] $1"; }
log_header() { echo -e "\n=== $1 ==="; }

ensure_nodejs_in_path() {
    if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
        NODE_BIN_PATH="$(command -v node)"
        NPM_BIN_PATH="$(command -v npm)"
        return 0
    fi

    local candidate_dirs=()
    local invoking_user="${SUDO_USER:-}"
    local invoking_home=""
    local latest_node_dir=""

    if [[ -n "$invoking_user" ]]; then
        invoking_home=$(getent passwd "$invoking_user" | cut -d: -f6 || true)
    fi

    if [[ -n "$invoking_home" && -d "$invoking_home/.nvm/versions/node" ]]; then
        latest_node_dir=$(ls -d "$invoking_home"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1 || true)
        [[ -n "$latest_node_dir" ]] && candidate_dirs+=("$latest_node_dir/bin")
    fi

    if [[ -d "$HOME/.nvm/versions/node" ]]; then
        latest_node_dir=$(ls -d "$HOME"/.nvm/versions/node/v* 2>/dev/null | sort -V | tail -1 || true)
        [[ -n "$latest_node_dir" ]] && candidate_dirs+=("$latest_node_dir/bin")
    fi

    candidate_dirs+=(
        "$HOME/.volta/bin"
        "$HOME/.local/share/fnm"
        "/usr/local/bin"
        "/usr/bin"
        "/bin"
    )

    local dir
    for dir in "${candidate_dirs[@]}"; do
        if [[ -x "$dir/node" && -x "$dir/npm" ]]; then
            export PATH="$dir:$PATH"
            NODE_BIN_PATH="$dir/node"
            NPM_BIN_PATH="$dir/npm"
            log_info "Using Node.js toolchain from: $dir"
            return 0
        fi
    done

    log_error "Node.js and npm are not available in PATH."
    log_error "If Node.js was installed via nvm, rerun the GCS init flow or ensure the nvm node bin directory is reachable."
    exit 1
}

refresh_project_metadata() {
    if [[ -f "$VERSION_FILE_PATH" ]]; then
        PROJECT_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE_PATH")"
    fi
}

configure_react_version_env() {
    local git_commit
    local git_branch

    refresh_project_metadata

    git_commit=$(git -C "$PROJECT_ROOT" rev-parse --short HEAD 2>/dev/null || echo "unknown")
    git_branch=$(git -C "$PROJECT_ROOT" rev-parse --abbrev-ref HEAD 2>/dev/null || echo "$BRANCH_NAME")

    export REACT_APP_VERSION="$PROJECT_VERSION"
    export REACT_APP_GIT_COMMIT="$git_commit"
    export REACT_APP_GIT_BRANCH="$git_branch"
}

normalize_runtime_mode() {
    local value="${1:-}"
    value="$(printf '%s' "$value" | tr '[:upper:]' '[:lower:]')"

    case "$value" in
        real|hardware|production) echo "real" ;;
        sitl|sim|simulation|simulated) echo "sitl" ;;
        *) echo "" ;;
    esac
}

# ===========================================
# STATUS AND DIAGNOSTIC FUNCTIONS
# ===========================================
resolve_current_runtime_mode() {
    local normalized_mode=""
    normalized_mode="$(normalize_runtime_mode "${MDS_MODE:-}")"

    if [[ -n "$normalized_mode" ]]; then
        echo "$normalized_mode"
        return 0
    fi

    echo "sitl"
}

get_runtime_mode_source() {
    local normalized_mode=""
    normalized_mode="$(normalize_runtime_mode "${MDS_MODE:-}")"

    if [[ -n "$normalized_mode" ]]; then
        echo "env:MDS_MODE"
        return 0
    fi

    echo "default:sitl"
}

get_current_drone_mode() {
    local runtime_mode
    runtime_mode="$(resolve_current_runtime_mode)"

    if [[ "$runtime_mode" == "real" ]]; then
        echo "REAL (Hardware)"
    else
        echo "SITL (Simulation)"
    fi
}

normalize_repo_url_for_compare() {
    local repo_url="${1:-}"

    repo_url="${repo_url%.git}"
    repo_url="${repo_url#git@github.com:}"
    repo_url="${repo_url#https://github.com/}"
    repo_url="${repo_url#github.com/}"
    printf '%s\n' "$repo_url"
}

get_configured_repo_url() {
    if [[ -n "${MDS_REPO_URL:-}" ]]; then
        printf '%s\n' "$MDS_REPO_URL"
    else
        echo "UNSET"
    fi
}

get_origin_remote_url() {
    git -C "$PROJECT_ROOT" remote get-url origin 2>/dev/null || echo "UNAVAILABLE"
}

repo_authority_status() {
    local configured_repo="${MDS_REPO_URL:-}"
    local origin_remote=""

    origin_remote="$(get_origin_remote_url)"

    if [[ -z "$configured_repo" ]]; then
        echo "NO CONFIGURED REPO"
        return 0
    fi

    if [[ "$origin_remote" == "UNAVAILABLE" ]]; then
        echo "NO GIT REMOTE"
        return 0
    fi

    if [[ "$(normalize_repo_url_for_compare "$configured_repo")" == "$(normalize_repo_url_for_compare "$origin_remote")" ]]; then
        echo "MATCH"
    else
        echo "MISMATCH"
    fi
}

get_repo_access_mode() {
    local repo_url="${MDS_REPO_URL:-$(get_origin_remote_url)}"

    if [[ "$repo_url" == git@github.com:* ]]; then
        echo "SSH deploy key"
    elif [[ "$repo_url" == https://github.com/* ]] && [[ -n "${MDS_GIT_AUTH_TOKEN_FILE:-}" ]]; then
        echo "HTTPS token file"
    elif [[ "$repo_url" == https://github.com/* ]]; then
        echo "HTTPS public/read-only"
    else
        echo "CUSTOM/UNKNOWN"
    fi
}

get_git_auto_push_status() {
    if [[ -n "${MDS_GIT_AUTO_PUSH:-}" ]]; then
        printf '%s\n' "$MDS_GIT_AUTO_PUSH"
    else
        echo "UNSET"
    fi
}

persist_runtime_mode_in_gcs_config() {
    local runtime_mode="$1"

    [[ -f "$GCS_SYSTEM_CONFIG" ]] || return 0

    if [[ ! -w "$GCS_SYSTEM_CONFIG" ]]; then
        log_warn "Cannot persist MDS_MODE=${runtime_mode} to ${GCS_SYSTEM_CONFIG}; using process override only."
        return 0
    fi

    if grep -q '^MDS_MODE=' "$GCS_SYSTEM_CONFIG"; then
        sed -i "s/^MDS_MODE=.*/MDS_MODE=${runtime_mode}/" "$GCS_SYSTEM_CONFIG"
    else
        printf '\nMDS_MODE=%s\n' "$runtime_mode" >> "$GCS_SYSTEM_CONFIG"
    fi
}

apply_requested_runtime_mode() {
    local requested_mode=""

    if [[ "$USE_REAL" == "true" ]]; then
        requested_mode="real"
        log_info "Switching canonical runtime mode to REAL..."
    elif [[ "$USE_SITL" == "true" ]]; then
        requested_mode="sitl"
        log_info "Switching canonical runtime mode to SITL..."
    else
        return 0
    fi

    export MDS_MODE="$requested_mode"
    persist_runtime_mode_in_gcs_config "$requested_mode"
    log_success "Runtime mode set to ${requested_mode}."
}

show_current_status() {
    cat << EOF

===============================================
  DRONE SERVICES - CURRENT STATUS
===============================================
Runtime Mode:     $(get_current_drone_mode)
Mode Source:      $(get_runtime_mode_source)
Configured Repo:  $(get_configured_repo_url)
Origin Remote:    $(get_origin_remote_url)
Repo Authority:   $(repo_authority_status)
Repo Access:      $(get_repo_access_mode)
Git Auto Push:    $(get_git_auto_push_status)
Backend:          FastAPI
Backend Reload:   $([[ "$DEPLOYMENT_MODE" == "production" ]] && echo "DISABLED (production)" || (backend_reload_enabled && echo "ENABLED (dev override)" || echo "DISABLED (state-safe default)"))
Virtual Env:      $([[ -d "$VENV_PATH" ]] && echo "OK ($VENV_PATH)" || echo "MISSING")
React Build:      $([[ -d "$BUILD_DIR" ]] && echo "EXISTS" || echo "NOT BUILT")
.env File:        $([[ -f "$ENV_FILE_PATH" ]] && echo "EXISTS" || echo "MISSING")

PATHS:
  GCS Server:     $GCS_SERVER_DIR
  React App:      $REACT_APP_DIR
  Build Dir:      $BUILD_DIR

PORTS:
  GCS Server:     $DEV_GCS_PORT
  React App:      $DEV_REACT_PORT

To change mode:
  SITL mode:      $0 --sitl
  Real mode:      $0 --real
===============================================
EOF
}

check_python_dependencies() {
    if [[ "$SKIP_DEPENDENCY_CHECK" == "true" ]]; then
        log_info "Skipping Python dependency check (--skip-deps)"
        return 0
    fi

    local requirements_file="$PARENT_DIR/requirements.txt"
    local venv_marker="$VENV_PATH/.deps_installed"

    if [[ ! -f "$requirements_file" ]]; then
        log_warn "requirements.txt not found, skipping dependency check"
        return 0
    fi

    # Check if requirements changed since last install
    if [[ -f "$venv_marker" ]]; then
        if [[ "$requirements_file" -nt "$venv_marker" ]]; then
            log_info "requirements.txt changed, updating dependencies..."
            pip install -r "$requirements_file" --quiet
            touch "$venv_marker"
            log_success "Python dependencies updated"
        else
            log_info "Python dependencies are up-to-date"
        fi
    else
        log_info "Installing Python dependencies..."
        pip install -r "$requirements_file" --quiet
        touch "$venv_marker"
        log_success "Python dependencies installed"
    fi
}

run_health_check() {
    log_header "HEALTH CHECK"
    local all_ok=true

    # Check GCS Server
    if [[ "$RUN_GCS_SERVER" == "true" ]]; then
        log_info "Checking GCS Server on port $DEV_GCS_PORT..."
        sleep 2  # Give server time to start
        for i in {1..5}; do
            if curl -s "http://localhost:$DEV_GCS_PORT/api/v1/system/health" > /dev/null 2>&1; then
                log_success "GCS Server is responding"
                break
            elif curl -s "http://localhost:$DEV_GCS_PORT/" > /dev/null 2>&1; then
                log_success "GCS Server is responding (health endpoint not yet ready)"
                break
            fi
            if [[ $i -eq 5 ]]; then
                log_warn "GCS Server not responding yet (may still be starting)"
                all_ok=false
            fi
            sleep 1
        done
    fi

    # Check React App
    if [[ "$RUN_GUI_APP" == "true" ]]; then
        log_info "Checking React App on port $DEV_REACT_PORT..."
        for i in {1..5}; do
            if curl -s "http://localhost:$DEV_REACT_PORT/" > /dev/null 2>&1; then
                log_success "React App is responding"
                break
            fi
            if [[ $i -eq 5 ]]; then
                log_warn "React App not responding yet (may still be starting)"
                all_ok=false
            fi
            sleep 1
        done
    fi

    if [[ "$all_ok" == "true" ]]; then
        log_success "All services healthy!"
    else
        log_warn "Some services may still be starting - check tmux session"
    fi
}

run_configuration_check() {
    log_header "CONFIGURATION CHECK"
    local all_ok=true

    # Check virtual environment
    if [[ -d "$VENV_PATH" ]]; then
        log_success "Virtual environment: OK"
    else
        log_error "Virtual environment: MISSING at $VENV_PATH"
        all_ok=false
    fi

    # Check GCS server directory
    if [[ -d "$GCS_SERVER_DIR" ]]; then
        log_success "GCS Server directory: OK"
    else
        log_error "GCS Server directory: MISSING at $GCS_SERVER_DIR"
        all_ok=false
    fi

    # Check React app
    if [[ -f "$REACT_APP_DIR/package.json" ]]; then
        log_success "React app: OK"
    else
        log_error "React app: MISSING package.json"
        all_ok=false
    fi

    if [[ "$RUN_GUI_APP" == "true" ]]; then
        ensure_nodejs_in_path
        log_success "Node.js/npm: AVAILABLE"
    fi

    # Check .env file
    if [[ -f "$ENV_FILE_PATH" ]]; then
        log_success ".env file: OK"
        local server_url=$(grep "^REACT_APP_MDS_SERVER_URL=" "$ENV_FILE_PATH" 2>/dev/null | head -1 || echo "")
        if [[ -n "$server_url" ]]; then
            log_info "  Server URL: $server_url (explicit override)"
        else
            log_info "  Server URL: Auto-detected from browser"
        fi
    else
        log_warn ".env file: MISSING (will be created on first run)"
        log_info "  Server URL: Will auto-detect from browser"
    fi

    # Check current runtime mode
    log_info "Current runtime mode: $(get_current_drone_mode) ($(get_runtime_mode_source))"

    # Check tmux
    if command -v tmux &> /dev/null; then
        log_success "tmux: INSTALLED"
    else
        log_warn "tmux: NOT INSTALLED (will be installed on first run)"
    fi

    # Check Python dependencies
    if [[ -d "$VENV_PATH" ]]; then
        source "$VENV_PATH/bin/activate" 2>/dev/null
        if python -c "import fastapi" 2>/dev/null; then
            log_success "FastAPI: INSTALLED"
        else
            log_warn "FastAPI: NOT INSTALLED (will be installed on first run)"
        fi
    fi

    log_header "CHECK COMPLETE"
    if [[ "$all_ok" == "true" ]]; then
        log_success "All checks passed! Ready to start."
        echo ""
        echo "Quick start commands:"
        echo "  SITL mode:  $0 --sitl"
        echo "  Real mode:  $0 --real"
        echo "  Production: $0 --prod --real"
    else
        log_error "Some checks failed. Please fix the issues above."
        exit 1
    fi
}

# ===========================================
# BACKEND VALIDATION
# ===========================================
validate_backend() {
    # Verify FastAPI is installed
    if ! python -c "import fastapi" 2>/dev/null; then
        log_error "FastAPI not installed!"
        echo ""
        echo "  Install with: pip install fastapi uvicorn"
        echo ""
        exit 1
    fi

    if ! python -c "import uvicorn" 2>/dev/null; then
        log_error "Uvicorn not installed!"
        echo ""
        echo "  Install with: pip install uvicorn"
        echo ""
        exit 1
    fi

    log_success "FastAPI backend ready"
}

# ===========================================
# GCS INITIALIZATION CHECK
# ===========================================
check_gcs_initialized() {
    if [[ ! -f "/etc/mds/gcs.env" ]] && [[ ! -d "$VENV_PATH" ]]; then
        log_warn "GCS may not be fully initialized"
        echo ""
        echo "If this is a fresh installation, run:"
        echo "  sudo ./tools/mds_gcs_init.sh"
        echo ""
        if [[ "${SKIP_INIT_CHECK:-false}" != "true" ]]; then
            read -p "Continue anyway? [y/N]: " confirm
            [[ "${confirm,,}" != "y" ]] && exit 1
        fi
    fi
}

# ===========================================
# UTILITY FUNCTIONS
# ===========================================
display_usage() {
    cat << EOF
Production-Ready Drone Services Launcher

USAGE: $0 [OPTIONS]

MODE OPTIONS:
  --prod, --production  : Production mode (optimized builds, WSGI server)
  --dev, --development  : Development mode (hot reload, debug server)

BUILD OPTIONS:
  --rebuild             : Force rebuild all components (React + dependencies)
  --force-rebuild       : Same as --rebuild (alias)
  --skip-deps           : Skip Python dependency check (faster startup)

DRONE MODE OPTIONS:
  --sitl                : Switch to simulation mode (SITL)
  --real                : Switch to real drone/hardware mode
  (If neither specified, current mode is preserved)

SERVICE OPTIONS:
  -g                    : Do NOT run GCS Server (default: enabled)
  -u                    : Do NOT run GUI React App (default: enabled)
  -n                    : Do NOT use tmux (default: uses tmux)
  -s                    : Run components in separate windows (default: combined)

DIAGNOSTICS:
  --check               : Check configuration and dependencies without starting
  --status              : Show current runtime mode and configuration

NETWORK OPTIONS:
  --overwrite-ip <IP>   : Override server IP in environment

REPOSITORY OPTIONS:
  -b <branch>           : Specify git branch (default: from MDS_BRANCH env var)

HELP:
  -h, --help            : Display this help message

EXAMPLES:
  Quick start (SITL):    $0 --sitl
  Quick start (Real):    $0 --real
  Production deploy:     $0 --prod --real
  Dev with rebuild:      $0 --dev --sitl --rebuild
  Check config only:     $0 --check
  Show current status:   $0 --status
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prod|--production) DEPLOYMENT_MODE="production"; shift ;;
            --dev|--development) DEPLOYMENT_MODE="development"; shift ;;
            --rebuild|--force-rebuild) FORCE_REBUILD=true; shift ;;
            --skip-deps) SKIP_DEPENDENCY_CHECK=true; shift ;;
            --check) CHECK_ONLY=true; shift ;;
            --status) STATUS_ONLY=true; shift ;;
            --sitl)
                if [[ "$USE_REAL" == "true" ]]; then
                    log_error "Cannot use --sitl and --real simultaneously."
                    exit 1
                fi
                USE_SITL=true; shift ;;
            --real)
                if [[ "$USE_SITL" == "true" ]]; then
                    log_error "Cannot use --sitl and --real simultaneously."
                    exit 1
                fi
                USE_REAL=true; shift ;;
            --overwrite-ip)
                if [[ -n "${2:-}" ]]; then
                    OVERWRITE_IP="$2"; shift 2
                else
                    log_error "--overwrite-ip requires an argument."; exit 1
                fi ;;
            -b)
                if [[ -n "${2:-}" ]]; then
                    BRANCH_NAME="$2"; shift 2
                else
                    log_error "-b requires a branch name."; exit 1
                fi ;;
            -g) RUN_GCS_SERVER=false; shift ;;
            -u) RUN_GUI_APP=false; shift ;;
            -n) USE_TMUX=false; shift ;;
            -s) COMBINED_VIEW=false; shift ;;
            -h|--help) display_usage; exit 0 ;;
            *) log_error "Unknown option: $1"; display_usage; exit 1 ;;
        esac
    done
}

check_command_installed() {
    local cmd="$1"
    local pkg="$2"
    if ! command -v "$cmd" &> /dev/null; then
        log_warn "$cmd not found. Installing $pkg..."
        sudo apt-get update && sudo apt-get install -y "$pkg"
        if [[ $? -ne 0 ]]; then
            log_error "Failed to install $pkg. Please install manually."
            exit 1
        fi
        log_success "$pkg installed successfully."
    else
        log_info "$cmd is available."
    fi
}

check_and_kill_port() {
    local port="$1"
    check_command_installed "lsof" "lsof"
    local pids=$(lsof -t -i :"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
        log_warn "Port $port is in use. Sending SIGTERM to processes: $pids"
        echo "$pids" | xargs -r kill
        sleep 2

        local remaining
        remaining=$(lsof -t -i :"$port" 2>/dev/null || true)
        if [[ -n "$remaining" ]]; then
            log_warn "Port $port is still busy. Escalating to SIGKILL: $remaining"
            echo "$remaining" | xargs -r kill -9
        fi

        log_success "Port $port freed."
    else
        log_info "Port $port is available."
    fi
}

load_virtualenv() {
    if [[ -d "$VENV_PATH" ]]; then
        source "$VENV_PATH/bin/activate"
        log_success "Virtual environment activated: $VENV_PATH"
    else
        log_error "Virtual environment not found: $VENV_PATH"
        log_error "Please create virtual environment first."
        exit 1
    fi
}

update_repository() {
    if [[ -n "$BRANCH_NAME" && -f "$UPDATE_SCRIPT_PATH" ]]; then
        local update_args=("-b" "$BRANCH_NAME")
        log_info "Updating repository to branch: $BRANCH_NAME"
        if [[ -n "${MDS_REPO_URL:-}" ]]; then
            update_args+=("--repo-url" "$MDS_REPO_URL")
            log_info "Using configured repository URL: $MDS_REPO_URL"
        fi
        REPO_DIR="$PROJECT_ROOT" bash "$UPDATE_SCRIPT_PATH" "${update_args[@]}"
        if [[ $? -eq 0 ]]; then
            refresh_project_metadata
            log_success "Repository updated successfully."
        else
            log_error "Repository update failed."
            exit 1
        fi
    else
        log_info "Repository update skipped."
    fi
}

handle_env_file() {
    log_info "Checking .env configuration..."

    local env_example="$REACT_APP_DIR/.env.example"
    local env_changed=false

    set_dashboard_env_value() {
        local key="$1"
        local value="$2"
        local current=""

        current="$(grep -m1 "^${key}=" "$ENV_FILE_PATH" 2>/dev/null | cut -d= -f2- || true)"
        if grep -q "^${key}=" "$ENV_FILE_PATH" 2>/dev/null; then
            if [[ "$current" != "$value" ]]; then
                sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE_PATH"
                env_changed=true
            fi
        else
            printf '\n%s=%s\n' "$key" "$value" >> "$ENV_FILE_PATH"
            env_changed=true
        fi

        if grep -q "^# ${key}=" "$ENV_FILE_PATH" 2>/dev/null; then
            local current_comment=""
            current_comment="$(grep -m1 "^# ${key}=" "$ENV_FILE_PATH" 2>/dev/null | cut -d= -f2- || true)"
            if [[ "$current_comment" != "$value" ]]; then
                sed -i "s|^# ${key}=.*|# ${key}=${value}|" "$ENV_FILE_PATH"
                env_changed=true
            fi
        fi
    }

    remove_dashboard_env_key() {
        local key="$1"
        if grep -q "^${key}=" "$ENV_FILE_PATH" 2>/dev/null || grep -q "^# ${key}=" "$ENV_FILE_PATH" 2>/dev/null; then
            sed -i "/^${key}=.*/d;/^# ${key}=.*/d" "$ENV_FILE_PATH"
            env_changed=true
        fi
    }

    migrate_legacy_dashboard_server_url() {
        local old_key="REACT_APP_SERVER_URL"
        local new_key="REACT_APP_MDS_SERVER_URL"
        local old_value=""

        old_value="$(grep -m1 "^${old_key}=" "$ENV_FILE_PATH" 2>/dev/null | cut -d= -f2- || true)"
        if [[ -n "$old_value" ]] && ! grep -q "^${new_key}=" "$ENV_FILE_PATH" 2>/dev/null; then
            set_dashboard_env_value "$new_key" "$old_value"
            log_warn "Migrated obsolete ${old_key} to ${new_key}."
        fi
        remove_dashboard_env_key "$old_key"
    }

    if [[ -f "$ENV_FILE_PATH" ]]; then
        log_success ".env file found."
        migrate_legacy_dashboard_server_url

        # Handle explicit IP override (for advanced use cases)
        if [[ -n "$OVERWRITE_IP" ]]; then
            log_info "Overwriting server IP to: $OVERWRITE_IP"
            cp "$ENV_FILE_PATH" "$ENV_FILE_PATH.bak"
            set_dashboard_env_value "REACT_APP_MDS_SERVER_URL" "http://$OVERWRITE_IP"
            log_success "Server IP updated and backup created."
        fi
    else
        log_warn ".env file not found. Creating from template..."
        mkdir -p "$(dirname "$ENV_FILE_PATH")"

        if [[ -f "$env_example" ]]; then
            # Copy from .env.example (server URL is unset for auto-detection)
            cp "$env_example" "$ENV_FILE_PATH"
            log_success ".env created from template"
            log_info "Server URL: Auto-detected from browser (no configuration needed)"
        else
            # Fallback: create minimal .env with essential settings
            cat > "$ENV_FILE_PATH" << EOF
# Auto-generated .env file
# Server URL is auto-detected from browser location (no configuration needed)
# Uncomment only if you need to override (e.g., different host):
# REACT_APP_MDS_SERVER_URL=http://192.168.1.100

REACT_APP_GCS_PORT=${DEV_GCS_PORT}
REACT_APP_DRONE_PORT=${MDS_DEFAULT_DRONE_API_PORT:-7070}
PORT=${DEV_REACT_PORT}
GENERATE_SOURCEMAP=false
SKIP_PREFLIGHT_CHECK=true
EOF
            log_success ".env file created with auto-detection enabled"
        fi

        # Apply explicit override if provided
        if [[ -n "$OVERWRITE_IP" ]]; then
            log_info "Applying server IP override: $OVERWRITE_IP"
            set_dashboard_env_value "REACT_APP_MDS_SERVER_URL" "http://$OVERWRITE_IP"
            log_success "Server IP override applied: $OVERWRITE_IP"
        fi
    fi

    migrate_legacy_dashboard_server_url

    # These values are controlled by the launcher/deployment profile. Keep them
    # synchronized on existing hosts so stale .env files cannot point a rebuilt
    # dashboard at the wrong backend port.
    set_dashboard_env_value "REACT_APP_GCS_PORT" "$DEV_GCS_PORT"
    set_dashboard_env_value "REACT_APP_DRONE_PORT" "${MDS_DEFAULT_DRONE_API_PORT:-7070}"
    set_dashboard_env_value "PORT" "$DEV_REACT_PORT"
    set_dashboard_env_value "GENERATE_SOURCEMAP" "false"
    set_dashboard_env_value "SKIP_PREFLIGHT_CHECK" "true"

    if [[ "$env_changed" == "true" ]]; then
        log_success "Dashboard .env runtime keys synchronized."
    fi
}

check_build_needed() {
    if [[ "$FORCE_REBUILD" == "true" ]]; then
        log_info "Force rebuild requested."
        return 0
    fi

    local build_marker=""
    build_marker="$(get_react_build_marker || true)"
    if [[ -z "$build_marker" ]]; then
        log_info "No React build marker found. Build needed."
        return 0
    fi

    local package_json="$REACT_APP_DIR/package.json"
    if [[ -f "$package_json" && "$package_json" -nt "$build_marker" ]]; then
        log_info "Package.json updated. Build needed."
        return 0
    fi

    local package_lock="$REACT_APP_DIR/package-lock.json"
    if [[ -f "$package_lock" && "$package_lock" -nt "$build_marker" ]]; then
        log_info "Package-lock.json updated. Build needed."
        return 0
    fi

    if [[ -f "$ENV_FILE_PATH" && "$ENV_FILE_PATH" -nt "$build_marker" ]]; then
        log_info ".env updated. Build needed."
        return 0
    fi

    if [[ -f "$VERSION_FILE_PATH" && "$VERSION_FILE_PATH" -nt "$build_marker" ]]; then
        log_info "VERSION updated. Build needed."
        return 0
    fi

    local public_dir="$REACT_APP_DIR/public"
    if path_tree_has_updates_since "$public_dir" "$build_marker"; then
        log_info "Public assets updated. Build needed."
        return 0
    fi

    local src_dir="$REACT_APP_DIR/src"
    if path_tree_has_updates_since "$src_dir" "$build_marker"; then
        log_info "Source files updated. Build needed."
        return 0
    fi

    log_info "Build marker is up-to-date. Skipping rebuild."
    return 1
}

get_react_build_marker() {
    local candidate=""

    for candidate in \
        "$BUILD_DIR/asset-manifest.json" \
        "$BUILD_DIR/index.html"
    do
        if [[ -f "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    return 1
}

path_tree_has_updates_since() {
    local candidate_path="$1"
    local reference_path="$2"

    if [[ ! -e "$candidate_path" || ! -e "$reference_path" ]]; then
        return 1
    fi

    if [[ -f "$candidate_path" ]]; then
        [[ "$candidate_path" -nt "$reference_path" ]]
        return $?
    fi

    if [[ -d "$candidate_path" ]]; then
        local newer_file
        newer_file="$(find "$candidate_path" -type f -newer "$reference_path" 2>/dev/null | head -1 || true)"
        [[ -n "$newer_file" ]]
        return $?
    fi

    return 1
}

build_react_app() {
    log_info "Building React application for production..."
    ensure_nodejs_in_path
    
    cd "$REACT_APP_DIR" || {
        log_error "Failed to navigate to React app directory: $REACT_APP_DIR"
        exit 1
    }
    
    if [[ ! -d "node_modules" || "$REACT_APP_DIR/package.json" -nt "node_modules" || "$REACT_APP_DIR/package-lock.json" -nt "node_modules" ]]; then
        install_dashboard_dependencies
    fi

    log_info "Building optimized production bundle..."
    NODE_OPTIONS="${NODE_OPTIONS:-} --max_old_space_size=${REACT_BUILD_MAX_OLD_SPACE_SIZE}" "$NPM_BIN_PATH" run build
    if [[ $? -ne 0 ]]; then
        log_error "Build failed."
        exit 1
    fi
    
    log_success "React build completed successfully."
}

install_dashboard_dependencies() {
    log_info "Installing dashboard npm dependencies..."
    ensure_nodejs_in_path

    if "$NPM_BIN_PATH" ci --no-audit --no-fund; then
        log_success "Dashboard npm dependencies ready."
        return 0
    fi

    if [[ "$NPM_ALLOW_INSTALL_FALLBACK" == "true" ]]; then
        log_warn "npm ci failed. MDS_ALLOW_NPM_INSTALL_FALLBACK=true, so npm install will be attempted."
        "$NPM_BIN_PATH" install --no-audit --no-fund
        log_success "Dashboard npm dependencies ready via npm install fallback."
        return 0
    fi

    log_error "npm ci failed. Refusing to run npm install automatically on this host."
    log_error "Refresh package-lock.json in git, or set MDS_ALLOW_NPM_INSTALL_FALLBACK=true for an explicit one-off fallback."
    exit 1
}

verify_react_setup() {
    log_info "Verifying React setup..."

    if [[ ! -f "$REACT_APP_DIR/package.json" ]]; then
        log_error "package.json not found at: $REACT_APP_DIR"
        exit 1
    fi

    # Verify node_modules exists (MDS GCS Init integration)
    if [[ ! -d "$REACT_APP_DIR/node_modules" || "$REACT_APP_DIR/package.json" -nt "$REACT_APP_DIR/node_modules" || "$REACT_APP_DIR/package-lock.json" -nt "$REACT_APP_DIR/node_modules" ]]; then
        log_warn "Node modules not installed at $REACT_APP_DIR"
        (
            cd "$REACT_APP_DIR" && install_dashboard_dependencies
        ) || {
            log_error "Failed to install npm dependencies"
            log_info "Run: cd $REACT_APP_DIR && npm ci --no-audit --no-fund"
            exit 1
        }
    fi

    log_success "React setup verified."
}

install_production_dependencies() {
    log_info "Installing production dependencies..."
    
    if ! python -c "import gunicorn" 2>/dev/null; then
        log_info "Installing gunicorn for production WSGI server..."
        pip install gunicorn
        if [[ $? -ne 0 ]]; then
            log_error "Failed to install gunicorn."
            exit 1
        fi
        log_success "Gunicorn installed successfully."
    else
        log_info "Gunicorn is already installed."
    fi
}

setup_production_environment() {
    apply_logging_mode_defaults

    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        log_info "Configuring production environment..."
        # Environment configuration
        export GCS_ENV=production
        export MDS_GCS_API_PORT="$DEV_GCS_PORT"
        export MDS_DASHBOARD_PORT="$DEV_REACT_PORT"
        # Node/React environment
        export NODE_ENV=production
        export REACT_APP_ENV=production
        install_production_dependencies
        log_success "Production environment configured (Backend: FastAPI)"
    else
        log_info "Configuring development environment..."
        # Environment configuration
        export GCS_ENV=development
        export MDS_GCS_API_PORT="$DEV_GCS_PORT"
        export MDS_DASHBOARD_PORT="$DEV_REACT_PORT"
        # Node/React environment
        export NODE_ENV=development
        export REACT_APP_ENV=development
        log_success "Development environment configured (Backend: FastAPI)"
    fi
}

get_gcs_server_command() {
    enforce_fastapi_single_worker

    # Set PYTHONPATH to include project root for module imports (functions, src, etc.)
    local python_path="PYTHONPATH='$PROJECT_ROOT:$PROJECT_ROOT/src:\$PYTHONPATH'"
    local uvicorn_bin="$VENV_PATH/bin/uvicorn"
    local gunicorn_bin="$VENV_PATH/bin/gunicorn"

    if [[ "$DEPLOYMENT_MODE" == "production" && ! -x "$gunicorn_bin" ]]; then
        log_error "Gunicorn binary not found at $gunicorn_bin"
        exit 1
    fi

    if [[ "$DEPLOYMENT_MODE" != "production" && ! -x "$uvicorn_bin" ]]; then
        log_error "Uvicorn binary not found at $uvicorn_bin"
        exit 1
    fi

    # FastAPI backend (only option)
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        # Production: single Uvicorn worker behind Gunicorn until backend state is externalized
        local production_access_log_args=""
        if [[ "${ENABLE_GCS_ACCESS_LOGS,,}" == "true" ]]; then
            production_access_log_args=" --access-logfile -"
        fi
        echo "cd '$GCS_SERVER_DIR' && $python_path '$gunicorn_bin' -w $PROD_WSGI_WORKERS -k uvicorn.workers.UvicornWorker -b $PROD_WSGI_BIND --timeout $PROD_GUNICORN_TIMEOUT --log-level $PROD_LOG_LEVEL${production_access_log_args} app_fastapi:app"
    else
        # Development: default to single-process FastAPI to preserve in-memory state.
        local development_access_log_args=" --no-access-log"
        local development_reload_args=""
        if [[ "${ENABLE_GCS_ACCESS_LOGS,,}" == "true" ]]; then
            development_access_log_args=""
        fi
        if backend_reload_enabled; then
            development_reload_args=" --reload"
            log_warn "Backend auto-reload is enabled via MDS_GCS_BACKEND_RELOAD." >&2
            log_warn "Use this only for backend code editing. Telemetry, heartbeat, command-tracker, and other in-memory runtime state may be inconsistent during live operations." >&2
        else
            log_info "Launching development FastAPI without backend auto-reload to preserve operational state." >&2
        fi
        echo "cd '$GCS_SERVER_DIR' && $python_path '$uvicorn_bin' app_fastapi:app --host 0.0.0.0 --port $DEV_GCS_PORT${development_reload_args}${development_access_log_args}"
    fi
}


get_react_command() {
    ensure_nodejs_in_path

    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        if [[ ! -d "$BUILD_DIR" ]]; then
            log_error "Production build directory missing: $BUILD_DIR"
            exit 1
        fi
        if [[ ! -f "$SPA_SERVER_SCRIPT" ]]; then
            log_error "SPA static server helper missing: $SPA_SERVER_SCRIPT"
            exit 1
        fi
        echo "python3 '$SPA_SERVER_SCRIPT' --directory '$BUILD_DIR' --port $DEV_REACT_PORT"
    else
        echo "cd '$REACT_APP_DIR' && '$NPM_BIN_PATH' start"
    fi
}

TMUX_RUNTIME_ENV_VARS=(
    MDS_MODE
    MDS_REPO_URL
    MDS_BRANCH
    MDS_INSTALL_DIR
    MDS_GIT_AUTO_PUSH
    MDS_GIT_AUTH_TOKEN_FILE
    MDS_GIT_AUTH_USERNAME
    MDS_GIT_SSH_KEY_FILE
    MDS_DOCKER_IMAGE
    MDS_SITL_GIT_SYNC
    MDS_SITL_REQUIREMENTS_SYNC
    MDS_SITL_USE_HOST_STARTUP_SCRIPT
    MDS_AUTH_ENABLED
    MDS_API_AUTH_ENABLED
    MDS_AUTH_USERS_FILE
    MDS_API_TOKENS_FILE
    MDS_AUTH_SESSION_SECRET_FILE
    MDS_AUTH_CSRF_SECRET_FILE
    MDS_AUTH_SESSION_TTL_HOURS
    MDS_AUTH_SECURE_COOKIES
    MDS_AUTH_CSRF_ENABLED
    MDS_AUTH_ALLOWED_CIDRS
    MDS_AUTH_TRUSTED_PROXY_CIDRS
    MDS_GCS_SYSTEM_CONFIG
    MDS_SKIP_GCS_SYSTEM_CONFIG
    GCS_ENV
    NODE_ENV
    REACT_APP_ENV
)

sync_tmux_session_environment() {
    local session="$1"
    local var_name=""

    for var_name in "${TMUX_RUNTIME_ENV_VARS[@]}"; do
        if [[ -n "${!var_name+x}" ]]; then
            tmux set-environment -t "$session" "$var_name" "${!var_name}"
        else
            tmux set-environment -t "$session" -u "$var_name" 2>/dev/null || true
        fi
    done
}

build_tmux_runtime_env_prefix() {
    local var_name=""
    local quoted_value=""
    local snippet=""

    for var_name in "${TMUX_RUNTIME_ENV_VARS[@]}"; do
        if [[ -n "${!var_name+x}" ]]; then
            printf -v quoted_value "%q" "${!var_name}"
            snippet+="export ${var_name}=${quoted_value}; "
        else
            snippet+="unset ${var_name}; "
        fi
    done

    printf '%s' "$snippet"
}

tmux_wait_for_pane_ready() {
    local delay="${TMUX_PANE_READY_DELAY_SECONDS:-0.2}"
    sleep "$delay"
}

prepare_react_runtime() {
    if [[ "$RUN_GUI_APP" != "true" ]]; then
        return 0
    fi

    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        if check_build_needed; then
            build_react_app
        else
            log_success "Production React build already up to date."
        fi
    else
        verify_react_setup
    fi
}

start_services_in_tmux() {
    local session="$SESSION_NAME"
    
    # Kill existing session
    if tmux has-session -t "$session" 2>/dev/null; then
        log_warn "Killing existing tmux session: $session"
        tmux kill-session -t "$session"
        sleep 1
    fi
    
    log_info "Creating tmux session: $session (mode: $DEPLOYMENT_MODE)"
    tmux new-session -d -s "$session"
    tmux_wait_for_pane_ready
    tmux set-option -g mouse on
    sync_tmux_session_environment "$session"
    
    local gcs_cmd=""
    local react_cmd=""
    local tmux_env_prefix=""

    prepare_react_runtime

    if [[ "$RUN_GCS_SERVER" == "true" ]]; then
        gcs_cmd=$(get_gcs_server_command)
    fi
    
    if [[ "$RUN_GUI_APP" == "true" ]]; then
        react_cmd=$(get_react_command)
    fi

    tmux_env_prefix="$(build_tmux_runtime_env_prefix)"
    
    if [[ "$COMBINED_VIEW" == "true" ]]; then
        tmux rename-window -t "$session:0" "Services"
        local pane_index=0
        
        if [[ "$RUN_GCS_SERVER" == "true" ]]; then
            tmux send-keys -t "$session:Services.$pane_index" "${tmux_env_prefix}clear && echo 'Starting GCS server (FastAPI) in $DEPLOYMENT_MODE mode...' && $gcs_cmd" C-m
            pane_index=$((pane_index + 1))
        fi
        
        if [[ "$RUN_GUI_APP" == "true" ]]; then
            if [[ $pane_index -gt 0 ]]; then
                tmux split-window -t "$session:Services" -h
                tmux_wait_for_pane_ready
            fi
            tmux send-keys -t "$session:Services.$pane_index" "${tmux_env_prefix}clear && echo 'Starting React app in $DEPLOYMENT_MODE mode...' && $react_cmd" C-m
        fi
        
        if [[ $pane_index -gt 0 ]]; then
            tmux select-layout -t "$session:Services" tiled
        fi
    else
        # Separate windows
        local window_index=0
        
        if [[ "$RUN_GCS_SERVER" == "true" ]]; then
            tmux rename-window -t "$session:0" "GCS-Server"
            tmux send-keys -t "$session:GCS-Server" "${tmux_env_prefix}clear && echo 'Starting GCS server (FastAPI)...' && $gcs_cmd" C-m
            window_index=$((window_index + 1))
        fi
        
        if [[ "$RUN_GUI_APP" == "true" ]]; then
            if [[ $window_index -eq 0 ]]; then
                tmux rename-window -t "$session:0" "React-App"
            else
                tmux new-window -t "$session" -n "React-App"
                tmux_wait_for_pane_ready
            fi
            tmux send-keys -t "$session:React-App" "${tmux_env_prefix}clear && echo 'Starting React app...' && $react_cmd" C-m
        fi
    fi
    
    show_tmux_instructions
    if [[ -t 0 && -t 1 ]]; then
        tmux attach-session -t "$session"
    else
        log_info "No interactive TTY detected. Services are running in tmux session: $session"
    fi
}

start_services_no_tmux() {
    log_info "Starting services without tmux in $DEPLOYMENT_MODE mode..."

    prepare_react_runtime

    if ! command -v gnome-terminal >/dev/null 2>&1; then
        log_error "gnome-terminal is not available. Use tmux mode on headless systems."
        exit 1
    fi

    if [[ "$RUN_GCS_SERVER" == "true" ]]; then
        local gcs_cmd=$(get_gcs_server_command)
        gnome-terminal -- bash -c "echo 'Starting GCS server (FastAPI) in $DEPLOYMENT_MODE mode...' && $gcs_cmd; exec bash"
    fi

    if [[ "$RUN_GUI_APP" == "true" ]]; then
        local react_cmd=$(get_react_command)
        gnome-terminal -- bash -c "echo 'Starting React app in $DEPLOYMENT_MODE mode...' && $react_cmd; exec bash"
    fi

    # Show helpful info for non-tmux mode
    cat << EOF

===============================================================================
  SERVICES STARTED (No-Tmux Mode)
===============================================================================

  Services are running in separate terminal windows.

  USEFUL COMMANDS:
    Check GCS health:  curl http://localhost:$DEV_GCS_PORT/api/v1/system/health
    View status:       $0 --status

  TO STOP SERVICES:
    Close the terminal windows, or find and kill the processes:
      pkill -f "uvicorn app_fastapi"   # Stop GCS server
      pkill -f "npm start"             # Stop React app

  ACCESS:
    Dashboard:  http://localhost:$DEV_REACT_PORT
    API:        http://localhost:$DEV_GCS_PORT
    Health:     http://localhost:$DEV_GCS_PORT/api/v1/system/health

===============================================================================
EOF
}

show_tmux_instructions() {
    cat << EOF

===============================================================================
  TMUX SESSION: $SESSION_NAME
===============================================================================

  NAVIGATION (Prefix: Ctrl+B):
    Switch panes:    Ctrl+B, Arrow keys
    Detach session:  Ctrl+B, then D
    Scroll mode:     Ctrl+B, then [  (q to exit scroll)

  COMMON COMMANDS:
    Reattach:        tmux attach -t $SESSION_NAME
    List sessions:   tmux ls
    Stop services:   tmux kill-session -t $SESSION_NAME

  HEALTH CHECK:
    curl http://localhost:$DEV_GCS_PORT/api/v1/system/health

  STATUS:
    $0 --status

===============================================================================
EOF
}

display_config_summary() {
    enforce_fastapi_single_worker

    cat << EOF

===============================================
  Configuration Summary
===============================================
Deployment Mode: $(echo $DEPLOYMENT_MODE | tr '[:lower:]' '[:upper:]')
Branch: $BRANCH_NAME
GCS Server: $([[ "$RUN_GCS_SERVER" == "true" ]] && echo "ENABLED" || echo "DISABLED")
GUI React App: $([[ "$RUN_GUI_APP" == "true" ]] && echo "ENABLED" || echo "DISABLED")
Tmux: $([[ "$USE_TMUX" == "true" ]] && echo "ENABLED" || echo "DISABLED")
View: $([[ "$COMBINED_VIEW" == "true" ]] && echo "Combined Panes" || echo "Separate Windows")
Force Rebuild: $([[ "$FORCE_REBUILD" == "true" ]] && echo "YES" || echo "NO")
EOF

    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        cat << EOF

PRODUCTION CONFIG:
  - WSGI Workers: $PROD_WSGI_WORKERS
  - Bind Address: $PROD_WSGI_BIND
  - Timeout: $PROD_GUNICORN_TIMEOUT seconds
  - Working Dir: $GCS_SERVER_DIR (FIXED)
  - Build Optimization: ENABLED
EOF
    else
        cat << EOF

DEVELOPMENT CONFIG:
  - React Port: $DEV_REACT_PORT
  - GCS Port: $DEV_GCS_PORT
  - Hot Reload: ENABLED
  - Debug Mode: ENABLED
EOF
    fi

    if [[ "$USE_REAL" == "true" ]]; then
        echo "Runtime Mode: REAL (Hardware) [switching]"
    elif [[ "$USE_SITL" == "true" ]]; then
        echo "Runtime Mode: SITL (Simulation) [switching]"
    else
        echo "Runtime Mode: $(get_current_drone_mode) [current via $(get_runtime_mode_source)]"
    fi

    if [[ -n "$OVERWRITE_IP" ]]; then
        echo "Server IP Override: $OVERWRITE_IP"
    fi

    echo "==============================================="
    echo
}

#########################################
# MAIN EXECUTION
#########################################

# Banner - Use shared banner if available
display_startup_banner() {
    local banner_path="$PARENT_DIR/tools/mds_banner.sh"
    if [[ -f "$banner_path" ]]; then
        source "$banner_path"
        local git_info branch commit git_date
        git_info=$(get_git_info "$PARENT_DIR" 2>/dev/null || echo "unknown|unknown|unknown")
        IFS='|' read -r branch commit git_date <<< "$git_info"
        print_mds_banner "Dashboard Services" "$PROJECT_VERSION" "$branch" "$commit"
    else
        # Fallback banner
        echo ""
        echo ",--.   ,--.,------.   ,---.   "
        echo "|   \`.'   ||  .-.  \\ '   .-'  "
        echo "|  |'.'|  ||  |  \\  :\`.  \`-.  "
        echo "|  |   |  ||  '--'  /.-'    | "
        echo "\`--'   \`--'\`-------' \`-----'  "
        echo ""
        echo "MAVSDK Drone Show - Dashboard Services"
        echo "================================================"
        echo "Version:  $PROJECT_VERSION"
        echo "================================================"
        echo ""
    fi
}

# ===========================================
# STARTUP SUMMARY FUNCTIONS
# ===========================================

print_startup_summary() {
    echo ""
    echo "==============================================================================="
    echo "  MDS GROUND CONTROL STATION - STARTUP SUMMARY"
    echo "==============================================================================="
    echo ""
    printf "  %-20s %s\n" "Mode:" "$(echo $DEPLOYMENT_MODE | tr '[:lower:]' '[:upper:]')"
    printf "  %-20s %s\n" "Backend:" "FastAPI"
    printf "  %-20s %s\n" "Drone Mode:" "$(get_current_drone_mode)"
    printf "  %-20s %s\n" "Session:" "$SESSION_NAME"
    echo ""
    echo "  Services:"
    [[ "$RUN_GCS_SERVER" == "true" ]] && printf "    [x] GCS Server      http://localhost:%s\n" "$DEV_GCS_PORT"
    [[ "$RUN_GUI_APP" == "true" ]] && printf "    [x] React Dashboard http://localhost:%s\n" "$DEV_REACT_PORT"
    echo ""
    echo "==============================================================================="
    echo ""
}

print_ready_message() {
    echo ""
    echo "==============================================================================="
    echo "  SERVICES STARTING"
    echo "==============================================================================="
    echo ""
    echo "  Opening tmux session: $SESSION_NAME"
    echo ""
    echo "  Quick Reference:"
    echo "    Detach:    Ctrl+B, then D"
    echo "    Reattach:  tmux attach -t $SESSION_NAME"
    echo "    Stop:      tmux kill-session -t $SESSION_NAME"
    echo ""
    echo "  Health Check:"
    echo "    curl http://localhost:$DEV_GCS_PORT/api/v1/system/health"
    echo ""
    echo "==============================================================================="
    sleep 1
}

# ===========================================
# MAIN EXECUTION
# ===========================================

display_startup_banner

# Parse arguments and initialize
parse_arguments "$@"

# Load GCS system configuration if available
load_gcs_system_config 2>/dev/null || true

if [[ "$STATUS_ONLY" == "true" ]]; then
    show_current_status
    exit 0
fi

# Handle --check option (run checks only, don't start services)
if [[ "$CHECK_ONLY" == "true" ]]; then
    run_configuration_check
    exit 0
fi

echo ""
echo "-----------------------------------------------------------------------"
echo "  SYSTEM CHECKS"
echo "-----------------------------------------------------------------------"

# Quick essential checks
check_command_installed "tmux" "tmux"
check_command_installed "lsof" "lsof"

# GCS initialization check
check_gcs_initialized

echo ""
echo "-----------------------------------------------------------------------"
echo "  CONFIGURATION"
echo "-----------------------------------------------------------------------"

# Execute setup sequence (minimal output)
apply_requested_runtime_mode
update_repository
if [[ "$RUN_GUI_APP" == "true" ]]; then
    ensure_nodejs_in_path
fi
configure_react_version_env
load_virtualenv
validate_backend
check_python_dependencies
handle_env_file
setup_production_environment

echo ""
echo "-----------------------------------------------------------------------"
echo "  PORT MANAGEMENT"
echo "-----------------------------------------------------------------------"

if [[ "$RUN_GCS_SERVER" == "true" ]]; then
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        prod_port=$(echo "$PROD_WSGI_BIND" | cut -d':' -f2)
        check_and_kill_port "$prod_port"
    else
        check_and_kill_port "$DEV_GCS_PORT"
    fi
fi

if [[ "$RUN_GUI_APP" == "true" ]]; then
    check_and_kill_port "$DEV_REACT_PORT"
fi

# Print startup summary
print_startup_summary
print_ready_message

# Start services
if [[ "$USE_TMUX" == "true" ]]; then
    start_services_in_tmux
else
    start_services_no_tmux
fi
