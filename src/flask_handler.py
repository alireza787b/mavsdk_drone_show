#src/flask_handler.py
import math
import time
import subprocess
from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
from src.drone_config import DroneConfig
from functions.data_utils import safe_float, safe_get
from src.params import Params
import logging
from pyproj import Proj, Transformer



class FlaskHandler:
    def __init__(self, params: Params, drone_config: DroneConfig):
        """
        Initialize the FlaskHandler with params and drone_config.
        DroneCommunicator will be injected later using the set_drone_communicator() method.
        """
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for all routes
        self.params = params
        self.drone_communicator = None  # DroneCommunicator will be set later
        self.drone_config = drone_config
        self.setup_routes()

    def setup_routes(self):
        """Defines the routes for the Flask application."""
        @self.app.route(f"/{Params.get_drone_state_URI}", methods=['GET'])
        def get_drone_state():
            """Endpoint to retrieve the current state of the drone."""
            try:
                drone_state = self.drone_communicator.get_drone_state()
                if drone_state:
                    # Add a timestamp to the drone state
                    drone_state['timestamp'] = int(time.time() * 1000)
                    return jsonify(drone_state)
                else:
                    return jsonify({"error": "Drone State not found"}), 404
            except Exception as e:
                return jsonify({"error_in_get_drone_state": str(e)}), 500

        @self.app.route(f"/{Params.send_drone_command_URI}", methods=['POST'])
        def send_drone_command():
            """Endpoint to send a command to the drone."""
            try:
                command_data = request.get_json()
                self.drone_communicator.process_command(command_data)
                return jsonify({"status": "success", "message": "Command received"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/get-git-status', methods=['GET'])
        def get_git_status():
            """
            Endpoint to retrieve the current Git status of the drone.
            This includes the branch, commit hash, author details, commit date,
            commit message, remote repository URL, tracking branch, and status of the working directory.
            """
            try:
                # Retrieve the current branch name
                branch = self._execute_git_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])

                # Retrieve the latest commit hash
                commit = self._execute_git_command(['git', 'rev-parse', 'HEAD'])

                # Retrieve author details and commit information
                author_name = self._execute_git_command(['git', 'show', '-s', '--format=%an', commit])
                author_email = self._execute_git_command(['git', 'show', '-s', '--format=%ae', commit])
                commit_date = self._execute_git_command(['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit])
                commit_message = self._execute_git_command(['git', 'show', '-s', '--format=%B', commit])

                # Retrieve remote repository URL
                remote_url = self._execute_git_command(['git', 'config', '--get', 'remote.origin.url'])

                # Retrieve the tracking branch
                tracking_branch = self._execute_git_command(['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])

                # Check if the working directory is clean or has uncommitted changes
                status = self._execute_git_command(['git', 'status', '--porcelain'])

                # Build the response dictionary
                response = {
                    'branch': branch,
                    'commit': commit,
                    'author_name': author_name,
                    'author_email': author_email,
                    'commit_date': commit_date,
                    'commit_message': commit_message,
                    'remote_url': remote_url,
                    'tracking_branch': tracking_branch,
                    'status': 'clean' if not status else 'dirty',
                    'uncommitted_changes': status.splitlines() if status else []
                }

                return jsonify(response)
            except subprocess.CalledProcessError as e:
                return jsonify({'error': f"Git command failed: {str(e)}"}), 500
            
            
        @self.app.route(f"/{Params.get_position_deviation_URI}", methods=['GET'])
        def get_position_deviation():
            """Endpoint to calculate the drone's position deviation from its intended initial position."""
            try:
                # Step 1: Get the origin coordinates from GCS
                origin = self._get_origin_from_gcs()
                if not origin:
                    return jsonify({"error": "Origin coordinates not set on GCS"}), 400

                # Step 2: Get the drone's current position
                current_lat = safe_float(safe_get(self.drone_config.position, 'lat'))
                current_lon = safe_float(safe_get(self.drone_config.position, 'long'))
                if current_lat is None or current_lon is None:
                    return jsonify({"error": "Drone's current position not available"}), 400

                # Step 3: Get the drone's intended initial position (N, E) from config
                initial_east = safe_float(safe_get(self.drone_config.config, 'x'))  # 'x' is East
                initial_north = safe_float(safe_get(self.drone_config.config, 'y'))  # 'y' is North
                if initial_north is None or initial_east is None:
                    return jsonify({"error": "Drone's intended initial position not set"}), 400

                # Step 4: Convert current position to NE coordinates relative to the origin
                current_north, current_east = self._latlon_to_ne(current_lat, current_lon, origin['lat'], origin['lon'])

                # Step 5: Calculate deviations
                deviation_north = current_north - initial_north
                deviation_east = current_east - initial_east
                total_deviation = math.sqrt(deviation_north**2 + deviation_east**2)

                # Step 6: Check if within acceptable range
                acceptable_range = self.params.acceptable_deviation  # in meters
                within_range = total_deviation <= acceptable_range

                # Step 7: Prepare and return response
                response = {
                    "deviation_north": deviation_north,
                    "deviation_east": deviation_east,
                    "total_deviation": total_deviation,
                    "within_acceptable_range": within_range
                }
                return jsonify(response), 200

            except Exception as e:
                logging.error(f"Error in get_position_deviation: {e}")
                return jsonify({"error": str(e)}), 500

    # Helper method to get origin from GCS
    def _get_origin_from_gcs(self):
        """Fetches the origin coordinates from the GCS."""
        try:
            gcs_ip = self.drone_config.config.get('gcs_ip')
            if not gcs_ip:
                logging.error("GCS IP not set in drone configuration")
                return None

            gcs_port = self.params.flask_telem_socket_port
            gcs_url = f"http://{gcs_ip}:{gcs_port}"

            response = requests.get(f"{gcs_url}/get-origin", timeout=5)
            if response.status_code == 200:
                data = response.json()
                if 'lat' in data and 'lon' in data:
                    return {'lat': float(data['lat']), 'lon': float(data['lon'])}
            else:
                logging.error(f"GCS responded with status code {response.status_code}")
            return None
        except requests.RequestException as e:
            logging.error(f"Error fetching origin from GCS: {e}")
            return None

    # Helper method to convert lat/lon to NE coordinates
    def _latlon_to_ne(self, lat, lon, origin_lat, origin_lon):
        """Converts lat/lon to north-east coordinates relative to the origin."""
        # Define a local projection centered at the origin
        proj_string = f"+proj=tmerc +lat_0={origin_lat} +lon_0={origin_lon} +k=1 +units=m +ellps=WGS84"
        transformer = Transformer.from_proj(
            Proj('epsg:4326'),  # Source coordinate system (WGS84)
            Proj(proj_string)   # Local tangent plane projection
        )
        east, north = transformer.transform(lat, lon)
        return north, east



    def _execute_git_command(self, command):
        """
        Helper method to execute a Git command and return the output.
        :param command: List containing the Git command and its arguments.
        :return: Output of the Git command as a decoded string.
        :raises: subprocess.CalledProcessError if the Git command fails.
        """
        return subprocess.check_output(command).strip().decode('utf-8')

    def run(self):
        """Runs the Flask application."""
        host = '0.0.0.0'
        port = self.params.drones_flask_port

        if self.params.env_mode == 'development':
            self.app.run(host=host, port=port, debug=True, use_reloader=False)
        else:
            self.app.run(host=host, port=port, debug=False, use_reloader=False)


    