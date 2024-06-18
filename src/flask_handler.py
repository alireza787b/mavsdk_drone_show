# flask_handler.py
import time
from flask import Flask, jsonify

class FlaskHandler:
    def __init__(self,params , drone_communicator):
        self.app = Flask(__name__)
        self.params = params
        self.drone_communicator = drone_communicator
        self.setup_routes()

    def setup_routes(self):
        @self.app.route('/get-drone-state', methods=['GET'])
        def get_drone_state():
            try:
                drone_state = self.drone_communicator.get_drone_state()
                if drone_state:
                    # Add the current UNIX timestamp to the drone state dictionary
                    drone_state['timestamp'] = int(time.time())
                    return jsonify(drone_state)
                else:
                    return jsonify({"error": "Drone State not found"}), 404
            except Exception as e:
                return jsonify({"error": str(e)}), 500

    def run(self):
        host='0.0.0.0'
        port=self.params.drones_flask_port
        self.app.run(host=host, port=port, debug=False, use_reloader=False)
