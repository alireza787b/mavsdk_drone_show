#src/flask_handler.py
import time
import subprocess
from flask import Flask, jsonify, request
from flask_cors import CORS
from src.params import Params

class FlaskHandler:
    def __init__(self, params, drone_communicator):
        self.app = Flask(__name__)
        CORS(self.app)  # Enable CORS for all routes
        self.params = params
        self.drone_communicator = drone_communicator
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
