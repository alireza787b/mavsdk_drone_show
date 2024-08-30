#src/flask_handler.py
import time
import subprocess
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
                return jsonify({"error_in_get_drone_state": str(e)}), 500

        @self.app.route(f"/{Params.send_drone_command_URI}", methods=['POST'])
        def send_drone_command():
            try:
                command_data = request.get_json()
                self.drone_communicator.process_command(command_data)
                return jsonify({"status": "success", "message": "Command received"}), 200
            except Exception as e:
                return jsonify({"error": str(e)}), 500

        @self.app.route('/get-git-status', methods=['GET'])
        def get_git_status():
            try:
                # Retrieve the current branch
                branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD']).strip().decode('utf-8')
                
                # Retrieve the latest commit hash
                commit = subprocess.check_output(['git', 'rev-parse', 'HEAD']).strip().decode('utf-8')
                
                # Retrieve the author name and email
                author_name = subprocess.check_output(['git', 'show', '-s', '--format=%an', commit]).strip().decode('utf-8')
                author_email = subprocess.check_output(['git', 'show', '-s', '--format=%ae', commit]).strip().decode('utf-8')
                
                # Retrieve the commit date
                commit_date = subprocess.check_output(['git', 'show', '-s', '--format=%cd', '--date=iso-strict', commit]).strip().decode('utf-8')
                
                # Retrieve the commit message
                commit_message = subprocess.check_output(['git', 'show', '-s', '--format=%B', commit]).strip().decode('utf-8')
                
                # Retrieve the remote URL
                remote_url = subprocess.check_output(['git', 'config', '--get', 'remote.origin.url']).strip().decode('utf-8')
                
                # Retrieve the tracking branch (e.g., origin/main)
                tracking_branch = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}']).strip().decode('utf-8')
                
                # Check if the working directory is clean or has uncommitted changes
                status = subprocess.check_output(['git', 'status', '--porcelain']).strip().decode('utf-8')

                return jsonify({
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
                })
            except subprocess.CalledProcessError as e:
                return jsonify({'error': f"Git command failed: {str(e)}"}), 500

    def run(self):
        host = '0.0.0.0'
        port = self.params.drones_flask_port

        if self.params.env_mode == 'development':
            self.app.run(host=host, port=port, debug=True, use_reloader=False)
        else:
            self.app.run(host=host, port=port, debug=False, use_reloader=False)
