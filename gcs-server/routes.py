from flask import Flask, jsonify, request
from telemetry import telemetry_data_all_drones, start_telemetry_polling
from command import send_commands_to_all
from config import load_config, save_config, load_swarm, save_swarm

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
        return jsonify(config)

    @app.route('/save_swarm', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        save_swarm(swarm_data)
        return jsonify({'status': 'success', 'message': 'Swarm data saved successfully'})

    @app.route('/get_swarm', methods=['GET'])
    def get_swarm():
        swarm = load_swarm()
        return jsonify(swarm)

    drones = load_config()
    start_telemetry_polling(drones)
