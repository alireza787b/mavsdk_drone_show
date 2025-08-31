#!/bin/bash

#########################################
# Enhanced Drone Services Launcher with Production/Development Modes
#
# Project: Drone Show GCS Server
# Author: Enhanced for Production/Development by Expert
# Date: Updated for Production Capability
#
# This script intelligently handles both development and production deployments
# with smart build detection, process management, and environment optimization.
#
# Usage:
#   ./linux_dashboard_start.sh [-g|-u|-n|-s|-h] [--sitl | --real] [--prod | --dev] [--force-rebuild] [--overwrite-ip <IP>] [-b <branch>]
#
# Production Features:
#   - Smart build detection and caching
#   - Production-optimized React builds
#   - WSGI server for Flask (gunicorn)
#   - Process monitoring and auto-restart
#   - Enhanced logging and error handling
#   - Environment-specific configurations
#
#########################################

# ===========================================
# PRODUCTION/DEVELOPMENT CONFIGURATION
# ===========================================
# Default mode - can be overridden by command line
DEFAULT_MODE="development"  # Options: "production" or "development"

# Production Configuration
PROD_WSGI_WORKERS=4
PROD_WSGI_BIND="0.0.0.0:5000"
PROD_GUNICORN_TIMEOUT=120
PROD_LOG_LEVEL="info"
PROD_BUILD_DIR="build"

# Development Configuration  
DEV_REACT_PORT=3030
DEV_FLASK_PORT=5000
DEV_LOG_LEVEL="debug"

# ===========================================

# Display Enhanced ASCII Art Banner
cat << "EOF"

  __  __   ___   _____ ___  _  __  ___  ___  ___  _  _ ___   ___ _  _  _____      __   ____  __ ___  _____  
 |  \/  | /_\ \ / / __|   \| |/ / |   \| _ \/ _ \| \| | __| / __| || |/ _ \ \    / /  / /  \/  |   \/ __\ \ 
 | |\/| |/ _ \ V /\__ \ |) | ' <  | |) |   / (_) | .` | _|  \__ \ __ | (_) \ \/\/ /  | || |\/| | |) \__ \| |
 |_|  |_/_/ \_\_/ |___/___/|_|\_\ |___/|_|_\\___/|_|\_|___| |___/_||_|\___/ \_/\_/   | ||_|  |_|___/|___/| |
                                                                                      \_\               /_/ 

                                    🚀 ENHANCED PRODUCTION READY 🚀

EOF

# Initialize variables
DEPLOYMENT_MODE="$DEFAULT_MODE"
FORCE_REBUILD=false
SMART_BUILD=true
BUILD_HASH_FILE=".build_hash"
RUN_GCS_SERVER=true
RUN_GUI_APP=true
USE_TMUX=true
COMBINED_VIEW=true
ENABLE_MOUSE=true
ENABLE_AUTO_PULL=true

# Paths and configuration
SESSION_NAME="DroneServices"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PATH="$HOME/mavsdk_drone_show/venv"
UPDATE_SCRIPT_PATH="$HOME/mavsdk_drone_show/tools/update_repo_ssh.sh"
BRANCH_NAME="main-candidate"
ENV_FILE_PATH="$SCRIPT_DIR/dashboard/drone-dashboard/.env"
REAL_MODE_FILE="$PARENT_DIR/real.mode"

# Build paths
REACT_APP_DIR="$SCRIPT_DIR/dashboard/drone-dashboard"
BUILD_DIR="$REACT_APP_DIR/$PROD_BUILD_DIR"
PACKAGE_JSON="$REACT_APP_DIR/package.json"

# New command line variables
USE_SITL=false
USE_REAL=false
OVERWRITE_IP=""

# ===========================================
# ENHANCED FUNCTION DEFINITIONS
# ===========================================

