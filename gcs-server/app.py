import os
import sys
import logging
from flask import Flask
from flask_cors import CORS
from routes import setup_routes

# Configure logging at the entry point of the application
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def create_app():
    """
    Create and configure an instance of the Flask application.
    Applies CORS to all routes within the application and sets up routes using a separate module.
    """
    app = Flask(__name__)

    # Enable CORS globally across all origins
    CORS(app)

    # Set up routes defined in the 'routes.py' module
    setup_routes(app)

    return app

if __name__ == "__main__":
    app = create_app()

    # Load system or application parameters from external sources if needed
    from params import Params  # Consider moving imports to the top if Params is used elsewhere outside __main__

    # Adjust the running port and debug mode based on environmental settings
    if Params.env_mode == 'development':
        app.run(host='0.0.0.0', port=Params.flask_telem_socket_port, debug=True)
    else:
        app.run(host='0.0.0.0', port=Params.flask_telem_socket_port, debug=False)
