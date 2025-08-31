# gcs-server/app.py
"""
GCS Server Main Application
==========================
Updated with advanced logging system for clean monitoring of drone swarms.
"""

import os
import sys
import signal
from flask import Flask, jsonify
from flask_cors import CORS

# Import the new logging system
from logging_config import (
    initialize_logging, get_logger, LogLevel, DisplayMode,
    log_system_startup, log_system_error, log_system_warning,
    configure_from_environment
)

from routes import setup_routes
from telemetry import start_telemetry_polling
from git_status import start_git_status_polling  
from config import load_config

def configure_logging():
    """Configure the advanced logging system"""
    # Determine log level based on environment
    debug_mode = os.getenv('FLASK_DEBUG', 'false').lower() == 'true'
    env_mode = os.getenv('FLASK_ENV', 'development')
    
    if debug_mode:
        log_level = LogLevel.DEBUG
        display_mode = DisplayMode.STREAM  # Use stream mode for debugging
    elif env_mode == 'production':
        log_level = LogLevel.QUIET  # Reduce noise in production
        display_mode = DisplayMode.HYBRID
    else:
        log_level = LogLevel.NORMAL
        display_mode = DisplayMode.HYBRID
    
    # Override with environment variables if set
    try:
        return configure_from_environment()
    except Exception:
        # Fallback to default configuration
        return initialize_logging(
            log_level=log_level,
            display_mode=display_mode,
            log_file='logs/gcs_server.log'
        )

def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}})
    
    # Setup routes
    setup_routes(app)

    @app.errorhandler(404)
    def not_found(error):
        log_system_warning(f"404 Not Found: {error}", "flask")
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        log_system_error(f"500 Internal Error: {error}", "flask")
        return jsonify({'error': 'Internal server error'}), 500

    return app

def initialize_services():
    """Initialize background services with proper logging"""
    try:
        from params import Params
        
        # Load drone configuration
        drones = load_config()
        
        if not drones:
            log_system_error("No drones found in configuration. Services will not start.", "config")
            return False
            
        log_system_startup(len(drones))
        
        # Start telemetry polling
        try:
            start_telemetry_polling(drones)
            get_logger().log_system_event(
                f"Telemetry polling started for {len(drones)} drones",
                "INFO", "telemetry"
            )
        except Exception as e:
            log_system_error(f"Failed to start telemetry polling: {e}", "telemetry")
            return False
        
        # Start git status polling  
        try:
            start_git_status_polling(drones)
            get_logger().log_system_event(
                f"Git status polling started for {len(drones)} drones", 
                "INFO", "git"
            )
        except Exception as e:
            log_system_error(f"Failed to start git status polling: {e}", "git")
            # Don't fail startup for git polling issues
        
        return True
        
    except Exception as e:
        log_system_error(f"Failed to initialize services: {e}", "startup")
        return False

def setup_signal_handlers():
    """Setup graceful shutdown handlers"""
    def signal_handler(signum, frame):
        signal_names = {signal.SIGINT: 'SIGINT', signal.SIGTERM: 'SIGTERM'}
        signal_name = signal_names.get(signum, f'Signal {signum}')
        
        get_logger().log_system_event(
            f"Received {signal_name}, shutting down gracefully...",
            "INFO", "shutdown"
        )
        
        # Perform cleanup here if needed
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

def main():
    """Main application entry point"""
    try:
        # Configure logging first
        logger = configure_logging()
        
        # Setup signal handlers
        setup_signal_handlers()
        
        # Initialize services
        if not initialize_services():
            get_logger().log_system_event(
                "Service initialization failed, exiting...",
                "CRITICAL", "startup"
            )
            sys.exit(1)
        
        # Create Flask app
        app = create_app()
        
        # Get configuration
        from params import Params
        env_mode = os.getenv('FLASK_ENV', 'development')
        flask_port = int(os.getenv('FLASK_PORT', Params.flask_telem_socket_port))
        debug_mode = env_mode == 'development'
        
        get_logger().log_system_event(
            f"Starting GCS server on port {flask_port} in {env_mode} mode",
            "INFO", "startup"
        )
        
        # Run the application
        if env_mode == 'production':
            # Production mode - let gunicorn handle this
            return app
        else:
            # Development mode - run directly
            app.run(
                host='0.0.0.0',
                port=flask_port, 
                debug=debug_mode,
                threaded=True
            )
            
    except Exception as e:
        # Fallback logging if our system fails
        print(f"CRITICAL: Application startup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

# CRITICAL: Module-level app object for gunicorn
app = main()

if __name__ == "__main__":
    main()