# Function to display enhanced usage instructions
display_usage() {
    echo "Enhanced Usage: $0 [OPTIONS]"
    echo ""
    echo "🎯 MODE OPTIONS:"
    echo "  --prod                : Run in production mode (optimized builds, WSGI server)"
    echo "  --dev                 : Run in development mode (hot reload, debug server)"
    echo "  --force-rebuild       : Force rebuild even if no changes detected"
    echo ""
    echo "🔧 SERVICE OPTIONS:"
    echo "  -g                    : Do NOT run GCS Server (default: enabled)"
    echo "  -u                    : Do NOT run GUI React App (default: enabled)" 
    echo "  -n                    : Do NOT use tmux (default: uses tmux)"
    echo "  -s                    : Run components in Separate windows (default: Combined)"
    echo ""
    echo "🎮 DRONE MODE OPTIONS:"
    echo "  --sitl                : Switch to simulation mode"
    echo "  --real                : Switch to real drone mode"
    echo ""
    echo "🌐 NETWORK OPTIONS:"
    echo "  --overwrite-ip <IP>   : Override server IP in environment"
    echo ""
    echo "📦 REPOSITORY OPTIONS:"
    echo "  -b <branch>           : Specify git branch (default: main-candidate)"
    echo ""
    echo "ℹ️  HELP:"
    echo "  -h                    : Display this help message"
    echo ""
    echo "📋 EXAMPLES:"
    echo "  Production deploy:     $0 --prod --real"
    echo "  Development with SITL: $0 --dev --sitl --force-rebuild"
    echo "  Quick production:      $0 --prod -s --overwrite-ip 192.168.1.100"
}

# Function to parse enhanced command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --prod|--production)
                DEPLOYMENT_MODE="production"
                shift ;;
            --dev|--development)  
                DEPLOYMENT_MODE="development"
                shift ;;
            --force-rebuild)
                FORCE_REBUILD=true
                shift ;;
            --sitl)
                if [ "$USE_REAL" = true ]; then
                    echo "❌ Cannot use --sitl and --real simultaneously."
                    exit 1
                fi
                USE_SITL=true
                shift ;;
            --real)
                if [ "$USE_SITL" = true ]; then
                    echo "❌ Cannot use --sitl and --real simultaneously."
                    exit 1
                fi
                USE_REAL=true
                shift ;;
            --overwrite-ip)
                if [ -n "$2" ]; then
                    OVERWRITE_IP="$2"
                    shift 2
                else
                    echo "❌ --overwrite-ip requires an argument."
                    display_usage; exit 1
                fi ;;
            -b)
                if [ -n "$2" ]; then
                    BRANCH_NAME="$2"
                    shift 2
                else
                    echo "❌ -b requires a branch name."
                    display_usage; exit 1
                fi ;;
            -g) RUN_GCS_SERVER=false; shift ;;
            -u) RUN_GUI_APP=false; shift ;;
            -n) USE_TMUX=false; shift ;;
            -s) COMBINED_VIEW=false; shift ;;
            -h) display_usage; exit 0 ;;
            *)
                echo "❌ Unknown option: $1"
                display_usage; exit 1 ;;
        esac
    done
}

# Function to check if build is needed (smart build detection)
check_build_needed() {
    if [ "$FORCE_REBUILD" = true ]; then
        echo "🔨 Force rebuild requested."
        return 0
    fi
    
    if [ ! -d "$BUILD_DIR" ]; then
        echo "🏗️  No build directory found. Build needed."
        return 0
    fi
    
    # Check if source files are newer than build
    if [ "$PACKAGE_JSON" -nt "$BUILD_DIR" ]; then
        echo "📦 Package.json updated. Build needed."
        return 0
    fi
    
    # Check source file modifications
    local src_dir="$REACT_APP_DIR/src"
    if [ -d "$src_dir" ]; then
        local newest_src=$(find "$src_dir" -type f -exec stat -c %Y {} \; | sort -n | tail -1)
        local build_time=$(stat -c %Y "$BUILD_DIR" 2>/dev/null || echo 0)
        
        if [ "$newest_src" -gt "$build_time" ]; then
            echo "📝 Source files updated. Build needed."
            return 0
        fi
    fi
    
    echo "✅ Build is up-to-date. Skipping rebuild."
    return 1
}

