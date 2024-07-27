import os
import subprocess
import time
import zipfile
from flask import Flask, jsonify, request, send_file, send_from_directory, current_app
import pandas as pd
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all
from config import load_config, save_config, load_swarm, save_swarm
from utils import allowed_file, clear_show_directories, zip_directory
import logging
from process_formation import run_formation_process  # Assuming you've refactored process_formation.py to provide this function

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_routes(app):
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        #logger.info("Telemetry data requested")
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
            logger.error(f"Error sending command: {str(e)}")
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
            logger.error(f"Error saving configuration: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/get-config-data', methods=['GET'])
    def get_config():
        logger.info("Configuration data requested")
        try:
            config = load_config()
            return jsonify(config)
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
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
            logger.error(f"Error saving swarm data: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm():
        logger.info("Swarm data requested")
        try:
            swarm = load_swarm()
            return jsonify(swarm)
        except Exception as e:
            logger.error(f"Error loading swarm data: {str(e)}")
            return jsonify({'status': 'error', 'message': str(e)}), 500


    @app.route('/import-show', methods=['POST'])
    def import_show():
        logger = logging.getLogger(__name__)
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
                zip_path = os.path.join('temp', 'uploaded.zip')
                uploaded_file.save(zip_path)
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall('shapes/swarm/skybrush')
                os.remove(zip_path)
                
                output = run_formation_process()
                logger.info(f"Process formation output: {output}")
                
                return jsonify({'success': True, 'message': output})
            except Exception as e:
                logger.error(f"Unexpected error during show import: {e}")
                return jsonify({'success': False, 'error': 'Unexpected error during show import', 'details': str(e)})
        else:
            logger.warning("Invalid file type uploaded")
            return jsonify({'success': False, 'error': 'Invalid file type. Please upload a ZIP file.'})
        
        
    @app.route('/download-raw-show', methods=['GET'])
    def download_raw_show():
        zip_file = zip_directory('shapes/swarm/skybrush', 'temp/raw_show')
        return send_file(zip_file, as_attachment=True, download_name='raw_show.zip')

    @app.route('/download-processed-show', methods=['GET'])
    def download_processed_show():
        zip_file = zip_directory('shapes/swarm/processed', 'temp/processed_show')
        return send_file(zip_file, as_attachment=True, download_name='processed_show.zip')


    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        logger.info(f"Image requested: {filename}")
        plots_directory = os.path.abspath('shapes/swarm/plots')
        return send_from_directory(plots_directory, filename)

    @app.route('/get-show-plots', methods=['GET'])
    def get_show_plots():
        logger.info("Show plots list requested")
        plots_directory = 'shapes/swarm/plots'
        filenames = [f for f in os.listdir(plots_directory) if f.endswith('.png')]
        if 'all_drones.png' in filenames:
            upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'all_drones.png')))
        else:
            upload_time = "unknown"
        return jsonify({'filenames': filenames, 'uploadTime': upload_time})

    @app.route('/get-first-last-row/<string:hw_id>', methods=['GET'])
    def get_first_last_row(hw_id):
        logger.info(f"First and last row requested for drone {hw_id}")
        try:
            csv_path = os.path.join("shapes", "swarm", "skybrush", f"Drone {hw_id}.csv")
            df = pd.read_csv(csv_path)
            first_row = df.iloc[0]
            last_row = df.iloc[-1]
            result = {
                "success": True,
                "firstRow": {"x": first_row['x [m]'], "y": first_row['y [m]']},
                "lastRow": {"x": last_row['x [m]'], "y": last_row['y [m]']}
            }
            logger.info(f"Successfully retrieved data for drone {hw_id}")
            return jsonify(result)
        except Exception as e:
            logger.error(f"Error retrieving data for drone {hw_id}: {str(e)}")
            return jsonify({"success": False, "error": str(e)}), 500
        
        # Error handling
    @app.errorhandler(404)
    def not_found_error(error):
        logger.error(f"404 error: {error}")
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        logger.error(f"500 error: {error}")
        return jsonify({"error": "Internal server error"}), 500

    # Start telemetry polling
    drones = load_config()
    start_telemetry_polling(drones)
    logger.info("Telemetry polling started")



if __name__ == '__main__':
    app = Flask(__name__)
    setup_routes(app)
    logger.info("Flask app started")
    app.run(debug=True)