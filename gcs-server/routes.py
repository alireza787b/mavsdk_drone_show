import os
import subprocess
import time
import zipfile
import logging
from flask import Flask, jsonify, request, send_from_directory
import pandas as pd
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all
from config import load_config, save_config, load_swarm, save_swarm
from utils import allowed_file, clear_show_directories

def setup_routes(app):
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        logging.info("Telemetry data requested")
        return jsonify(telemetry_data_all_drones)

    @app.route('/send_command', methods=['POST'])
    def send_command():
        command_data = request.get_json()
        logging.info(f"Command received: {command_data}")
        drones = load_config()
        send_commands_to_all(drones, command_data)
        return jsonify({'status': 'success', 'message': 'Command sent to all drones'})

    @app.route('/save_config', methods=['POST'])
    def save_config_route():
        config_data = request.get_json()
        save_config(config_data)
        logging.info("Configuration saved successfully")
        return jsonify({'status': 'success', 'message': 'Configuration saved successfully'})

    @app.route('/get_config', methods=['GET'])
    def get_config():
        config = load_config()
        logging.info("Configuration data requested")
        return jsonify(config)

    @app.route('/save_swarm', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        save_swarm(swarm_data)
        logging.info("Swarm data saved successfully")
        return jsonify({'status': 'success', 'message': 'Swarm data saved successfully'})

    @app.route('/get_swarm', methods=['GET'])
    def get_swarm():
        swarm = load_swarm()
        logging.info("Swarm data requested")
        return jsonify(swarm)

    @app.route('/import-show', methods=['POST'])
    def import_show():
        uploaded_file = request.files.get('file')
        if uploaded_file and allowed_file(uploaded_file.filename):
            clear_show_directories()
            zip_path = os.path.join('temp', 'uploaded.zip')
            uploaded_file.save(zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall('shapes/swarm/skybrush')
            os.remove(zip_path)
            try:
                completed_process = subprocess.run(["python3", "process_formation.py"], capture_output=True, text=True, check=True)
                logging.info(f"Process formation output: {completed_process.stdout}")
            except subprocess.CalledProcessError as e:
                logging.error(f"Error in running process formation script: {e}")
                return jsonify({'success': False, 'error': 'Error in running processformation.py', 'details': str(e)})
            return jsonify({'success': True})
        else:
            logging.error("Invalid file type for import show")
            return jsonify({'success': False, 'error': 'Invalid file type. Please upload a ZIP file.'})

    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        logging.info(f"Serving image: {filename}")
        return send_from_directory('shapes/swarm/plots', filename)

    @app.route('/get-show-plots', methods=['GET'])
    def get_show_plots():
        plots_directory = 'shapes/swarm/plots'
        filenames = [f for f in os.listdir(plots_directory) if f.endswith('.png')]
        if 'all_drones.png' in filenames:
            upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'all_drones.png')))
        else:
            upload_time = "unknown"
        logging.info("Show plots requested")
        return jsonify({'filenames': filenames, 'uploadTime': upload_time})

    @app.route('/get-first-last-row/<string:hw_id>', methods=['GET'])
    def get_first_last_row(hw_id):
        try:
            csv_path = os.path.join("shapes", "swarm", "skybrush", f"Drone {hw_id}.csv")
            df = pd.read_csv(csv_path)
            first_row = df.iloc[0]
            last_row = df.iloc[-1]
            first_x = first_row['x [m]']
            first_y = first_row['y [m]']
            last_x = last_row['x [m]']
            last_y = last_row['y [m]']
            logging.info(f"First and last row for drone {hw_id} requested")
            return jsonify({"success": True, "firstRow": {"x": first_x, "y": first_y}, "lastRow": {"x": last_x, "y": last_y}})
        except Exception as e:
            logging.error(f"Error getting first and last row for drone {hw_id}: {e}")
            return jsonify({"success": False, "error": str(e)})

    drones = load_config()
    start_telemetry_polling(drones)
