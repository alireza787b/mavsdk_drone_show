import os
import sys
import logging
from flask import Flask
from routes import setup_routes

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'src')))
from params import Params

def create_app():
    app = Flask(__name__)
    setup_routes(app)
    return app

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(level=logging.INFO)
    
    app = create_app()

    if Params.env_mode == 'development':
        app.run(host='0.0.0.0', port=Params.flask_telem_socket_port, debug=True)
    else:
        app.run(host='0.0.0.0', port=Params.flask_telem_socket_port, debug=False)