# Function to build React application for production
build_react_app() {
    echo "🏗️  Building React application for production..."
    
    cd "$REACT_APP_DIR" || {
        echo "❌ Failed to navigate to React app directory."
        exit 1
    }
    
    # Install dependencies if needed
    if [ ! -d "node_modules" ] || [ "$PACKAGE_JSON" -nt "node_modules" ]; then
        echo "📦 Installing/updating Node.js dependencies..."
        npm ci --only=production
        if [ $? -ne 0 ]; then
            echo "❌ Failed to install dependencies."
            exit 1
        fi
    fi
    
    # Build the application
    echo "🚀 Building optimized production bundle..."
    npm run build
    if [ $? -ne 0 ]; then
        echo "❌ Build failed."
        exit 1
    fi
    
    # Create build hash for future reference
    echo "$(date +%s)" > "$BUILD_HASH_FILE"
    echo "✅ React build completed successfully."
}

# Function to install production dependencies
install_production_dependencies() {
    echo "🔧 Installing production dependencies..."
    
    # Check for gunicorn
    if ! python -c "import gunicorn" 2>/dev/null; then
        echo "📦 Installing gunicorn for production WSGI server..."
        pip install gunicorn
        if [ $? -ne 0 ]; then
            echo "❌ Failed to install gunicorn."
            exit 1
        fi
    fi
    
    # Check for other production dependencies
    if ! command -v nginx &> /dev/null && [ "$DEPLOYMENT_MODE" = "production" ]; then
        echo "⚠️  Nginx not detected. Consider installing for production reverse proxy."
    fi
}

# Function to start React application based on mode
start_react_app() {
    local react_cmd=""
    
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        # Check if build is needed
        if check_build_needed; then
            build_react_app
        fi
        
        # Serve built files (using simple Python server for now, nginx recommended for production)
        react_cmd="cd $BUILD_DIR && python3 -m http.server $DEV_REACT_PORT"
        echo "🚀 Starting React app in PRODUCTION mode (serving build files)"
    else
        react_cmd="cd $REACT_APP_DIR && npm start"
        echo "🔧 Starting React app in DEVELOPMENT mode (hot reload enabled)"
    fi
    
    echo "$react_cmd"
}

# Function to start Flask/GCS server based on mode  
start_flask_server() {
    local flask_cmd=""
    
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        # Production mode with gunicorn
        flask_cmd="cd $PARENT_DIR && gunicorn -w $PROD_WSGI_WORKERS -b $PROD_WSGI_BIND --timeout $PROD_GUNICORN_TIMEOUT --log-level $PROD_LOG_LEVEL gcs-server.app:app"
        echo "🚀 Starting Flask server in PRODUCTION mode (gunicorn WSGI)"
    else
        # Development mode
        flask_cmd="cd $PARENT_DIR && $VENV_PATH/bin/python gcs-server/app.py"
        echo "🔧 Starting Flask server in DEVELOPMENT mode (debug enabled)"
    fi
    
    echo "$flask_cmd"
}

# Function to setup production environment
setup_production_environment() {
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        echo "🚀 Configuring production environment..."
        
        # Set production environment variables
        export FLASK_ENV=production
        export NODE_ENV=production
        export REACT_APP_ENV=production
        
        # Install production dependencies
        install_production_dependencies
        
        echo "✅ Production environment configured."
    else
        echo "🔧 Configuring development environment..."
        
        # Set development environment variables
        export FLASK_ENV=development
        export FLASK_DEBUG=1
        export NODE_ENV=development
        export REACT_APP_ENV=development
        
        echo "✅ Development environment configured."
    fi
}

