#!/bin/bash

#########################################
# Final Production-Ready Drone Services Launcher
#
# Project: Drone Show GCS Server
# Version: Production Final
# 
# CRITICAL FIXES APPLIED:
# - Flask WSGI module-level app object created
# - Absolute path resolution for any execution directory
# - Clean bash commands (NO Unicode/emojis)
# - Robust virtual environment handling
# - Production-grade error handling
#
# Usage: ./linux_dashboard_start.sh [OPTIONS]
#########################################

set -euo pipefail  # Strict error handling

# ===========================================
# CONFIGURATION
# ===========================================
DEFAULT_MODE="development"
PROD_WSGI_WORKERS=4
PROD_WSGI_BIND="0.0.0.0:5000"
PROD_GUNICORN_TIMEOUT=120
PROD_LOG_LEVEL="info"
DEV_REACT_PORT=3030
DEV_FLASK_PORT=5000
SESSION_NAME="DroneServices"

# ===========================================
# PATH RESOLUTION (ABSOLUTE PATHS ONLY)
# ===========================================
SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname "$SCRIPT_PATH")"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$PARENT_DIR")"

# Detect correct paths regardless of execution directory
if [[ "$SCRIPT_DIR" == *"/app" ]]; then
    # Executed as app/linux_dashboard_start.sh
    REACT_APP_DIR="$SCRIPT_DIR/dashboard/drone-dashboard"
    GCS_SERVER_DIR="$PARENT_DIR/gcs-server"
    VENV_PATH="$PARENT_DIR/venv"
else
    # Executed from project root
    REACT_APP_DIR="$SCRIPT_DIR/dashboard/drone-dashboard"
    GCS_SERVER_DIR="$SCRIPT_DIR/gcs-server"
    VENV_PATH="$SCRIPT_DIR/venv"
fi

# Final path validation
if [[ ! -d "$GCS_SERVER_DIR" ]]; then
    echo "ERROR: GCS server directory not found at $GCS_SERVER_DIR"
    echo "Script location: $SCRIPT_DIR"
    echo "Parent directory: $PARENT_DIR"
    exit 1
fi

ENV_FILE_PATH="$REACT_APP_DIR/.env"
BUILD_DIR="$REACT_APP_DIR/build"
REAL_MODE_FILE="$GCS_SERVER_DIR/real.mode"
UPDATE_SCRIPT_PATH="$PROJECT_ROOT/tools/update_repo_ssh.sh"

# ===========================================
# VARIABLES
# ===========================================
DEPLOYMENT_MODE="$DEFAULT_MODE"
FORCE_REBUILD=false
RUN_GCS_SERVER=true
RUN_GUI_APP=true
USE_TMUX=true
COMBINED_VIEW=true
USE_SITL=false
USE_REAL=false
OVERWRITE_IP=""
# Repository Configuration: Environment Variable Support (MDS v3.1+)
# This script now supports custom branches via environment variables
# Default behavior unchanged for normal users
BRANCH_NAME="${MDS_BRANCH:-main}"

# ===========================================
# LOGGING FUNCTIONS
# ===========================================
log_info() { echo "[INFO] $1"; }
log_warn() { echo "[WARN] $1"; }
log_error() { echo "[ERROR] $1" >&2; }
log_success() { echo "[SUCCESS] $1"; }

