#gcs-server/app.py
import os
import sys
import logging
from flask import Flask, jsonify
from flask_cors import CORS
from routes import setup_routes
from telemetry import start_telemetry_polling
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
    """
    Create and configure an instance of the Flask application.
    Applies CORS to all routes within the application and sets up routes using a separate module.
    """
    app = Flask(__name__)

    # Enable CORS globally (consider restricting origins in production)
    CORS(app, resources={r"/*": {"origins": "*"}})

    # Set up routes defined in the 'routes.py' module
    setup_routes(app)

    # Example custom error handler
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Not found'}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500

    return app

if __name__ == "__main__":
    # Configure logging before creating the app
    configure_logging()

    # Load system or application parameters from external sources if needed
    from params import Params  # Consider moving imports to the top if Params is used elsewhere outside __main__

    # Start telemetry polling for all drones
    drones = load_config()
    if drones:
        start_telemetry_polling(drones)
    else:
        logging.error("No drones found in configuration")

    # Environment-based configuration
    ENV_MODE = os.getenv('FLASK_ENV', 'development')
    FLASK_PORT = int(os.getenv('FLASK_PORT', Params.flask_telem_socket_port))
    DEBUG_MODE = ENV_MODE == 'development'

    app = create_app()

    # Run the Flask app
    app.run(host='0.0.0.0', port=FLASK_PORT, debug=DEBUG_MODE)