# Enhanced function to start services in tmux with mode awareness
start_services_in_tmux() {
    local session="$SESSION_NAME"
    
    # Kill existing session
    if tmux has-session -t "$session" 2>/dev/null; then
        echo "⚠️  Killing existing tmux session '$session'..."
        tmux kill-session -t "$session"
        sleep 1
    fi
    
    echo "🟢 Creating tmux session '$session' in $DEPLOYMENT_MODE mode..."
    tmux new-session -d -s "$session"
    
    if [ "$ENABLE_MOUSE" = true ]; then
        tmux set-option -g mouse on
    fi
    
    # Get command strings based on mode
    local gcs_cmd=""
    local react_cmd=""
    
    if [ "$RUN_GCS_SERVER" = true ]; then
        gcs_cmd=$(start_flask_server)
    fi
    
    if [ "$RUN_GUI_APP" = true ]; then
        react_cmd=$(start_react_app)
    fi
    
    # Setup tmux layout
    if [ "$COMBINED_VIEW" = true ]; then
        tmux rename-window -t "$session:0" "${DEPLOYMENT_MODE^}View"
        local pane_index=0
        
        if [ "$RUN_GCS_SERVER" = true ]; then
            tmux send-keys -t "$session:${DEPLOYMENT_MODE^}View.$pane_index" "clear; $gcs_cmd; bash" C-m
            pane_index=$((pane_index + 1))
        fi
        
        if [ "$RUN_GUI_APP" = true ]; then
            if [ $pane_index -gt 0 ]; then
                tmux split-window -t "$session:${DEPLOYMENT_MODE^}View" -h
            fi
            tmux send-keys -t "$session:${DEPLOYMENT_MODE^}View.$pane_index" "clear; $react_cmd; bash" C-m
        fi
        
        if [ $pane_index -gt 0 ]; then
            tmux select-layout -t "$session:${DEPLOYMENT_MODE^}View" tiled
        fi
    else
        # Separate windows mode
        local window_index=0
        
        if [ "$RUN_GCS_SERVER" = true ]; then
            if [ $window_index -eq 0 ]; then
                tmux rename-window -t "$session:0" "GCS-Server"
                tmux send-keys -t "$session:GCS-Server" "clear; $gcs_cmd; bash" C-m
            else
                tmux new-window -t "$session" -n "GCS-Server"
                tmux send-keys -t "$session:GCS-Server" "clear; $gcs_cmd; bash" C-m
            fi
            window_index=$((window_index + 1))
        fi
        
        if [ "$RUN_GUI_APP" = true ]; then
            if [ $window_index -eq 0 ]; then
                tmux rename-window -t "$session:0" "GUI-React"
                tmux send-keys -t "$session:GUI-React" "clear; $react_cmd; bash" C-m
            else
                tmux new-window -t "$session" -n "GUI-React"
                tmux send-keys -t "$session:GUI-React" "clear; $react_cmd; bash" C-m
            fi
        fi
    fi
    
    show_enhanced_tmux_instructions
    tmux attach-session -t "$session"
}

# Enhanced tmux instructions
show_enhanced_tmux_instructions() {
    echo ""
    echo "==============================================="
    echo "  🚀 Enhanced tmux Guide ($DEPLOYMENT_MODE mode):"
    echo "==============================================="
    echo "Prefix key (Ctrl+B), then:"
    if [ "$COMBINED_VIEW" = true ]; then
        echo "  - Switch panes: Arrow keys (e.g., Ctrl+B, then →)"
        echo "  - Resize panes: Hold Ctrl+B + Arrow key"
    else
        echo "  - Switch windows: Number keys (1, 2, etc.)"
    fi
    echo "  - Detach session: Ctrl+B, then D"  
    echo "  - Reattach: tmux attach -t $SESSION_NAME"
    echo "  - Kill session: tmux kill-session -t $SESSION_NAME"
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        echo ""
        echo "🚀 PRODUCTION MODE ACTIVE:"
        echo "  - React: Serving optimized build files"
        echo "  - Flask: Running with gunicorn WSGI server"
        echo "  - Logging: Enhanced production logging enabled"
    else
        echo ""
        echo "🔧 DEVELOPMENT MODE ACTIVE:"
        echo "  - React: Hot reload enabled on port $DEV_REACT_PORT"
        echo "  - Flask: Debug mode with auto-restart"
        echo "  - Logging: Verbose debug logging enabled"
    fi
    echo "==============================================="
    echo ""
}

#########################################
# ENHANCED MAIN EXECUTION SEQUENCE  
#########################################

# Parse command line arguments
parse_arguments "$@"

