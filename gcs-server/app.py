#gcs-server/app.py
import os
import sys
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from routes import setup_routes
from telemetry import start_telemetry_polling
from git_status import start_git_status_polling
from network import start_network_status_polling
from config import load_config

# Configure logging at the entry point of the application
def configure_logging():
    log_level = logging.DEBUG if os.getenv('FLASK_DEBUG', 'false').lower() == 'true' else logging.INFO
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # Define colors and symbols
    RESET = "\x1b[0m"
    GREEN = "\x1b[32m"
    RED = "\x1b[31m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    INFO_SYMBOL = BLUE + "ℹ️" + RESET

    # Custom formatter with colors
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
    logger.handlers = [handler]  # Replace existing handlers

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

if __name__ == "__main__":
    configure_logging()

    from params import Params

    drones = load_config()
    if drones:
        logging.info(f"Starting telemetry polling for {len(drones)} drones.")
        start_telemetry_polling(drones)
        logging.info(f"Starting git status polling for {len(drones)} drones.")
        start_git_status_polling(drones)
        # logging.info(f"Starting network status polling for {len(drones)} drones.")
        # start_network_status_polling(drones)
    else:
        logging.error("No drones found in configuration. Telemetry polling will not be started.")

    ENV_MODE = os.getenv('FLASK_ENV', 'development')
    FLASK_PORT = int(os.getenv('FLASK_PORT', Params.flask_telem_socket_port))
    DEBUG_MODE = ENV_MODE == 'development'

    app = create_app()
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=DEBUG_MODE)
