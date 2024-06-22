import os
import subprocess
import time
import zipfile
from flask import Flask, jsonify, request, send_from_directory, Response
import pandas as pd
import json
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all
from config import load_config, save_config, load_swarm, save_swarm
from utils import allowed_file, clear_show_directories

def setup_routes(app):
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        return jsonify(telemetry_data_all_drones)

    @app.route('/send_command', methods=['POST'])
    def send_command():
        command_data = request.get_json()
        drones = load_config()
        send_commands_to_all(drones, command_data)
        return jsonify({'status': 'success', 'message': 'Command sent to all drones'})

    @app.route('/save_config', methods=['POST'])
    def save_config_route():
        config_data = request.get_json()
        save_config(config_data)
        return jsonify({'status': 'success', 'message': 'Configuration saved successfully'})

    @app.route('/get_config', methods=['GET'])
    def get_config():
        config = load_config()
        return Response(json.dumps(config), mimetype='application/json')

    @app.route('/save_swarm', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        save_swarm(swarm_data)
        return jsonify({'status': 'success', 'message': 'Swarm data saved successfully'})

    @app.route('/get_swarm', methods=['GET'])
    def get_swarm():
        swarm = load_swarm()
        return Response(json.dumps(swarm), mimetype='application/json')

    # Additional routes from gcs_with_flask.py
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
                print("Have {} bytes in stdout:\n{}".format(len(completed_process.stdout), completed_process.stdout))
            except subprocess.CalledProcessError as e:
                print(str(e))
                return jsonify({'success': False, 'error': 'Error in running processformation.py', 'details': str(e)})
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Invalid file type. Please upload a ZIP file.'})

    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        print("Trying to serve:", filename)
        print("From directory:", os.path.abspath('shapes/swarm/plots'))
        return send_from_directory('shapes/swarm/plots', filename)

    @app.route('/get-show-plots', methods=['GET'])
    def get_show_plots():
        plots_directory = 'shapes/swarm/plots'
        filenames = [f for f in os.listdir(plots_directory) if f.endswith('.png')]
        if 'all_drones.png' in filenames:
            upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'all_drones.png')))
        else:
            upload_time = "unknown"
        return Response(json.dumps({'filenames': filenames, 'uploadTime': upload_time}), mimetype='application/json')

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
            return Response(json.dumps({"success": True, "firstRow": {"x": first_x, "y": first_y}, "lastRow": {"x": last_x, "y": last_y}}), mimetype='application/json')
        except Exception as e:
            return Response(json.dumps({"success": False, "error": str(e)}), mimetype='application/json')

    # Restoring additional routes from old gcs server
    @app.route('/save-swarm-data', methods=['POST'])
    def save_swarm_data():
        try:
            data = request.json
            # Convert the JSON data to CSV format
            csv_data = "hw_id,follow,offset_n,offset_e,offset_alt\n"
            for drone in data:
                csv_data += f"{drone['hw_id']},{drone['follow']},{drone['offset_n']},{drone['offset_e']},{drone['offset_alt']}\n"

            # Save to swarm.csv
            save_swarm(csv_data.splitlines())

            return {"message": "Data saved successfully"}, 200
        except Exception as e:
            return {"message": f"Error: {str(e)}"}, 500

    @app.route('/save-config-data', methods=['POST'])
    def save_config_data():
        data = request.json
        try:
            # Ensure that all drones have essential properties before writing to CSV
            if not all('hw_id' in drone for drone in data):
                return jsonify({"message": "Incomplete data received. Every drone must have an 'hw_id'."}), 400

            save_config(data)

            return jsonify({"message": "Configuration saved successfully!"}), 200
        except Exception as e:
            return jsonify({"message": "Error saving configuration!", "error": str(e)}), 500

    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm_data():
        swarm = load_swarm()
        return Response(json.dumps(swarm), mimetype='application/json')

    @app.route('/get-config-data', methods=['GET'])
    def get_config_data():
        config = load_config()
        return Response(json.dumps(config), mimetype='application/json')

    drones = load_config()
    start_telemetry_polling(drones)