# ===========================================
# UTILITY FUNCTIONS
# ===========================================
display_usage() {
    cat << EOF
Production-Ready Drone Services Launcher

USAGE: $0 [OPTIONS]

MODE OPTIONS:
  --prod                : Production mode (optimized builds, WSGI server)
  --dev                 : Development mode (hot reload, debug server)
  --force-rebuild       : Force rebuild even if no changes detected

SERVICE OPTIONS:
  -g                    : Do NOT run GCS Server (default: enabled)
  -u                    : Do NOT run GUI React App (default: enabled)
  -n                    : Do NOT use tmux (default: uses tmux)
  -s                    : Run components in separate windows (default: combined)

DRONE MODE OPTIONS:
  --sitl                : Switch to simulation mode
  --real                : Switch to real drone mode

NETWORK OPTIONS:
  --overwrite-ip <IP>   : Override server IP in environment

REPOSITORY OPTIONS:
  -b <branch>           : Specify git branch (default: from MDS_BRANCH env var or main)

HELP:
  -h                    : Display this help message

EXAMPLES:
  Production deploy:     $0 --prod --real
  Development with SITL: $0 --dev --sitl --force-rebuild
  Custom IP production:  $0 --prod --overwrite-ip 192.168.1.100
EOF
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prod|--production) DEPLOYMENT_MODE="production"; shift ;;
            --dev|--development) DEPLOYMENT_MODE="development"; shift ;;
            --force-rebuild) FORCE_REBUILD=true; shift ;;
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
            -h) display_usage; exit 0 ;;
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
        log_warn "Port $port is in use. Killing processes: $pids"
        echo "$pids" | xargs -r kill -9
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

handle_real_mode_file() {
    if [[ "$USE_REAL" == "true" ]]; then
        log_info "Switching to Real Mode..."
        touch "$REAL_MODE_FILE"
        log_success "Real mode file created."
    elif [[ "$USE_SITL" == "true" ]]; then
        log_info "Switching to Simulation Mode..."
        if [[ -f "$REAL_MODE_FILE" ]]; then
            rm "$REAL_MODE_FILE"
            log_success "Real mode file removed."
        else
            log_info "Already in Simulation Mode."
        fi
    else
        log_info "No mode switch requested. Current mode preserved."
    fi
}

