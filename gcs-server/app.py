#gcs-server/app.py
import os
import sys
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from routes import setup_routes
from telemetry import start_telemetry_polling
from git_status import start_git_status_polling
from config import load_config

def configure_logging():
    log_level = logging.DEBUG if os.getenv('FLASK_DEBUG', 'false').lower() == 'true' else logging.INFO
    logger = logging.getLogger()
    logger.setLevel(log_level)

    RESET = "\x1b[0m"
    GREEN = "\x1b[32m"
    RED = "\x1b[31m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    INFO_SYMBOL = BLUE + "[INFO]" + RESET

    class CustomFormatter(logging.Formatter):
        def format(self, record):
            levelno = record.levelno
            if levelno >= logging.CRITICAL:
                color = RED
            elif levelno >= logging.ERROR:
                color = RED
            elif levelno >= logging.WARNING:
                color = YELLOW
            elif levelno >= logging.INFO:
                color = GREEN
            else:
                color = RESET
            formatter = logging.Formatter(f"{color}%(asctime)s | %(message)s{RESET}", "%Y-%m-%d %H:%M:%S")
            return formatter.format(record)

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())
    logger.handlers = [handler]

    logging.info(f"{INFO_SYMBOL} Logging is configured.")

def create_app():
    app = Flask(__name__)
    CORS(app, resources={r"/*": {"origins": "*"}})
    setup_routes(app)

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500

    return app

def initialize_services():
    """Initialize background services for production and development"""
    from params import Params
    
    drones = load_config()
    if drones:
        logging.info(f"Starting telemetry polling for {len(drones)} drones.")
        start_telemetry_polling(drones)
        logging.info(f"Starting git status polling for {len(drones)} drones.")
        start_git_status_polling(drones)
    else:
        logging.error("No drones found in configuration. Telemetry polling will not be started.")

# CRITICAL FIX: Create module-level app object for gunicorn
configure_logging()
initialize_services()
app = create_app()

if __name__ == "__main__":
    from params import Params
    
    ENV_MODE = os.getenv('FLASK_ENV', 'development')
    FLASK_PORT = int(os.getenv('FLASK_PORT', Params.flask_telem_socket_port))
    DEBUG_MODE = ENV_MODE == 'development'

    app.run(host='0.0.0.0', port=FLASK_PORT, debug=DEBUG_MODE)