#gcs-server/routes.py
import os
import subprocess
import sys
import time
import traceback
import zipfile
import requests
from flask import Flask, jsonify, request, send_file, send_from_directory, current_app
import pandas as pd
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all, send_command_to_drone
from config import get_drone_git_status, get_git_status, load_config, save_config, load_swarm, save_swarm
from utils import allowed_file, clear_show_directories, git_operations, zip_directory
import logging
from params import Params
from datetime import datetime
from get_elevation import get_elevation  # Import the elevation function
from origin import save_origin, load_origin


# Configure base directory for better path management
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(BASE_DIR)
from process_formation import run_formation_process

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def error_response(message, status_code=500):
    """Generate a consistent error response with logging."""
    logger.error(message)
    return jsonify({'status': 'error', 'message': message}), status_code

def setup_routes(app):
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        logger.info("Telemetry data requested")
        if not telemetry_data_all_drones:
            logger.warning("Telemetry data is currently empty")
        return jsonify(telemetry_data_all_drones)

    @app.route('/submit_command', methods=['POST'])
    def submit_command():
        command_data = request.get_json()
        if not command_data:
            return error_response("No command data provided", 400)

        logger.info(f"Received command: {command_data}")
        try:
            drones = load_config()
            if not drones:
                return error_response("No drones found in the configuration", 500)

            send_commands_to_all(drones, command_data)
            logger.info("Command sent successfully to all drones")
            return jsonify({'status': 'success', 'message': 'Command sent to all drones'})
        except Exception as e:
            logger.error(f"Error sending command: {e}", exc_info=True)
            return error_response(f"Error sending command: {e}")

    @app.route('/save-config-data', methods=['POST'])
    def save_config_route():
        config_data = request.get_json()
        if not config_data:
            return error_response("No configuration data provided", 400)

        logger.info("Received configuration data for saving")
        try:
            # Save the configuration data
            save_config(config_data)
            logger.info("Configuration saved successfully")

            git_info = None
            # If auto push to Git is enabled, perform Git operations
            if Params.GIT_AUTO_PUSH:
                logger.info("Git auto-push is enabled. Attempting to push configuration changes to repository.")
                git_info = git_operations(BASE_DIR, f"Update configuration: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                logger.info(git_info)

            # Return a success message, including Git info if applicable
            response_data = {'status': 'success', 'message': 'Configuration saved successfully'}
            if git_info:
                response_data['git_info'] = git_info

            return jsonify(response_data)
        except Exception as e:
            logger.error(f"Error saving configuration: {e}", exc_info=True)
            return error_response(f"Error saving configuration: {e}")

    @app.route('/get-config-data', methods=['GET'])
    def get_config():
        logger.info("Configuration data requested")
        try:
            config = load_config()
            return jsonify(config)
        except Exception as e:
            return error_response(f"Error loading configuration: {e}")

    @app.route('/save-swarm-data', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        if not swarm_data:
            return error_response("No swarm data provided", 400)

        logger.info("Received swarm data for saving")
        try:
            save_swarm(swarm_data)
            logger.info("Swarm data saved successfully")
            return jsonify({'status': 'success', 'message': 'Swarm data saved successfully'})
        except Exception as e:
            return error_response(f"Error saving swarm data: {e}")

    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm():
        logger.info("Swarm data requested")
        try:
            swarm = load_swarm()
            return jsonify(swarm)
        except Exception as e:
            return error_response(f"Error loading swarm data: {e}")

    @app.route('/import-show', methods=['POST'])
    def import_show():
        """
        Endpoint to handle the uploading and processing of drone show files,
        saves the uploaded files, processes them, and optionally pushes changes to a Git repository.
        """
        logger.info("Show import requested")
        file = request.files.get('file')
        if not file or file.filename == '':
            logger.warning("No file part or empty filename")
            return error_response('No file part or empty filename', 400)

        skybrush_dir = os.path.join(BASE_DIR, 'shapes/swarm/skybrush')
        try:
            clear_show_directories(BASE_DIR)
            zip_path = os.path.join(BASE_DIR, 'temp', 'uploaded.zip')
            file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(skybrush_dir)
            os.remove(zip_path)

            # Debug log before processing
            logger.debug(f"Starting process formation for files in {skybrush_dir}")
            output = run_formation_process(BASE_DIR)
            logger.info(f"Process formation output: {output}")

            if Params.GIT_AUTO_PUSH:
                git_result = git_operations(BASE_DIR, f"Update from upload: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {file.filename}")
                logger.info(git_result)
                return jsonify({'success': True, 'message': output, 'git_info': git_result})
            else:
                return jsonify({'success': True, 'message': output})
        except Exception as e:
            return error_response(f"Unexpected error during show import: {traceback.format_exc()}")

    @app.route('/download-raw-show', methods=['GET'])
    def download_raw_show():
        try:
            zip_file = zip_directory(os.path.join(BASE_DIR, 'shapes/swarm/skybrush'), os.path.join(BASE_DIR, 'temp/raw_show'))
            return send_file(zip_file, as_attachment=True, download_name='raw_show.zip')
        except Exception as e:
            return error_response(f"Error creating raw show zip: {e}")

    @app.route('/download-processed-show', methods=['GET'])
    def download_processed_show():
        try:
            zip_file = zip_directory(os.path.join(BASE_DIR, 'shapes/swarm/processed'), os.path.join(BASE_DIR, 'temp/processed_show'))
            return send_file(zip_file, as_attachment=True, download_name='processed_show.zip')
        except Exception as e:
            return error_response(f"Error creating processed show zip: {e}")

    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        logger.info(f"Image requested: {filename}")
        try:
            plots_directory = os.path.join(BASE_DIR, 'shapes/swarm/plots')
            return send_from_directory(plots_directory, filename)
        except Exception as e:
            return error_response(f"Error sending image: {e}", 404)

    @app.route('/get-show-plots', methods=['GET'])
    def get_show_plots():
        logger.info("Show plots list requested")
        try:
            plots_directory = os.path.join(BASE_DIR, 'shapes/swarm/plots')
            if not os.path.exists(plots_directory):
                os.makedirs(plots_directory)

            filenames = [f for f in os.listdir(plots_directory) if f.endswith('.png')]
            upload_time = "unknown"
            if 'all_drones.png' in filenames:
                upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'all_drones.png')))

            return jsonify({'filenames': filenames, 'uploadTime': upload_time})
        except Exception as e:
            return error_response(f"Failed to list directory: {e}")

    @app.route('/elevation', methods=['GET'])
    def elevation_route():
        lat = request.args.get('lat')
        lon = request.args.get('lon')

        if lat is None or lon is None:
            logger.error("Latitude and Longitude must be provided")
            return jsonify({'error': 'Latitude and Longitude must be provided'}), 400

        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            logger.error("Invalid latitude or longitude format")
            return jsonify({'error': 'Invalid latitude or longitude format'}), 400

        elevation_data = get_elevation(lat, lon)
        if elevation_data:
            return jsonify(elevation_data)
        else:
            return jsonify({'error': 'Failed to fetch elevation data'}), 500

    @app.route('/get-gcs-git-status', methods=['GET'])
    def get_gcs_git_status():
        """Retrieve the Git status of the GCS."""
        gcs_status = get_git_status()
        return jsonify(gcs_status)

    @app.route('/get-drone-git-status/<int:drone_id>', methods=['GET'])
    def fetch_drone_git_status(drone_id):
        """
        Endpoint to retrieve the Git status of a specific drone using its hardware ID (hw_id).
        :param drone_id: Hardware ID (hw_id) of the drone.
        :return: JSON response with Git status or an error message.
        """
        try:
            logging.debug(f"Fetching drone with ID {drone_id} from configuration")
            drones = load_config()
            drone = next((d for d in drones if int(d['hw_id']) == drone_id), None)

            if not drone:
                logging.error(f'Drone with ID {drone_id} not found')
                return jsonify({'error': f'Drone with ID {drone_id} not found'}), 404

            drone_uri = f"http://{drone['ip']}:{Params.drones_flask_port}"
            logging.debug(f"Constructed drone URI: {drone_uri}")
            drone_status = get_drone_git_status(drone_uri)

            if 'error' in drone_status:
                logging.error(f"Error in drone status response: {drone_status['error']}")
                return jsonify({'error': drone_status['error']}), 500

            logging.debug(f"Drone status retrieved successfully: {drone_status}")
            return jsonify(drone_status), 200
        except Exception as e:
            logging.error(f"Exception occurred: {str(e)}")
            return jsonify({'error': str(e)}), 500





    @app.route('/get-custom-show-image', methods=['GET'])
    def get_custom_show_image():
        """
        Endpoint to get the custom drone show image.
        The image is expected to be located at shapes/active.png.
        """
        try:
            image_path = os.path.join(BASE_DIR, 'shapes', 'trajectory_plot.png')
            print("Debug: Image path being used:", image_path)  # Debug statement
            if os.path.exists(image_path):
                return send_file(image_path, mimetype='image/png', as_attachment=False)
            else:
                return jsonify({'error': f'Custom show image not found at {image_path}'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/set-origin', methods=['POST'])
    def set_origin():
        data = request.get_json()
        lat = data.get('lat')
        lon = data.get('lon')
        if lat is None or lon is None:
            logger.error("Latitude and longitude are required")
            return jsonify({'status': 'error', 'message': 'Latitude and longitude are required'}), 400
        try:
            save_origin({'lat': lat, 'lon': lon})
            logger.info("Origin coordinates saved")
            return jsonify({'status': 'success', 'message': 'Origin saved'})
        except Exception as e:
            logger.error(f"Error saving origin: {e}")
            return jsonify({'status': 'error', 'message': 'Error saving origin'}), 500

    @app.route('/get-origin', methods=['GET'])
    def get_origin():
        try:
            data = load_origin()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error loading origin: {e}")
            return jsonify({'status': 'error', 'message': 'Error loading origin'}), 500

