# gcs-server/routes.py
"""
GCS Server Routes - Simplified Working Version
==============================================
Basic routes with new logging system integrated.
"""

import json
import os
import threading
import sys
import time
from flask import Flask, jsonify, request
from datetime import datetime

# Import existing modules (keeping your current functionality)
from telemetry import telemetry_data_all_drones, data_lock
from command import send_commands_to_all, send_commands_to_selected
from config import load_config, save_config, load_swarm, save_swarm
from heartbeat import handle_heartbeat_post, get_all_heartbeats
from git_status import git_status_data_all_drones, data_lock_git_status

# Import new logging system (with fallback)
try:
    from logging_config import get_logger, log_system_error, log_system_warning
    
    def log_system_event(message: str, level: str = "INFO", component: str = "system"):
        """Log system event using new logging system"""
        get_logger().log_system_event(message, level, component)
        
    LOGGING_AVAILABLE = True
except ImportError:
    # Fallback to standard logging if new system not available
    import logging
    logger = logging.getLogger(__name__)
    
    def log_system_error(message: str, component: str = "system"):
        logger.error(f"[{component}] {message}")
        
    def log_system_warning(message: str, component: str = "system"):
        logger.warning(f"[{component}] {message}")
        
    def log_system_event(message: str, level: str = "INFO", component: str = "system"):
        logger.log(getattr(logging, level, logging.INFO), f"[{component}] {message}")
        
    LOGGING_AVAILABLE = False

def error_response(message: str, status_code: int = 500):
    """Generate consistent error response"""
    log_system_error(f"API Error {status_code}: {message}", "api")
    return jsonify({
        'status': 'error', 
        'message': message,
        'timestamp': datetime.now().isoformat()
    }), status_code

def success_response(data=None, message=None):
    """Generate consistent success response"""
    response = {
        'status': 'success',
        'timestamp': datetime.now().isoformat()
    }
    if message:
        response['message'] = message
    if data is not None:
        response['data'] = data
    return jsonify(response)

def setup_routes(app: Flask):
    """Setup all API routes"""
    
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        """Get current telemetry data"""
        try:
            with data_lock:
                telemetry_copy = telemetry_data_all_drones.copy()
            
            if not telemetry_copy:
                log_system_warning("Telemetry request served but no data available", "api")
            
            return jsonify(telemetry_copy)
        except Exception as e:
            return error_response(f"Failed to retrieve telemetry: {str(e)}")

    @app.route('/submit_command', methods=['POST'])
    def submit_command():
        """Submit command to drones"""
        try:
            command_data = request.get_json()
            if not command_data:
                return error_response("No command data provided", 400)

            command_type = command_data.get('missionType', 'UNKNOWN')
            target_drones = command_data.get('target_drones', [])
            
            log_system_event(
                f"Command '{command_type}' submitted", "INFO", "command"
            )

            # Load drones
            drones = load_config()
            if not drones:
                return error_response("No drones configured", 400)

            # Execute command asynchronously
            def execute_async():
                try:
                    if target_drones:
                        send_commands_to_selected(drones, command_data, target_drones)
                    else:
                        send_commands_to_all(drones, command_data)
                    
                    log_system_event(
                        f"Command '{command_type}' execution completed", "INFO", "command"
                    )
                except Exception as e:
                    log_system_error(f"Command execution failed: {str(e)}", "command")

            threading.Thread(target=execute_async, daemon=True).start()
            
            return success_response(message=f"Command '{command_type}' submitted")

        except Exception as e:
            return error_response(f"Command submission failed: {str(e)}")

    @app.route('/get-config-data', methods=['GET'])
    def get_config():
        """Get drone configuration"""
        try:
            config = load_config()
            return jsonify(config)
        except Exception as e:
            return error_response(f"Failed to load configuration: {str(e)}")

    @app.route('/save-config-data', methods=['POST'])
    def save_config_route():
        """Save drone configuration"""
        try:
            config_data = request.get_json()
            if not config_data:
                return error_response("No configuration data provided", 400)

            save_config(config_data)
            log_system_event(f"Configuration updated: {len(config_data)} drones", "INFO", "config")
            
            return success_response(message="Configuration saved successfully")

        except Exception as e:
            return error_response(f"Configuration save failed: {str(e)}")

    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm():
        """Get swarm formation data"""
        try:
            swarm_data = load_swarm()
            return jsonify(swarm_data)
        except Exception as e:
            return error_response(f"Failed to load swarm data: {str(e)}")

    @app.route('/save-swarm-data', methods=['POST'])
    def save_swarm_route():
        """Save swarm formation data"""
        try:
            swarm_data = request.get_json()
            if not swarm_data:
                return error_response("No swarm data provided", 400)

            save_swarm(swarm_data)
            log_system_event(f"Swarm data updated: {len(swarm_data)} entries", "INFO", "swarm")
            
            return success_response(message="Swarm data saved successfully")

        except Exception as e:
            return error_response(f"Swarm data save failed: {str(e)}")

    @app.route('/git-status', methods=['GET'])
    def get_git_status():
        """Get Git status from all drones"""
        try:
            with data_lock_git_status:
                git_status_copy = git_status_data_all_drones.copy()
            return jsonify(git_status_copy)
        except Exception as e:
            return error_response(f"Failed to get Git status: {str(e)}")

    @app.route('/drone-heartbeat', methods=['POST'])
    def drone_heartbeat():
        """Handle drone heartbeat messages"""
        try:
            return handle_heartbeat_post()
        except Exception as e:
            return error_response(f"Heartbeat processing failed: {str(e)}")

    @app.route('/get-heartbeats', methods=['GET'])
    def get_heartbeats():
        """Get all drone heartbeat data"""
        try:
            return get_all_heartbeats()
        except Exception as e:
            return error_response(f"Failed to get heartbeats: {str(e)}")

    @app.route('/ping', methods=['GET'])
    def ping():
        """Health check endpoint"""
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

    @app.route('/request-new-leader', methods=['POST'])
    def request_new_leader():
        """Handle new leader requests"""
        try:
            data = request.get_json()
            if not data or "hw_id" not in data:
                return error_response("Missing hw_id", 400)

            hw_id = str(data["hw_id"])
            log_system_event(f"New leader request from drone {hw_id}", "INFO", "leader")

            # Load and update swarm data
            swarm_data = load_swarm()
            entry = next((row for row in swarm_data if row.get('hw_id') == hw_id), None)
            
            if entry is None:
                return error_response(f"Drone {hw_id} not found", 404)

            # Update leader information
            entry['follow'] = data.get('follow', entry['follow'])
            entry['offset_n'] = data.get('offset_n', entry['offset_n'])
            entry['offset_e'] = data.get('offset_e', entry['offset_e'])
            entry['offset_alt'] = data.get('offset_alt', entry['offset_alt'])
            entry['body_coord'] = (data.get('body_coord') == '1')

            save_swarm(swarm_data)
            
            return success_response(message=f"Leader updated for drone {hw_id}")

        except Exception as e:
            return error_response(f"Leader request failed: {str(e)}")

    # Log initialization
    log_system_event("API routes initialized successfully", "INFO", "startup")