import time
from flask import Flask, jsonify, request
from flask_cors import CORS
from src.params import Params

class FlaskHandler:
    def __init__(self, params, drone_communicator):
        self.app = Flask(__name__)
        CORS(self.app)  # This will enable CORS for all routes
        self.params = params
        self.drone_communicator = drone_communicator
        self.setup_routes()

    def setup_routes(self):
        @self.app.route(f"/{Params.get_drone_state_URI}", methods=['GET'])
        def get_drone_state():
            try:
                drone_state = self.drone_communicator.get_drone_state()
                if drone_state:
                    # Send timestamp in milliseconds
                    drone_state['timestamp'] = int(time.time() * 1000)
                    return jsonify(drone_state)
                else:
                    return jsonify({"error": "Drone State not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route(f"/{Params.send_drone_command_URI}", methods=['POST'])
        def send_drone_command():
            try:
                command_data = request.get_json()
                self.drone_communicator.process_command(command_data)
                return jsonify({"status": "success", "message": "Command received"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def run(self):
        host = '0.0.0.0'
        port = self.params.drones_flask_port

        if self.params.env_mode == 'development':
            self.app.run(host=host, port=port, debug=True, use_reloader=False)
        else:
            self.app.run(host=host, port=port, debug=False, use_reloader=False)
