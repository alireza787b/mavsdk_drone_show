import os
import subprocess
import sys
import time
import zipfile
from flask import Flask, jsonify, request, send_file, send_from_directory, current_app
import pandas as pd
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all
from config import load_config, save_config, load_swarm, save_swarm
from utils import allowed_file, clear_show_directories, zip_directory
import logging

# Configure base directory for better path management
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
#from process_formation import run_formation_process
print(BASE_DIR)


# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_routes(app):
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        logger.info("Telemetry data requested")
        return jsonify(telemetry_data_all_drones)

    @app.route('/send_command', methods=['POST'])
    def send_command():
        command_data = request.get_json()
        logger.info(f"Received command: {command_data}")
        try:
            drones = load_config()
            send_commands_to_all(drones, command_data)
            logger.info("Command sent successfully to all drones")
            return jsonify({'status': 'success', 'message': 'Command sent to all drones'})
        except Exception as e:
            logger.error(f"Error sending command: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/save-config-data', methods=['POST'])
    def save_config_route():
        config_data = request.get_json()
        logger.info("Received configuration data for saving")
        try:
            save_config(config_data)
            logger.info("Configuration saved successfully")
            return jsonify({'status': 'success', 'message': 'Configuration saved successfully'})
        except Exception as e:
            logger.error(f"Error saving configuration: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/get-config-data', methods=['GET'])
    def get_config():
        logger.info("Configuration data requested")
        try:
            config = load_config()
            return jsonify(config)
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/save-swarm-data', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        logger.info("Received swarm data for saving")
        try:
            save_swarm(swarm_data)
            logger.info("Swarm data saved successfully")
            return jsonify({'status': 'success', 'message': 'Swarm data saved successfully'})
        except Exception as e:
            logger.error(f"Error saving swarm data: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm():
        logger.info("Swarm data requested")
        try:
            swarm = load_swarm()
            return jsonify(swarm)
        except Exception as e:
            logger.error(f"Error loading swarm data: {e}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/import-show', methods=['POST'])
    def import_show():
        logger.info("Show import requested")
        if 'file' not in request.files:
            logger.warning("No file part in the request")
            return jsonify({'success': False, 'error': 'No file part'})

        uploaded_file = request.files['file']
        if uploaded_file.filename == '':
            logger.warning("No selected file")
            return jsonify({'success': False, 'error': 'No selected file'})

        if uploaded_file and allowed_file(uploaded_file.filename):
            try:
                clear_show_directories()
                zip_path = os.path.join(BASE_DIR, 'temp', 'uploaded.zip')
                uploaded_file.save(zip_path)
                logger.info(f"File saved to {zip_path}")
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(os.path.join(BASE_DIR, 'shapes/swarm/skybrush'))
                os.remove(zip_path)
                logger.info("Zip file extracted and original deleted")

                output = run_formation_process()
                if output is None:
                    raise ValueError("Failed to process the formation correctly.")
                return jsonify({'success': True, 'message': output})
            except Exception as e:
                logger.error(f"Unexpected error during show import: {e}", exc_info=True)
                return jsonify({'success': False, 'error': 'Unexpected error during show import', 'details': str(e)})



    @app.route('/download-raw-show', methods=['GET'])
    def download_raw_show():
        zip_file = zip_directory(os.path.join(BASE_DIR, 'shapes/swarm/skybrush'), os.path.join(BASE_DIR, 'temp/raw_show'))
        return send_file(zip_file, as_attachment=True, download_name='raw_show.zip')

    @app.route('/download-processed-show', methods=['GET'])
    def download_processed_show():
        zip_file = zip_directory(os.path.join(BASE_DIR, 'shapes/swarm/processed'), os.path.join(BASE_DIR, 'temp/processed_show'))
        return send_file(zip_file, as_attachment=True, download_name='processed_show.zip')

    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        logger.info(f"Image requested: {filename}")
        plots_directory = os.path.join(BASE_DIR, 'shapes/swarm/plots')
        return send_from_directory(plots_directory, filename)

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
            logger.error(f"Failed to list directory: {e}")
            return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app = Flask(__name__)
    setup_routes(app)
    app.run(debug=True)
