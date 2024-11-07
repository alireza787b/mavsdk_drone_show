# gcs-server/app.py
import os
import sys
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from routes import setup_routes
from telemetry import start_telemetry_thread  # Updated import
from config import load_config

# Configure logging at the entry point of the application
def configure_logging():
    log_level = logging.DEBUG if os.getenv('FLASK_DEBUG', 'false').lower() == 'true' else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("app.log") if log_level == logging.INFO else logging.NullHandler()
        ]
    )
    logging.info("Logging is configured.")

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
        start_telemetry_thread(drones)  # Updated function call
    else:
        logging.error("No drones found in configuration. Telemetry polling will not be started.")

    ENV_MODE = os.getenv('FLASK_ENV', 'development')
    FLASK_PORT = int(os.getenv('FLASK_PORT', Params.flask_telem_socket_port))
    DEBUG_MODE = ENV_MODE == 'development'

    app = create_app()
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=DEBUG_MODE)