update_repository() {
    if [[ -n "$BRANCH_NAME" && -f "$UPDATE_SCRIPT_PATH" ]]; then
        log_info "Updating repository to branch: $BRANCH_NAME"
        bash "$UPDATE_SCRIPT_PATH" -b "$BRANCH_NAME"
        if [[ $? -eq 0 ]]; then
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
    
    if [[ -f "$ENV_FILE_PATH" ]]; then
        log_success ".env file found."
        if [[ -n "$OVERWRITE_IP" ]]; then
            log_info "Overwriting server IP to: $OVERWRITE_IP"
            cp "$ENV_FILE_PATH" "$ENV_FILE_PATH.bak"
            sed -i "s|^REACT_APP_SERVER_URL=.*|REACT_APP_SERVER_URL=http://$OVERWRITE_IP|" "$ENV_FILE_PATH"
            log_success "Server IP updated and backup created."
        fi
    else
        log_warn ".env file not found. Creating new one..."
        local server_ip="${OVERWRITE_IP:-}"
        if [[ -z "$server_ip" ]]; then
            echo -n "Enter server IP (e.g., 192.168.1.100): "
            read server_ip
        fi
        
        if [[ ! $server_ip =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            log_error "Invalid IP address format."
            exit 1
        fi
        
        mkdir -p "$(dirname "$ENV_FILE_PATH")"
        cat > "$ENV_FILE_PATH" << EOF
REACT_APP_SERVER_URL=http://$server_ip
REACT_APP_FLASK_PORT=5000
DRONE_APP_FLASK_PORT=7070
GENERATE_SOURCEMAP=false
EOF
        log_success ".env file created with IP: $server_ip"
    fi
}

check_build_needed() {
    if [[ "$FORCE_REBUILD" == "true" ]]; then
        log_info "Force rebuild requested."
        return 0
    fi
    
    if [[ ! -d "$BUILD_DIR" ]]; then
        log_info "No build directory found. Build needed."
        return 0
    fi
    
    local package_json="$REACT_APP_DIR/package.json"
    if [[ "$package_json" -nt "$BUILD_DIR" ]]; then
        log_info "Package.json updated. Build needed."
        return 0
    fi
    
    local src_dir="$REACT_APP_DIR/src"
    if [[ -d "$src_dir" ]]; then
        local newest_src=$(find "$src_dir" -type f -newer "$BUILD_DIR" 2>/dev/null | head -1)
        if [[ -n "$newest_src" ]]; then
            log_info "Source files updated. Build needed."
            return 0
        fi
    fi
    
    log_info "Build is up-to-date. Skipping rebuild."
    return 1
}

build_react_app() {
    log_info "Building React application for production..."
    
    cd "$REACT_APP_DIR" || {
        log_error "Failed to navigate to React app directory: $REACT_APP_DIR"
        exit 1
    }
    
    if [[ ! -d "node_modules" || "$REACT_APP_DIR/package.json" -nt "node_modules" ]]; then
        log_info "Installing Node.js dependencies..."
        npm ci --only=production
        if [[ $? -ne 0 ]]; then
            log_error "Failed to install dependencies."
            exit 1
        fi
    fi
    
    log_info "Building optimized production bundle..."
    npm run build
    if [[ $? -ne 0 ]]; then
        log_error "Build failed."
        exit 1
    fi
    
    log_success "React build completed successfully."
}

verify_react_setup() {
    log_info "Verifying React setup..."
    
    if [[ ! -f "$REACT_APP_DIR/package.json" ]]; then
        log_error "package.json not found at: $REACT_APP_DIR"
        exit 1
    fi
    
    if [[ ! -d "$REACT_APP_DIR/node_modules" ]]; then
        log_info "Installing missing dependencies..."
        cd "$REACT_APP_DIR" && npm install
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
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        log_info "Configuring production environment..."
        export FLASK_ENV=production
        export NODE_ENV=production
        export REACT_APP_ENV=production
        install_production_dependencies
        log_success "Production environment configured."
    else
        log_info "Configuring development environment..."
        export FLASK_ENV=development
        export FLASK_DEBUG=1
        export NODE_ENV=development
        export REACT_APP_ENV=development
        log_success "Development environment configured."
    fi
}

get_flask_command() {
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        echo "cd '$GCS_SERVER_DIR' && gunicorn -w $PROD_WSGI_WORKERS -b $PROD_WSGI_BIND --timeout $PROD_GUNICORN_TIMEOUT --log-level $PROD_LOG_LEVEL app:app"
    else
        echo "cd '$GCS_SERVER_DIR' && python app.py"
    fi
}

get_react_command() {
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        if check_build_needed; then
            build_react_app
        fi
        echo "cd '$BUILD_DIR' && python3 -m http.server $DEV_REACT_PORT"
    else
        verify_react_setup
        echo "cd '$REACT_APP_DIR' && npm start"
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
    tmux set-option -g mouse on
    
    local gcs_cmd=""
    local react_cmd=""
    
    if [[ "$RUN_GCS_SERVER" == "true" ]]; then
        gcs_cmd=$(get_flask_command)
    fi
    
    if [[ "$RUN_GUI_APP" == "true" ]]; then
        react_cmd=$(get_react_command)
    fi
    
    if [[ "$COMBINED_VIEW" == "true" ]]; then
        tmux rename-window -t "$session:0" "Services"
        local pane_index=0
        
        if [[ "$RUN_GCS_SERVER" == "true" ]]; then
            tmux send-keys -t "$session:Services.$pane_index" "clear && echo 'Starting Flask server in $DEPLOYMENT_MODE mode...' && $gcs_cmd" C-m
            pane_index=$((pane_index + 1))
        fi
        
        if [[ "$RUN_GUI_APP" == "true" ]]; then
            if [[ $pane_index -gt 0 ]]; then
                tmux split-window -t "$session:Services" -h
            fi
            tmux send-keys -t "$session:Services.$pane_index" "clear && echo 'Starting React app in $DEPLOYMENT_MODE mode...' && $react_cmd" C-m
        fi
        
        if [[ $pane_index -gt 0 ]]; then
            tmux select-layout -t "$session:Services" tiled
        fi
    else
        # Separate windows
        local window_index=0
        
        if [[ "$RUN_GCS_SERVER" == "true" ]]; then
            tmux rename-window -t "$session:0" "Flask-Server"
            tmux send-keys -t "$session:Flask-Server" "clear && echo 'Starting Flask server...' && $gcs_cmd" C-m
            window_index=$((window_index + 1))
        fi
        
        if [[ "$RUN_GUI_APP" == "true" ]]; then
            if [[ $window_index -eq 0 ]]; then
                tmux rename-window -t "$session:0" "React-App"
            else
                tmux new-window -t "$session" -n "React-App"
            fi
            tmux send-keys -t "$session:React-App" "clear && echo 'Starting React app...' && $react_cmd" C-m
        fi
    fi
    
    show_tmux_instructions
    tmux attach-session -t "$session"
}

start_services_no_tmux() {
    log_info "Starting services without tmux in $DEPLOYMENT_MODE mode..."
    
    if [[ "$RUN_GCS_SERVER" == "true" ]]; then
        local gcs_cmd=$(get_flask_command)
        gnome-terminal -- bash -c "echo 'Starting Flask server in $DEPLOYMENT_MODE mode...' && $gcs_cmd; exec bash"
    fi
    
    if [[ "$RUN_GUI_APP" == "true" ]]; then
        local react_cmd=$(get_react_command)
        gnome-terminal -- bash -c "echo 'Starting React app in $DEPLOYMENT_MODE mode...' && $react_cmd; exec bash"
    fi
}

show_tmux_instructions() {
    cat << EOF

===============================================
  tmux Session Guide (Mode: $DEPLOYMENT_MODE)
===============================================
Prefix key (Ctrl+B), then:
EOF

    if [[ "$COMBINED_VIEW" == "true" ]]; then
        echo "  - Switch panes: Arrow keys"
        echo "  - Resize panes: Hold Ctrl+B + Arrow key"
    else
        echo "  - Switch windows: Number keys (1, 2, etc.)"
    fi

    cat << EOF
  - Detach session: Ctrl+B, then D
  - Reattach: tmux attach -t $SESSION_NAME
  - Kill session: tmux kill-session -t $SESSION_NAME

MODE INFORMATION:
EOF

    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        cat << EOF
  - React: Serving optimized build files
  - Flask: Running with gunicorn WSGI server
  - Working Dir: $GCS_SERVER_DIR (FIXED for imports)
  - Logging: Production logging enabled
EOF
    else
        cat << EOF
  - React: Hot reload enabled on port $DEV_REACT_PORT
  - Flask: Debug mode with auto-restart
  - Logging: Verbose debug logging enabled
EOF
    fi

    echo "==============================================="
    echo
}

display_config_summary() {
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
  - Flask Port: $DEV_FLASK_PORT
  - Hot Reload: ENABLED
  - Debug Mode: ENABLED
EOF
    fi

    if [[ "$USE_REAL" == "true" ]]; then
        echo "Drone Mode: Real Hardware"
    elif [[ "$USE_SITL" == "true" ]]; then
        echo "Drone Mode: Simulation (SITL)"
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

# Banner
cat << "EOF"

  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 

                              PRODUCTION READY DRONE SERVICES

EOF

# Parse arguments and initialize
parse_arguments "$@"

log_info "Initializing Drone Services System..."
display_config_summary

# System checks
check_command_installed "tmux" "tmux"
check_command_installed "lsof" "lsof"

# Execute setup sequence
handle_real_mode_file
update_repository
load_virtualenv
handle_env_file  
setup_production_environment

# Port management
log_info "Checking ports for $DEPLOYMENT_MODE mode..."
if [[ "$RUN_GCS_SERVER" == "true" ]]; then
    if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
        prod_port=$(echo "$PROD_WSGI_BIND" | cut -d':' -f2)
        check_and_kill_port "$prod_port"
    else
        check_and_kill_port "$DEV_FLASK_PORT"
    fi
fi

if [[ "$RUN_GUI_APP" == "true" ]]; then
    check_and_kill_port "$DEV_REACT_PORT"
fi

# Start services
if [[ "$USE_TMUX" == "true" ]]; then
    start_services_in_tmux
else
    start_services_no_tmux
fi

log_success "Drone Services System Started Successfully!"
log_info "All services running in $(echo $DEPLOYMENT_MODE | tr '[:lower:]' '[:upper:]') mode"

if [[ "$DEPLOYMENT_MODE" == "production" ]]; then
    log_info "Production optimizations active"
    log_info "Flask working directory: $GCS_SERVER_DIR (FIXED)"
else
    log_info "Development mode with hot reloading active"
fi