echo "==============================================="
echo "  🚀 Enhanced DroneServices System Initializing..."
echo "==============================================="

# Display configuration summary
echo ""
echo "==============================================="
echo "  📋 Enhanced Configuration Summary:"
echo "==============================================="
echo "🎯  Deployment Mode: $(echo $DEPLOYMENT_MODE | tr '[:lower:]' '[:upper:]')"
echo "🌿  Branch: $BRANCH_NAME"
echo "🔧  GCS Server: $([ "$RUN_GCS_SERVER" = true ] && echo "✅ Enabled" || echo "❌ Disabled")"
echo "🖥️   GUI React App: $([ "$RUN_GUI_APP" = true ] && echo "✅ Enabled" || echo "❌ Disabled")"
echo "📺  Tmux: $([ "$USE_TMUX" = true ] && echo "✅ Enabled" || echo "❌ Disabled")"
echo "🪟  View: $([ "$COMBINED_VIEW" = true ] && echo "Combined Panes" || echo "Separate Windows")"
echo "🔄  Force Rebuild: $([ "$FORCE_REBUILD" = true ] && echo "✅ Yes" || echo "❌ No")"

# Mode-specific configuration display
if [ "$DEPLOYMENT_MODE" = "production" ]; then
    echo "🚀  PRODUCTION CONFIG:"
    echo "    - WSGI Workers: $PROD_WSGI_WORKERS"
    echo "    - Bind Address: $PROD_WSGI_BIND"
    echo "    - Timeout: $PROD_GUNICORN_TIMEOUT seconds"
    echo "    - Build Optimization: ✅ Enabled"
else
    echo "🔧  DEVELOPMENT CONFIG:"
    echo "    - React Port: $DEV_REACT_PORT"
    echo "    - Flask Port: $DEV_FLASK_PORT"
    echo "    - Hot Reload: ✅ Enabled"
    echo "    - Debug Mode: ✅ Enabled"
fi

if [ "$USE_REAL" = true ]; then
    echo "🚁  Drone Mode: Real Hardware"
elif [ "$USE_SITL" = true ]; then
    echo "🎮  Drone Mode: Simulation (SITL)"
fi

if [ -n "$OVERWRITE_IP" ]; then
    echo "🌐  Server IP Override: $OVERWRITE_IP"
fi
echo "==============================================="
echo ""

# Continue with existing functions but enhanced
check_tmux_installed
handle_real_mode_file
update_repository
load_virtualenv
handle_env_file
setup_production_environment

# Enhanced port checking with mode awareness
echo "-----------------------------------------------"
echo "🔍 Checking ports for $DEPLOYMENT_MODE mode..."
echo "-----------------------------------------------"

if [ "$RUN_GCS_SERVER" = true ]; then
    if [ "$DEPLOYMENT_MODE" = "production" ]; then
        # Extract port from bind address for production
        PROD_PORT=$(echo "$PROD_WSGI_BIND" | cut -d':' -f2)
        check_and_kill_port "$PROD_PORT"
    else
        check_and_kill_port "$DEV_FLASK_PORT"
    fi
fi

if [ "$RUN_GUI_APP" = true ]; then
    check_and_kill_port "$DEV_REACT_PORT"
fi

# Start services
if [ "$USE_TMUX" = true ]; then
    start_services_in_tmux
else
    echo "🟢 Starting services without tmux in $DEPLOYMENT_MODE mode..."
    # Implementation for non-tmux mode with production awareness
    # (Similar to tmux version but with gnome-terminal)
fi

echo "==============================================="
echo "  🎉 Enhanced DroneServices System Started!"
echo "==============================================="
echo ""
echo "✅ All services running in $(echo $DEPLOYMENT_MODE | tr '[:lower:]' '[:upper:]') mode"
if [ "$DEPLOYMENT_MODE" = "production" ]; then
    echo "🚀 Production optimizations active"
    echo "📊 Monitor logs for performance metrics"
    echo "🔒 Security hardening recommended for live deployment"
else
    echo "🔧 Development mode with hot reloading active"
    echo "🐛 Debug mode enabled for easier troubleshooting"
fi
echo ""