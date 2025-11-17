# gcs-server/routes.py
"""
GCS Server Routes - Complete Version
===================================
All original functionality preserved with new logging system integrated.
"""

import json
import os
import threading
import sys
import time
import traceback
import zipfile
import requests
import math
import pymap3d as pm
from flask import Flask, jsonify, request, send_file, send_from_directory, current_app, make_response
import pandas as pd
from datetime import datetime

# Import existing modules (preserving all original functionality)
from telemetry import telemetry_data_all_drones, start_telemetry_polling, data_lock
from command import send_commands_to_all, send_commands_to_selected
from config import get_drone_git_status, get_gcs_git_report, load_config, save_config, load_swarm, save_swarm, validate_and_process_config
from utils import allowed_file, clear_show_directories, git_operations, zip_directory
from params import Params
from get_elevation import get_elevation
from origin import compute_origin_from_drone, save_origin, load_origin, calculate_position_deviations, _get_expected_position_from_trajectory
from heartbeat import handle_heartbeat_post, get_all_heartbeats, get_network_info_from_heartbeats
from git_status import git_status_data_all_drones, data_lock_git_status

# Import new logging system with fallback
try:
    from logging_config import get_logger, log_system_error, log_system_warning
    
    def log_system_event(message: str, level: str = "INFO", component: str = "system"):
        """Log system event using new logging system"""
        get_logger().log_system_event(message, level, component)
        
    def log_api_request(endpoint: str, method: str, status_code: int = 200):
        """Professional API request logging with intelligent filtering"""
        from params import Params
        logger = get_logger()

        # Define routine endpoints that shouldn't be logged unless there's an error
        routine_endpoints = ['/telemetry', '/ping', '/drone-heartbeat', '/get-heartbeats']

        # Check if this is a routine endpoint
        is_routine = any(routine in endpoint for routine in routine_endpoints)

        if is_routine and not Params.LOG_ROUTINE_API_CALLS:
            # Only log errors for routine endpoints in professional mode
            if status_code >= Params.API_ERROR_LOG_THRESHOLD:
                level = "ERROR" if status_code >= 500 else "WARNING"
                logger.log_system_event(
                    f"API Error: {method} {endpoint} → {status_code}",
                    level, "api"
                )
        else:
            # Log important non-routine API calls
            if status_code >= 400:
                level = "ERROR" if status_code >= 500 else "WARNING"
                logger.log_system_event(
                    f"API {method} {endpoint} → {status_code}", level, "api"
                )
            elif not is_routine:  # Log successful non-routine calls
                logger.log_system_event(
                    f"✅ API {method} {endpoint} → {status_code}", "INFO", "api"
                )
        
    LOGGING_AVAILABLE = True
except ImportError:
    # Fallback to standard logging
    import logging
    logger = logging.getLogger(__name__)
    
    def log_system_error(message: str, component: str = "system"):
        logger.error(f"[{component}] {message}")
        
    def log_system_warning(message: str, component: str = "system"):
        logger.warning(f"[{component}] {message}")
        
    def log_system_event(message: str, level: str = "INFO", component: str = "system"):
        logger.log(getattr(logging, level, logging.INFO), f"[{component}] {message}")
        
    def log_api_request(endpoint: str, method: str, status_code: int = 200):
        if status_code >= 400:
            logger.log(logging.ERROR if status_code >= 500 else logging.WARNING, 
                      f"API {method} {endpoint} - {status_code}")
        
    LOGGING_AVAILABLE = False

# Configure base directories (preserving original logic)
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

if Params.sim_mode:
    plots_directory = os.path.join(BASE_DIR, 'shapes_sitl/swarm/plots')
    skybrush_dir = os.path.join(BASE_DIR, 'shapes_sitl/swarm/skybrush')
    processed_dir = os.path.join(BASE_DIR, 'shapes_sitl/swarm/processed')
    shapes_dir = os.path.join(BASE_DIR, 'shapes_sitl')
else:
    plots_directory = os.path.join(BASE_DIR, 'shapes/swarm/plots')
    skybrush_dir = os.path.join(BASE_DIR, 'shapes/swarm/skybrush')
    processed_dir = os.path.join(BASE_DIR, 'shapes/swarm/processed')
    shapes_dir = os.path.join(BASE_DIR, 'shapes')

sys.path.append(BASE_DIR)
from process_formation import run_formation_process

# Import new comprehensive metrics engine (after BASE_DIR is defined)
try:
    sys.path.append(os.path.join(BASE_DIR, 'functions'))
    from drone_show_metrics import DroneShowMetrics
    METRICS_AVAILABLE = True
except ImportError as e:
    METRICS_AVAILABLE = False
    # We'll log this later when logging is available

# Preserve original symbols and colors for backward compatibility
RESET = "\x1b[0m"
GREEN = "\x1b[32m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
BLUE = "\x1b[34m"
INFO_SYMBOL = BLUE + "ℹ️" + RESET
ERROR_SYMBOL = RED + "❌" + RESET

def error_response(message, status_code=500):
    """Generate a consistent error response with logging (preserving original)."""
    log_system_error(f"API Error {status_code}: {message}", "api")
    return jsonify({'status': 'error', 'message': message}), status_code

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

def setup_routes(app):
    """Setup all API routes (preserving ALL original functionality)"""
    
    @app.before_request
    def before_request():
        """Log request start"""
        request.start_time = time.time()

    @app.after_request  
    def after_request(response):
        """Log request completion"""
        if hasattr(request, 'start_time'):
            duration = time.time() - request.start_time
            log_api_request(request.path, request.method, response.status_code)
        return response

    # ========================================================================
    # TELEMETRY ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/telemetry', methods=['GET'])
    def get_telemetry():
        # Professional mode: Don't log routine telemetry requests
        # This endpoint is called frequently by the dashboard
        return jsonify(telemetry_data_all_drones)

    # ========================================================================
    # COMMAND ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/submit_command', methods=['POST'])
    def submit_command():
        """
        Endpoint to receive commands from the frontend and process them asynchronously.

        Phase 2 Enhancement: If auto_global_origin is True, include origin data in command payload.
        """
        command_data = request.get_json()
        if not command_data:
            return error_response("No command data provided", 400)

        # Extract target_drones from command_data if provided
        target_drones = command_data.pop('target_drones', None)

        # Phase 2: Include origin data if auto_global_origin is enabled
        auto_global_origin = command_data.get('auto_global_origin', False)
        if auto_global_origin:
            # Fetch current origin from GCS
            try:
                origin = load_origin()
                if origin and origin.get('lat') and origin.get('lon'):
                    command_data['origin'] = {
                        'lat': float(origin['lat']),
                        'lon': float(origin['lon']),
                        'alt': float(origin.get('alt', 0)),
                        'timestamp': origin.get('timestamp', ''),
                        'source': origin.get('alt_source', 'gcs')
                    }
                    log_system_event(
                        f"🌍 Phase 2: Including origin in command (lat={origin['lat']:.6f}, lon={origin['lon']:.6f})",
                        "INFO", "command"
                    )
                else:
                    log_system_event(
                        "⚠️ Phase 2: auto_global_origin=True but origin not set! Drones will fetch from GCS.",
                        "WARNING", "command"
                    )
            except Exception as e:
                log_system_error(f"Phase 2: Failed to load origin for command: {e}", "command")

        # Professional command logging
        if target_drones:
            log_system_event(f"⚡ Command '{command_data.get('action', 'unknown')}' received for {len(target_drones)} selected drones", "INFO", "command")
        else:
            log_system_event(f"⚡ Command '{command_data.get('action', 'unknown')}' received for all drones", "INFO", "command")

        try:
            drones = load_config()
            if not drones:
                return error_response("No drones found in the configuration", 500)

            # Start processing the command in a new thread
            if target_drones:
                thread = threading.Thread(target=process_command_async, args=(drones, command_data, target_drones))
            else:
                thread = threading.Thread(target=process_command_async, args=(drones, command_data))

            thread.daemon = True
            thread.start()

            # Don't log routine command processing start - reduces noise
            
            response_data = {
                'status': 'success',
                'message': "Command received and is being processed."
            }
            return jsonify(response_data), 200
        except Exception as e:
            log_system_error(f"Error initiating command processing: {e}", "command")
            return error_response(f"Error initiating command processing: {e}")

    def process_command_async(drones, command_data, target_drones=None):
        """
        Function to process the command asynchronously (preserving original).
        """
        try:
            start_time = time.time()

            # Choose appropriate sending function based on target_drones
            if target_drones:
                results = send_commands_to_selected(drones, command_data, target_drones)
                total_count = len(target_drones)
            else:
                results = send_commands_to_all(drones, command_data)
                total_count = len(drones)

            elapsed_time = time.time() - start_time
            success_count = sum(results.values())

            # Professional command completion logging
            if success_count == total_count:
                log_system_event(
                    f"✅ Command completed successfully on all {total_count} drones ({elapsed_time:.2f}s)",
                    "INFO", "command"
                )
            else:
                log_system_event(
                    f"⚠️ Command partially completed: {success_count}/{total_count} drones succeeded ({elapsed_time:.2f}s)",
                    "WARNING", "command"
                )
        except Exception as e:
            log_system_error(f"Error processing command asynchronously: {e}", "command")

    # ========================================================================
    # CONFIGURATION ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/get-trajectory-first-row', methods=['GET'])
    def get_trajectory_first_row():
        """
        Get expected position (first row) from trajectory CSV file.
        Used by auto-accept pos_id feature to fetch correct x,y coordinates.
        """
        try:
            pos_id = request.args.get('pos_id')
            if not pos_id:
                return error_response("pos_id parameter required", 400)

            pos_id = int(pos_id)
            sim_mode = getattr(Params, 'sim_mode', False)

            # Get expected position from trajectory CSV
            north, east = _get_expected_position_from_trajectory(pos_id, sim_mode)

            if north is None or east is None:
                return error_response(
                    f"Trajectory file not found for pos_id={pos_id}",
                    404
                )

            return jsonify({
                "pos_id": pos_id,
                "north": north,
                "east": east,
                "source": f"Drone {pos_id}.csv (first waypoint)"
            })

        except ValueError as e:
            return error_response(f"Invalid pos_id: {e}", 400)
        except Exception as e:
            log_system_error(f"Error fetching trajectory coordinates: {e}", "config")
            return error_response(f"Error fetching trajectory data: {e}")

    @app.route('/validate-config', methods=['POST'])
    def validate_config_route():
        """
        Validate configuration and process x,y coordinates from trajectory CSV.
        Returns validation report WITHOUT saving to file.
        Used by UI to show review dialog before final save.
        """
        config_data = request.get_json()
        if not config_data:
            return error_response("No configuration data provided", 400)

        log_system_event("🔍 Configuration validation requested", "INFO", "config")

        try:
            # Validate config_data format
            if not isinstance(config_data, list) or not all(isinstance(drone, dict) for drone in config_data):
                raise ValueError("Invalid configuration data format")

            # Validate and process config
            sim_mode = getattr(Params, 'sim_mode', False)
            report = validate_and_process_config(config_data, sim_mode)

            log_system_event(
                f"✅ Validation complete: {report['summary']['duplicates_count']} duplicates, "
                f"{report['summary']['missing_trajectories_count']} missing trajectories, "
                f"{report['summary']['role_swaps_count']} role swaps",
                "INFO",
                "config"
            )

            return jsonify(report)

        except Exception as e:
            log_system_error(f"Error validating configuration: {e}", "config")
            return error_response(f"Error validating configuration: {e}")

    @app.route('/save-config-data', methods=['POST'])
    def save_config_route():
        config_data = request.get_json()
        if not config_data:
            return error_response("No configuration data provided", 400)

        log_system_event("💾 Configuration update received", "INFO", "config")

        try:
            # Validate config_data
            if not isinstance(config_data, list) or not all(isinstance(drone, dict) for drone in config_data):
                raise ValueError("Invalid configuration data format")

            # Process config with trajectory-based x,y updates
            sim_mode = getattr(Params, 'sim_mode', False)
            report = validate_and_process_config(config_data, sim_mode)

            # Save the processed configuration (with trajectory-based x,y)
            save_config(report['updated_config'])
            log_system_event("✅ Configuration saved successfully", "INFO", "config")

            git_info = None
            # If auto push to Git is enabled, perform Git operations
            if Params.GIT_AUTO_PUSH:
                log_system_event("Git auto-push is enabled. Attempting to push configuration changes to repository.", "INFO", "config")
                git_result = git_operations(
                    BASE_DIR,
                    f"Update configuration: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if git_result.get('success'):
                    log_system_event("Git operations successful.", "INFO", "config")
                else:
                    log_system_error(f"Git operations failed: {git_result.get('message')}", "config")
                git_info = git_result

            # Return a success message, including Git info if applicable
            response_data = {'status': 'success', 'message': 'Configuration saved successfully'}
            if git_info:
                response_data['git_info'] = git_info

            return jsonify(response_data)
        except Exception as e:
            log_system_error(f"Error saving configuration: {e}", "config")
            return error_response(f"Error saving configuration: {e}")

    @app.route('/get-config-data', methods=['GET'])
    def get_config():
        # Don't log routine config requests - reduces noise
        try:
            config = load_config()
            return jsonify(config)
        except Exception as e:
            return error_response(f"Error loading configuration: {e}")

    # ========================================================================
    # SWARM ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/save-swarm-data', methods=['POST'])
    def save_swarm_route():
        swarm_data = request.get_json()
        if not swarm_data:
            return error_response("No swarm data provided", 400)

        log_system_event("💾 Swarm configuration update received", "INFO", "swarm")
        try:
            save_swarm(swarm_data)
            log_system_event("✅ Swarm configuration saved successfully", "INFO", "swarm")

            # Determine Git push behavior
            commit_override = request.args.get('commit')
            should_commit = (
                commit_override.lower() == 'true'
                if commit_override is not None
                else Params.GIT_AUTO_PUSH
            )

            git_info = None
            if should_commit:
                log_system_event("Git commit & push triggered.", "INFO", "swarm")
                try:
                    git_result = git_operations(
                        BASE_DIR,
                        f"Update swarm data: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    git_info = git_result
                    if git_result.get('success'):
                        log_system_event("Git operations successful.", "INFO", "swarm")
                    else:
                        log_system_error(f"Git operations failed: {git_result.get('message')}", "swarm")
                except Exception as git_exc:
                    log_system_error(f"Exception during Git operations: {str(git_exc)}", "swarm")
                    git_info = {'success': False, 'message': str(git_exc), 'output': ''}

            response = {'status': 'success', 'message': 'Swarm data saved successfully'}
            if git_info:
                response['git_info'] = git_info

            return jsonify(response), 200

        except Exception as e:
            log_system_error(f"Error saving swarm data: {str(e)}", "swarm")
            return error_response(str(e), 500)
    
    @app.route('/get-swarm-data', methods=['GET'])
    def get_swarm():
        # Don't log routine swarm data requests - reduces noise
        try:
            swarm = load_swarm()
            return jsonify(swarm)
        except Exception as e:
            return error_response(f"Error loading swarm data: {e}")

    # ========================================================================
    # SHOW MANAGEMENT ENDPOINTS (preserving ALL original functionality)
    # ========================================================================
    
    @app.route('/import-show', methods=['POST', 'OPTIONS'])
    def import_show():
        """
        Endpoint to handle the uploading and processing of drone show files:
          1) Clears the SITL or real show directories (depending on sim_mode).
          2) Saves the uploaded zip.
          3) Extracts it into the correct skybrush_dir.
          4) Calls run_formation_process.
          5) Optionally pushes changes to Git.
        """
        # Handle preflight OPTIONS request for CORS
        if request.method == 'OPTIONS':
            response = make_response()
            response.headers.add("Access-Control-Allow-Origin", "*")
            response.headers.add('Access-Control-Allow-Headers', "*")
            response.headers.add('Access-Control-Allow-Methods', "*")
            return response

        file = request.files.get('file')
        log_system_event(f"📤 Show import requested: {file.filename if file else 'No file'}", "INFO", "show")
        if not file or file.filename == '':
            log_system_warning("No file part or empty filename", "show")
            return error_response('No file part or empty filename', 400)

        try:
            # 1) Clear the correct SITL/real show directories
            clear_show_directories(BASE_DIR)

            # 2) Save the uploaded zip into a temp folder
            zip_path = os.path.join(BASE_DIR, 'temp', 'uploaded.zip')
            os.makedirs(os.path.dirname(zip_path), exist_ok=True)
            file.save(zip_path)

            # 3) Extract the zip into the correct skybrush folder
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(skybrush_dir)
            os.remove(zip_path)

            # 4) Process formation with enhanced logging
            log_system_event(f"⚙️ Processing show files from {skybrush_dir}", "INFO", "show")

            # Count input files before processing
            input_files = [f for f in os.listdir(skybrush_dir) if f.endswith('.csv')]
            input_count = len(input_files)
            log_system_event(f"📊 Input: {input_count} drone CSV files detected", "INFO", "show")

            output = run_formation_process(BASE_DIR)

            # Verify processing results
            processed_files = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]
            processed_count = len(processed_files)

            if processed_count == input_count:
                log_system_event(f"✅ Show processing completed successfully: {processed_count}/{input_count} drones processed", "INFO", "show")
            else:
                log_system_error(f"⚠️ Processing mismatch: {processed_count}/{input_count} drones processed", "show")
                # Continue anyway but log the issue

            # 5) Calculate comprehensive metrics (new feature)
            comprehensive_metrics = None
            if METRICS_AVAILABLE:
                try:
                    log_system_event("📊 Calculating comprehensive show metrics", "INFO", "show")
                    metrics_engine = DroneShowMetrics(processed_dir)
                    comprehensive_metrics = metrics_engine.calculate_comprehensive_metrics()
                    
                    # Save metrics to file for later retrieval with show info
                    upload_time = datetime.now().isoformat()
                    metrics_file = metrics_engine.save_metrics_to_file(
                        comprehensive_metrics, 
                        show_filename=file.filename,
                        upload_datetime=upload_time
                    )
                    if metrics_file:
                        log_system_event(f"✅ Show metrics saved to {metrics_file}", "INFO", "show")
                    else:
                        log_system_warning("Failed to save comprehensive metrics", "show")
                except Exception as metrics_error:
                    log_system_error(f"Error calculating comprehensive metrics: {metrics_error}", "show")
                    comprehensive_metrics = {'error': str(metrics_error)}

            # 6) Optionally do Git commit/push
            if Params.GIT_AUTO_PUSH:
                log_system_event("Git auto-push is enabled. Attempting to push show changes to repository.", "INFO", "show")
                git_result = git_operations(
                    BASE_DIR,
                    f"Update from upload: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {file.filename}"
                )

                # ====================================================================
                # CRITICAL VERIFICATION: Check git tracking status
                # ====================================================================
                git_tracking_stats = {
                    'committed_count': 0,
                    'ignored_count': 0,
                    'untracked_files': [],
                    'tracking_complete': False
                }

                try:
                    from git import Repo
                    repo = Repo(BASE_DIR)

                    # Get tracked processed files
                    tracked_processed = repo.git.ls_files('shapes/swarm/processed').split('\n') if repo.git.ls_files('shapes/swarm/processed') else []
                    tracked_processed = [f for f in tracked_processed if f.endswith('.csv')]

                    # Get filesystem processed files
                    filesystem_processed = [f for f in os.listdir(processed_dir) if f.endswith('.csv')]

                    git_tracking_stats['committed_count'] = len(tracked_processed)
                    git_tracking_stats['ignored_count'] = len(filesystem_processed) - len(tracked_processed)

                    # Identify untracked files
                    tracked_basenames = {os.path.basename(f) for f in tracked_processed}
                    filesystem_basenames = set(filesystem_processed)
                    untracked = filesystem_basenames - tracked_basenames

                    if untracked:
                        git_tracking_stats['untracked_files'] = sorted(list(untracked))
                        log_system_warning(
                            f"⚠️ Git tracking incomplete: {len(untracked)} processed files NOT tracked: {untracked}",
                            "show"
                        )
                    else:
                        git_tracking_stats['tracking_complete'] = True

                except Exception as track_error:
                    log_system_warning(f"Could not verify git tracking: {track_error}", "show")

                if git_result.get('success'):
                    if git_tracking_stats['tracking_complete']:
                        log_system_event(f"✅ Git operations successful. {git_tracking_stats['committed_count']} drone files tracked.", "INFO", "show")
                    else:
                        log_system_warning(f"⚠️ Git succeeded but {git_tracking_stats['ignored_count']} files not tracked!", "show")
                else:
                    log_system_error(f"Git operations failed: {git_result.get('message')}", "show")
                
                # Calculate show health status
                show_health_status = "healthy"
                health_issues = []

                if processed_count != input_count:
                    show_health_status = "error"
                    health_issues.append(f"Processing incomplete: {processed_count}/{input_count} drones")

                if not git_tracking_stats['tracking_complete']:
                    show_health_status = "warning" if show_health_status == "healthy" else "error"
                    health_issues.append(f"{git_tracking_stats['ignored_count']} files not tracked in git")

                response_data = {
                    'success': True,
                    'message': output,
                    'git_info': git_result,
                    'processing_stats': {
                        'input_count': input_count,
                        'processed_count': processed_count,
                        'validation_passed': processed_count == input_count
                    },
                    'git_tracking_stats': git_tracking_stats,
                    'show_health': {
                        'status': show_health_status,
                        'issues': health_issues
                    }
                }
                if comprehensive_metrics:
                    response_data['comprehensive_metrics'] = comprehensive_metrics

                return jsonify(response_data)
            else:
                # No git push, but still validate processing
                show_health_status = "healthy" if processed_count == input_count else "error"
                health_issues = [] if processed_count == input_count else [f"Processing incomplete: {processed_count}/{input_count} drones"]

                response_data = {
                    'success': True,
                    'message': output,
                    'processing_stats': {
                        'input_count': input_count,
                        'processed_count': processed_count,
                        'validation_passed': processed_count == input_count
                    },
                    'show_health': {
                        'status': show_health_status,
                        'issues': health_issues
                    }
                }
                if comprehensive_metrics:
                    response_data['comprehensive_metrics'] = comprehensive_metrics

                return jsonify(response_data)
        except Exception as e:
            log_system_error(f"Unexpected error during show import: {traceback.format_exc()}", "show")
            return error_response(f"Unexpected error during show import: {traceback.format_exc()}")

    @app.route('/download-raw-show', methods=['GET'])
    def download_raw_show():
        try:
            zip_file = zip_directory(skybrush_dir, os.path.join(BASE_DIR, 'temp/raw_show'))
            return send_file(zip_file, as_attachment=True, download_name='raw_show.zip')
        except Exception as e:
            return error_response(f"Error creating raw show zip: {e}")

    @app.route('/download-processed-show', methods=['GET'])
    def download_processed_show():
        try:
            zip_file = zip_directory(processed_dir, os.path.join(BASE_DIR, 'temp/processed_show'))
            return send_file(zip_file, as_attachment=True, download_name='processed_show.zip')
        except Exception as e:
            return error_response(f"Error creating processed show zip: {e}")
        
    @app.route('/get-show-info', methods=['GET'])
    def get_show_info():
        try:
            check_all = True

            # Find all Drone CSV files
            drone_csv_files = [f for f in os.listdir(skybrush_dir) 
                            if f.startswith('Drone ') and f.endswith('.csv')]
            
            if not drone_csv_files:
                return error_response("No drone CSV files found")

            # If check_all is False, filter to just "Drone 1.csv" (or first in the list)
            if not check_all:
                drone_csv_files = [drone_csv_files[0]]

            drone_count = len(drone_csv_files)

            max_duration_ms = 0.0
            max_altitude = 0.0

            # Iterate over each CSV to find the maximum duration and altitude
            for csv_file in drone_csv_files:
                csv_path = os.path.join(skybrush_dir, csv_file)

                with open(csv_path, 'r') as file:
                    # Skip the header
                    next(file)

                    lines = file.readlines()
                    if not lines:
                        continue

                    # Last line for time
                    last_line = lines[-1].strip().split(',')
                    duration_ms = float(last_line[0])
                    # Update max duration
                    if duration_ms > max_duration_ms:
                        max_duration_ms = duration_ms

                    # Find max altitude in this CSV
                    for line in lines:
                        parts = line.strip().split(',')
                        if len(parts) < 4:
                            continue
                        z_val = float(parts[3])  # 'z [m]' is the 4th column
                        if z_val > max_altitude:
                            max_altitude = z_val

            # Convert max duration to minutes / seconds
            duration_minutes = max_duration_ms / 60000
            duration_seconds = (max_duration_ms % 60000) / 1000
            
            return jsonify({
                'drone_count': drone_count,
                'duration_ms': max_duration_ms,
                'duration_minutes': round(duration_minutes, 2),
                'duration_seconds': round(duration_seconds, 2),
                'max_altitude': round(max_altitude, 2)
            })

        except FileNotFoundError:
            return error_response("Drone CSV files not found in skybrush directory")
        except Exception as e:
            return error_response(f"Error reading show info: {e}")

    @app.route('/get-comprehensive-metrics', methods=['GET'])
    def get_comprehensive_metrics():
        """
        NEW ENDPOINT: Retrieve comprehensive trajectory analysis metrics
        """
        log_system_event("Comprehensive metrics requested", "INFO", "show")
        
        if not METRICS_AVAILABLE:
            return error_response("Enhanced metrics engine not available", 503)
        
        try:
            # Try to load from saved file first (now in swarm directory)
            swarm_dir = os.path.join(BASE_DIR, base_folder, 'swarm') if 'base_folder' in locals() else os.path.join(BASE_DIR, 'shapes/swarm')
            metrics_file = os.path.join(swarm_dir, 'comprehensive_metrics.json')
            if os.path.exists(metrics_file):
                with open(metrics_file, 'r') as f:
                    metrics_data = json.load(f)
                log_system_event("Comprehensive metrics loaded from file", "INFO", "show")
                return jsonify(metrics_data)
            
            # If no saved file, calculate on-demand
            log_system_event("Calculating comprehensive metrics on-demand", "INFO", "show")
            metrics_engine = DroneShowMetrics(processed_dir)
            comprehensive_metrics = metrics_engine.calculate_comprehensive_metrics()
            
            # Save for future requests
            metrics_engine.save_metrics_to_file(comprehensive_metrics)
            
            return jsonify(comprehensive_metrics)
            
        except Exception as e:
            log_system_error(f"Error retrieving comprehensive metrics: {e}", "show")
            return error_response(f"Error calculating comprehensive metrics: {e}")

    @app.route('/get-safety-report', methods=['GET'])
    def get_safety_report():
        """
        NEW ENDPOINT: Get detailed safety analysis report
        """
        log_system_event("Safety report requested", "INFO", "show")
        
        if not METRICS_AVAILABLE:
            return error_response("Enhanced metrics engine not available", 503)
        
        try:
            metrics_engine = DroneShowMetrics(processed_dir)
            if not metrics_engine.load_drone_data():
                return error_response("No drone data available for safety analysis", 404)
            
            safety_metrics = metrics_engine.calculate_safety_metrics()
            
            return jsonify({
                'safety_analysis': safety_metrics,
                'recommendations': [
                    'Maintain minimum 2m separation between drones',
                    'Ensure ground clearance > 1m at all times',
                    'Monitor collision warnings during flight'
                ] if safety_metrics.get('collision_warnings_count', 0) > 0 else [
                    'Safety analysis complete - no issues detected',
                    'Formation maintains safe separation distances'
                ]
            })
            
        except Exception as e:
            log_system_error(f"Error generating safety report: {e}", "show")
            return error_response(f"Error generating safety report: {e}")

    @app.route('/validate-trajectory', methods=['POST'])
    def validate_trajectory():
        """
        NEW ENDPOINT: Real-time trajectory validation
        """
        log_system_event("Trajectory validation requested", "INFO", "show")
        
        if not METRICS_AVAILABLE:
            return error_response("Enhanced metrics engine not available", 503)
        
        try:
            metrics_engine = DroneShowMetrics(processed_dir)
            if not metrics_engine.load_drone_data():
                return error_response("No drone data available for validation", 404)
            
            # Calculate all metrics for validation
            all_metrics = metrics_engine.calculate_comprehensive_metrics()
            
            # Determine overall validation status
            validation_status = "PASS"
            issues = []
            
            if 'safety_metrics' in all_metrics:
                safety = all_metrics['safety_metrics']
                if safety.get('safety_status') != 'SAFE':
                    validation_status = "FAIL"
                    issues.append(f"Safety issue: {safety.get('safety_status')}")
                
                if safety.get('collision_warnings_count', 0) > 0:
                    validation_status = "WARNING"
                    issues.append(f"{safety['collision_warnings_count']} collision warnings")
            
            if 'performance_metrics' in all_metrics:
                perf = all_metrics['performance_metrics']
                if perf.get('max_velocity_ms', 0) > 15:  # 15 m/s limit
                    validation_status = "WARNING"
                    issues.append(f"High velocity: {perf['max_velocity_ms']} m/s")
            
            return jsonify({
                'validation_status': validation_status,
                'issues': issues,
                'metrics_summary': {
                    'safety_status': all_metrics.get('safety_metrics', {}).get('safety_status', 'Unknown'),
                    'max_velocity': all_metrics.get('performance_metrics', {}).get('max_velocity_ms', 0),
                    'formation_quality': all_metrics.get('formation_metrics', {}).get('formation_quality', 'Unknown')
                }
            })
            
        except Exception as e:
            log_system_error(f"Error validating trajectory: {e}", "show")
            return error_response(f"Error validating trajectory: {e}")

    @app.route('/deploy-show', methods=['POST'])
    def deploy_show():
        """
        NEW ENDPOINT: Deploy show changes to git repository for drone fleet
        """
        log_system_event("🚀 Show deployment initiated", "INFO", "deploy")
        
        try:
            data = request.get_json() or {}
            commit_message = data.get('message', f"Deploy drone show: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Perform git operations to commit and push changes
            git_result = git_operations(BASE_DIR, commit_message)
            
            if git_result.get('success'):
                log_system_event("✅ Show deployed successfully to drone fleet", "INFO", "deploy")
                return jsonify({
                    'success': True,
                    'message': 'Show deployed successfully to drone fleet',
                    'git_info': git_result
                })
            else:
                log_system_error(f"Show deployment failed: {git_result.get('message')}", "deploy")
                return error_response(f"Deployment failed: {git_result.get('message')}")
                
        except Exception as e:
            log_system_error(f"Error during show deployment: {e}", "deploy")
            return error_response(f"Error during deployment: {e}")

    @app.route('/get-show-plots/<filename>')
    def send_image(filename):
        # Don't log routine image requests - reduces noise
        try:
            return send_from_directory(plots_directory, filename)
        except Exception as e:
            return error_response(f"Error sending image: {e}", 404)

    @app.route('/get-show-plots', methods=['GET'])
    def get_show_plots():
        # Don't log routine plot list requests - reduces noise
        try:
            if not os.path.exists(plots_directory):
                os.makedirs(plots_directory)

            filenames = [f for f in os.listdir(plots_directory) if f.endswith('.jpg')]
            upload_time = "unknown"
            if 'combined_drone_paths.png' in filenames:
                upload_time = time.ctime(os.path.getctime(os.path.join(plots_directory, 'combined_drone_paths.jpg')))

            return jsonify({'filenames': filenames, 'uploadTime': upload_time})
        except Exception as e:
            return error_response(f"Failed to list directory: {e}")

    @app.route('/get-custom-show-image', methods=['GET'])
    def get_custom_show_image():
        """
        Endpoint to get the custom drone show image.
        The image is expected to be located at shapes/active.png.
        """
        try:
            image_path = os.path.join(shapes_dir, 'trajectory_plot.png')
            print("Debug: Image path being used:", image_path)  # Debug statement
            if os.path.exists(image_path):
                return send_file(image_path, mimetype='image/png', as_attachment=False)
            else:
                return jsonify({'error': f'Custom show image not found at {image_path}'}), 404
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    # ========================================================================
    # ELEVATION AND ORIGIN ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/elevation', methods=['GET'])
    def elevation_route():
        lat = request.args.get('lat')
        lon = request.args.get('lon')

        if lat is None or lon is None:
            log_system_error("Latitude and Longitude must be provided", "elevation")
            return jsonify({'error': 'Latitude and Longitude must be provided'}), 400

        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            log_system_error("Invalid latitude or longitude format", "elevation")
            return jsonify({'error': 'Invalid latitude or longitude format'}), 400

        elevation_data = get_elevation(lat, lon)
        if elevation_data:
            return jsonify(elevation_data)
        else:
            return jsonify({'error': 'Failed to fetch elevation data'}), 500

    @app.route('/set-origin', methods=['POST'])
    def set_origin():
        """
        Set origin coordinates with optional altitude support.

        Request body:
          - lat: float (required) - Latitude in decimal degrees
          - lon: float (required) - Longitude in decimal degrees
          - alt: float (optional) - MSL altitude in meters
          - alt_source: str (optional) - 'manual' | 'drone' | 'elevation_api'
        """
        data = request.get_json()
        lat = data.get('lat')
        lon = data.get('lon')

        if lat is None or lon is None:
            log_system_error("Latitude and longitude are required", "origin")
            return jsonify({'status': 'error', 'message': 'Latitude and longitude are required'}), 400

        try:
            # Save with altitude support (v2 schema) - save_origin handles defaults
            save_origin(data)

            alt = data.get('alt', 0)
            alt_source = data.get('alt_source', 'manual')

            log_system_event(
                f"Origin set to lat={lat}, lon={lon}, alt={alt}m (source: {alt_source})",
                "INFO", "origin"
            )

            return jsonify({
                'status': 'success',
                'message': 'Origin saved',
                'data': {
                    'lat': float(lat),
                    'lon': float(lon),
                    'alt': float(alt),
                    'alt_source': alt_source
                }
            })

        except Exception as e:
            log_system_error(f"Error saving origin: {e}", "origin")
            return jsonify({'status': 'error', 'message': 'Error saving origin'}), 500

    @app.route('/get-origin', methods=['GET'])
    def get_origin():
        """
        Get origin coordinates (v2 schema with altitude).

        Returns:
          - lat: float or empty string
          - lon: float or empty string
          - alt: float (default 0)
          - alt_source: str
          - timestamp: ISO string
          - version: int
        """
        try:
            data = load_origin()  # Now returns v2 schema with altitude

            # Return complete v2 schema (backwards compatible)
            return jsonify(data)

        except Exception as e:
            log_system_error(f"Error loading origin: {e}", "origin")
            return jsonify({'status': 'error', 'message': 'Error loading origin'}), 500

    @app.route('/get-origin-for-drone', methods=['GET'])
    def get_origin_for_drone():
        """
        Lightweight endpoint for drones to fetch origin before flight (Phase 2).

        This endpoint is optimized for drone pre-flight origin fetching during
        Phase 2 Auto Global Origin Correction mode. Returns minimal data required
        for coordinate transformation with clear error handling.

        Returns:
            Success (200):
                {
                    "lat": float,           # Latitude in degrees
                    "lon": float,           # Longitude in degrees
                    "alt": float,           # Altitude MSL in meters
                    "timestamp": str,       # ISO 8601 timestamp
                    "source": str           # Origin source: "manual", "drone", "elevation_api"
                }

            Error (404):
                {
                    "error": str,           # Error message
                    "message": str          # Detailed explanation
                }

        Usage:
            Drones call this endpoint during run_drone() before arming to fetch
            the shared drone show origin. Falls back to cache if unavailable.
        """
        try:
            # Load origin using existing origin management function
            origin = load_origin()

            # Validate origin is set
            if not origin or 'lat' not in origin or 'lon' not in origin:
                return jsonify({
                    'error': 'Origin not set',
                    'message': 'Drone show origin has not been configured in GCS. Use dashboard to set origin.'
                }), 404

            # Validate coordinates are not empty
            if not origin['lat'] or not origin['lon']:
                return jsonify({
                    'error': 'Origin incomplete',
                    'message': 'Origin coordinates are empty. Please reconfigure origin in GCS.'
                }), 404

            # Return minimal data required for drone coordinate transformation
            return jsonify({
                'lat': float(origin['lat']),
                'lon': float(origin['lon']),
                'alt': float(origin.get('alt', 0)),  # Default to 0 if altitude not set
                'timestamp': origin.get('timestamp', ''),
                'source': origin.get('alt_source', 'unknown')
            }), 200

        except Exception as e:
            log_system_error(f"Error in get-origin-for-drone: {e}", "origin")
            return jsonify({
                'error': 'Server error',
                'message': f'Failed to retrieve origin: {str(e)}'
            }), 500

    @app.route('/get-position-deviations', methods=['GET'])
    def get_position_deviations():
        """
        Calculate position deviations for all drones with comprehensive status reporting.

        Compares expected positions (from config + origin) with current GPS positions.

        Returns:
          - Per-drone deviation data with GPS quality indicators
          - Summary statistics
          - Status classifications (ok/warning/error/no_telemetry)
        """
        try:
            # Load origin
            origin = load_origin()
            if not origin or 'lat' not in origin or 'lon' not in origin or not origin['lat'] or not origin['lon']:
                return jsonify({
                    "status": "error",
                    "error": "Origin coordinates not set on GCS"
                }), 400

            origin_lat = float(origin['lat'])
            origin_lon = float(origin['lon'])
            origin_alt = float(origin.get('alt', 0))

            # Load drone config
            drones_config = load_config()
            if not drones_config:
                return jsonify({
                    "status": "error",
                    "error": "No drones configuration found"
                }), 500

            # Get telemetry data (thread-safe)
            with data_lock:
                telemetry_data_copy = telemetry_data_all_drones.copy()

            # Calculate deviations with enhanced data structure
            deviations = {}
            summary_stats = {
                'total_drones': len(drones_config),
                'online': 0,
                'within_threshold': 0,
                'warnings': 0,
                'errors': 0,
                'no_telemetry': 0,
                'best_deviation': float('inf'),
                'worst_deviation': 0,
                'total_deviation_sum': 0
            }

            threshold_warning = Params.acceptable_deviation  # e.g., 2.0m
            threshold_error = threshold_warning * 2.5  # e.g., 5.0m

            for drone in drones_config:
                hw_id = drone.get('hw_id')
                pos_id = drone.get('pos_id')

                if not hw_id:
                    continue

                # CRITICAL FIX: Use pos_id to get expected position from trajectory CSV
                # When hw_id ≠ pos_id, the drone executes pos_id's trajectory, so expected
                # position must come from trajectory file, NOT from config.csv x,y values
                if not pos_id:
                    # Fallback: if no pos_id defined, assume pos_id == hw_id
                    pos_id = hw_id

                # Detect simulation mode from Params
                sim_mode = getattr(Params, 'sim_mode', False)

                # Get expected position from trajectory CSV (single source of truth)
                expected_north, expected_east = _get_expected_position_from_trajectory(pos_id, sim_mode)

                if expected_north is None or expected_east is None:
                    deviations[hw_id] = {
                        "hw_id": hw_id,
                        "pos_id": pos_id,
                        "status": "error",
                        "message": f"Could not read trajectory file for pos_id={pos_id}"
                    }
                    summary_stats['errors'] += 1
                    continue

                # Calculate expected GPS position
                try:
                    expected_lat, expected_lon, expected_alt = pm.ned2geodetic(
                        expected_north, expected_east, 0,
                        origin_lat, origin_lon, origin_alt
                    )
                except Exception as e:
                    deviations[hw_id] = {
                        "status": "error",
                        "message": f"Coordinate conversion error: {str(e)}"
                    }
                    summary_stats['errors'] += 1
                    continue

                # Get current position from telemetry
                drone_telemetry = telemetry_data_copy.get(hw_id, {})
                current_lat = drone_telemetry.get('Position_Lat')
                current_lon = drone_telemetry.get('Position_Long')
                current_alt = drone_telemetry.get('Position_Alt')

                # Check if telemetry available
                if current_lat is None or current_lon is None:
                    deviations[hw_id] = {
                        "hw_id": hw_id,
                        "pos_id": drone.get('pos_id', hw_id),
                        "expected": {
                            "lat": expected_lat,
                            "lon": expected_lon,
                            "north": expected_north,
                            "east": expected_east
                        },
                        "current": None,
                        "deviation": None,
                        "status": "no_telemetry",
                        "message": "No GPS data available"
                    }
                    summary_stats['no_telemetry'] += 1
                    continue

                # Parse telemetry values
                try:
                    current_lat = float(current_lat)
                    current_lon = float(current_lon)
                    current_alt = float(current_alt) if current_alt is not None else None
                except (TypeError, ValueError):
                    deviations[hw_id] = {
                        "hw_id": hw_id,
                        "pos_id": drone.get('pos_id', hw_id),
                        "expected": {
                            "lat": expected_lat,
                            "lon": expected_lon,
                            "north": expected_north,
                            "east": expected_east
                        },
                        "current": None,
                        "deviation": None,
                        "status": "error",
                        "message": "Invalid telemetry data"
                    }
                    summary_stats['errors'] += 1
                    continue

                # Convert current GPS to NED
                try:
                    current_north, current_east, current_down = pm.geodetic2ned(
                        current_lat, current_lon, current_alt or origin_alt,
                        origin_lat, origin_lon, origin_alt
                    )
                except Exception as e:
                    deviations[hw_id] = {
                        "hw_id": hw_id,
                        "pos_id": drone.get('pos_id', hw_id),
                        "status": "error",
                        "message": f"NED conversion error: {str(e)}"
                    }
                    summary_stats['errors'] += 1
                    continue

                # Calculate deviations
                deviation_north = current_north - expected_north
                deviation_east = current_east - expected_east
                deviation_horizontal = math.sqrt(deviation_north**2 + deviation_east**2)

                deviation_vertical = abs(current_down) if current_alt is not None else 0
                deviation_total_3d = math.sqrt(deviation_north**2 + deviation_east**2 + deviation_vertical**2)

                # Determine GPS quality - check fix_type first (most reliable indicator)
                gps_fix_type = drone_telemetry.get('Gps_Fix_Type', drone_telemetry.get('gps_fix_type', 0))
                satellites = drone_telemetry.get('Satellites', drone_telemetry.get('Satellites_Visible', 0))
                hdop = drone_telemetry.get('HDOP', drone_telemetry.get('Hdop', 99))

                try:
                    gps_fix_type = int(gps_fix_type)
                    satellites = int(satellites)
                    hdop = float(hdop)
                except:
                    gps_fix_type = 0
                    satellites = 0
                    hdop = 99

                # GPS quality classification - prioritize fix_type (MAVLink standard)
                # Fix types: 0=No GPS, 1=No Fix, 2=2D Fix, 3=3D Fix, 4=DGPS, 5=RTK Float, 6=RTK Fixed
                if gps_fix_type >= 6:
                    # RTK Fixed - best quality
                    gps_quality = 'excellent'
                elif gps_fix_type >= 5:
                    # RTK Float - excellent
                    gps_quality = 'excellent'
                elif gps_fix_type >= 4:
                    # DGPS - very good
                    gps_quality = 'good'
                elif gps_fix_type >= 3:
                    # 3D Fix - good quality (use satellites/HDOP to refine)
                    if satellites >= 10 and hdop < 1.5:
                        gps_quality = 'excellent'
                    elif satellites >= 8 and hdop < 2.0:
                        gps_quality = 'good'
                    elif satellites >= 6 and hdop < 5.0:
                        gps_quality = 'fair'
                    else:
                        # 3D fix but lower satellite count or higher HDOP - still acceptable
                        gps_quality = 'fair'
                elif gps_fix_type >= 2:
                    # 2D Fix - poor (no altitude)
                    gps_quality = 'poor'
                elif gps_fix_type >= 1:
                    # No Fix - GPS connected but no position
                    gps_quality = 'no_fix'
                else:
                    # No GPS (0) - no GPS hardware
                    gps_quality = 'no_fix'

                # Determine status
                within_threshold = deviation_horizontal <= threshold_warning

                # Only warn if GPS quality is actually poor (2D fix or worse)
                # 3D fix and above should not trigger warnings based on GPS alone
                if gps_quality in ['no_fix', 'poor']:
                    status = 'warning'
                    fix_type_name = {0: 'No GPS', 1: 'No Fix', 2: '2D Fix', 3: '3D Fix', 4: 'DGPS', 5: 'RTK Float', 6: 'RTK Fixed'}.get(gps_fix_type, f'Fix Type {gps_fix_type}')
                    message = f"GPS quality issue: {fix_type_name} (quality: {gps_quality})"
                    summary_stats['warnings'] += 1
                elif deviation_horizontal > threshold_error:
                    status = 'error'
                    message = f"Deviation exceeds error threshold ({deviation_horizontal:.2f}m > {threshold_error}m)"
                    summary_stats['errors'] += 1
                elif deviation_horizontal > threshold_warning:
                    status = 'warning'
                    message = f"Deviation exceeds warning threshold ({deviation_horizontal:.2f}m > {threshold_warning}m)"
                    summary_stats['warnings'] += 1
                else:
                    status = 'ok'
                    message = "Position within acceptable range"
                    summary_stats['within_threshold'] += 1

                summary_stats['online'] += 1
                summary_stats['total_deviation_sum'] += deviation_horizontal
                summary_stats['best_deviation'] = min(summary_stats['best_deviation'], deviation_horizontal)
                summary_stats['worst_deviation'] = max(summary_stats['worst_deviation'], deviation_horizontal)

                # Build complete deviation data
                deviations[hw_id] = {
                    "hw_id": hw_id,
                    "pos_id": drone.get('pos_id', hw_id),
                    "expected": {
                        "lat": expected_lat,
                        "lon": expected_lon,
                        "north": expected_north,
                        "east": expected_east
                    },
                    "current": {
                        "lat": current_lat,
                        "lon": current_lon,
                        "alt": current_alt,
                        "north": current_north,
                        "east": current_east,
                        "timestamp": drone_telemetry.get('timestamp'),
                        "gps_quality": gps_quality,
                        "satellites": satellites,
                        "hdop": hdop
                    },
                    "deviation": {
                        "north": deviation_north,
                        "east": deviation_east,
                        "horizontal": deviation_horizontal,
                        "vertical": deviation_vertical,
                        "total_3d": deviation_total_3d,
                        "within_threshold": within_threshold,
                        "threshold_meters": threshold_warning
                    },
                    "status": status,
                    "message": message
                }

            # Calculate average deviation
            if summary_stats['online'] > 0:
                summary_stats['average_deviation'] = summary_stats['total_deviation_sum'] / summary_stats['online']
            else:
                summary_stats['average_deviation'] = 0

            # Reset best if no valid measurements
            if summary_stats['best_deviation'] == float('inf'):
                summary_stats['best_deviation'] = 0

            del summary_stats['total_deviation_sum']  # Remove internal counter

            # Return comprehensive response
            response = {
                "status": "success",
                "origin": {
                    "lat": origin_lat,
                    "lon": origin_lon,
                    "alt": origin_alt,
                    "timestamp": origin.get('timestamp')
                },
                "deviations": deviations,
                "summary": summary_stats
            }

            return jsonify(response), 200

        except Exception as e:
            log_system_error(f"Error in get_position_deviations: {e}", "origin")
            return jsonify({
                "status": "error",
                "error": str(e)
            }), 500

    @app.route('/compute-origin', methods=['POST'])
    def compute_origin():
        """
        Endpoint to compute the origin coordinates based on a drone's current position and intended N,E positions.
        """
        try:
            data = request.get_json()
            log_system_event(f"Received /compute-origin request data: {data}", "INFO", "origin")

            # Validate input data
            required_fields = ['current_lat', 'current_lon', 'intended_east', 'intended_north']
            missing_fields = [field for field in required_fields if field not in data]
            if missing_fields:
                error_msg = f"Missing required field(s): {', '.join(missing_fields)}"
                log_system_error(error_msg, "origin")
                return jsonify({'status': 'error', 'message': error_msg}), 400

            # Parse and validate numerical inputs
            try:
                current_lat = float(data.get('current_lat'))
                current_lon = float(data.get('current_lon'))
                intended_east = float(data.get('intended_east'))
                intended_north = float(data.get('intended_north'))
            except (TypeError, ValueError) as e:
                error_msg = f"Invalid input data types: {e}"
                log_system_error(error_msg, "origin")
                return jsonify({'status': 'error', 'message': error_msg}), 400

            log_system_event(f"Parsed inputs - current_lat: {current_lat}, current_lon: {current_lon}, intended_east: {intended_east}, intended_north: {intended_north}", "INFO", "origin")

            # Compute the origin
            origin_lat, origin_lon = compute_origin_from_drone(current_lat, current_lon, intended_north, intended_east)

            # Save the origin
            save_origin({'lat': origin_lat, 'lon': origin_lon})

            return jsonify({'status': 'success', 'lat': origin_lat, 'lon': origin_lon}), 200

        except Exception as e:
            log_system_error(f"Error in compute_origin endpoint: {e}", "origin")
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/get-desired-launch-positions', methods=['GET'])
    def get_desired_launch_positions():
        """
        Calculate GPS coordinates for each drone's desired launch position.

        Query Parameters:
          - heading: float (optional, 0-359 degrees, default 0)
          - format: str (optional, 'json'|'csv'|'kml', default 'json')

        Returns:
          JSON response with origin, drone positions, and formation metadata
        """
        try:
            # Load origin
            origin_data = load_origin()
            if not origin_data.get('lat') or not origin_data.get('lon'):
                return jsonify({
                    'status': 'error',
                    'message': 'Origin not set. Please set origin coordinates first.'
                }), 400

            origin_lat = float(origin_data['lat'])
            origin_lon = float(origin_data['lon'])
            origin_alt = float(origin_data.get('alt', 0))

            # Get optional heading parameter
            heading = float(request.args.get('heading', 0))
            heading = heading % 360  # Normalize to 0-359

            # Load drone config
            config = load_config()
            if not config:
                return jsonify({
                    'status': 'error',
                    'message': 'No drone configuration found'
                }), 404

            # Calculate positions
            drones_data = []
            formation_extent = {
                'max_north': float('-inf'),
                'max_east': float('-inf'),
                'max_south': float('inf'),
                'max_west': float('inf')
            }

            for drone in config:
                hw_id = drone.get('hw_id')
                pos_id = drone.get('pos_id', hw_id)

                # Get config x, y (x=North, y=East as per coordinate system)
                config_north = float(drone.get('x', 0))
                config_east = float(drone.get('y', 0))

                # Apply heading rotation if specified
                if heading != 0:
                    # Rotate coordinates clockwise by heading angle
                    heading_rad = math.radians(heading)
                    rotated_north = config_north * math.cos(heading_rad) - config_east * math.sin(heading_rad)
                    rotated_east = config_north * math.sin(heading_rad) + config_east * math.cos(heading_rad)
                    config_north = rotated_north
                    config_east = rotated_east

                # Update formation extent
                formation_extent['max_north'] = max(formation_extent['max_north'], config_north)
                formation_extent['max_east'] = max(formation_extent['max_east'], config_east)
                formation_extent['max_south'] = min(formation_extent['max_south'], config_north)
                formation_extent['max_west'] = min(formation_extent['max_west'], config_east)

                # Convert NED to LLA using pymap3d
                # pymap3d.ned2geodetic(north, east, down, lat0, lon0, alt0)
                launch_lat, launch_lon, launch_alt = pm.ned2geodetic(
                    config_north,
                    config_east,
                    0,  # down = 0 (at origin altitude)
                    origin_lat,
                    origin_lon,
                    origin_alt
                )

                # Calculate distance and bearing for metadata
                distance = math.sqrt(config_north**2 + config_east**2)
                bearing = math.degrees(math.atan2(config_east, config_north)) % 360

                drones_data.append({
                    'hw_id': hw_id,
                    'pos_id': pos_id,
                    'config_north': config_north,
                    'config_east': config_east,
                    'launch_lat': launch_lat,
                    'launch_lon': launch_lon,
                    'launch_alt_msl': launch_alt,
                    'distance_from_origin': distance,
                    'bearing_from_origin': bearing
                })

            # Calculate formation diameter
            north_span = formation_extent['max_north'] - formation_extent['max_south']
            east_span = formation_extent['max_east'] - formation_extent['max_west']
            diameter = math.sqrt(north_span**2 + east_span**2)
            formation_extent['diameter'] = diameter

            # Prepare response
            response = {
                'status': 'success',
                'origin': {
                    'lat': origin_lat,
                    'lon': origin_lon,
                    'alt': origin_alt,
                    'heading': heading
                },
                'drones': drones_data,
                'metadata': {
                    'total_drones': len(drones_data),
                    'formation_extent': formation_extent,
                    'timestamp': datetime.now().isoformat()
                }
            }

            log_system_event(f"Calculated {len(drones_data)} launch positions (heading={heading}°)", "INFO", "origin")
            return jsonify(response), 200

        except Exception as e:
            log_system_error(f"Error in get_desired_launch_positions: {e}", "origin")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500

    # ========================================================================
    # GCS CONFIGURATION ENDPOINTS
    # ========================================================================

    @app.route('/get-gcs-config', methods=['GET'])
    def get_gcs_config():
        """
        Get current GCS IP configuration from Params.

        Returns:
            JSON with current GCS_IP and related settings
        """
        try:
            from src.params import Params

            return jsonify({
                'status': 'success',
                'data': {
                    'gcs_ip': Params.GCS_IP,
                    'gcs_flask_port': Params.GCS_FLASK_PORT,
                    'git_auto_push': Params.GIT_AUTO_PUSH,
                    'git_branch': Params.GIT_BRANCH,
                    'simulation_mode': Params.sim_mode
                },
                'timestamp': datetime.now().isoformat()
            })
        except Exception as e:
            log_system_error(f"Error loading GCS config: {e}", "config")
            return jsonify({
                'status': 'error',
                'message': f"Error loading GCS config: {e}"
            }), 500

    @app.route('/save-gcs-config', methods=['POST'])
    def save_gcs_config():
        """
        Update GCS IP in src/params.py and commit to git.

        Request body:
            - gcs_ip: string (required) - New GCS IP address

        Returns:
            JSON with success/error and git info
        """
        try:
            data = request.get_json()
            new_gcs_ip = data.get('gcs_ip')
            update_env_file = data.get('update_env_file', False)

            if not new_gcs_ip:
                return jsonify({
                    'status': 'error',
                    'message': 'gcs_ip is required'
                }), 400

            log_system_event(f"GCS IP update requested: {new_gcs_ip} (update_env: {update_env_file})", "INFO", "config")

            # Update params.py file
            from gcs_config_updater import update_gcs_ip_in_params
            update_result = update_gcs_ip_in_params(new_gcs_ip)

            if not update_result.get('success'):
                return jsonify({
                    'status': 'error',
                    'message': update_result.get('error')
                }), 400

            # Check if no change was made
            if update_result.get('no_change'):
                log_system_event(f"GCS IP unchanged: {new_gcs_ip}", "INFO", "config")
                return jsonify({
                    'status': 'success',
                    'message': 'GCS IP is already set to this value',
                    'data': {
                        'old_ip': update_result.get('old_ip'),
                        'new_ip': new_gcs_ip
                    },
                    'no_change': True
                }), 200

            log_system_event(f"✅ GCS IP updated in params.py: {new_gcs_ip}", "INFO", "config")

            # Update .env file if requested
            env_update_result = None
            if update_env_file:
                log_system_event("Updating dashboard .env file", "INFO", "config")
                from env_updater import update_dashboard_env
                env_update_result = update_dashboard_env(new_gcs_ip)

                if env_update_result.get('success'):
                    log_system_event(f"✅ Dashboard .env updated: {env_update_result.get('new_url')}", "INFO", "config")
                else:
                    log_system_error(f".env update failed: {env_update_result.get('error')}", "config")

            # Git commit and push
            git_info = None
            if Params.GIT_AUTO_PUSH:
                log_system_event("Git auto-push enabled. Committing GCS config changes.", "INFO", "config")
                git_result = git_operations(
                    BASE_DIR,
                    f"Update GCS IP configuration to {new_gcs_ip}: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                if git_result.get('success'):
                    log_system_event("Git operations successful.", "INFO", "config")
                else:
                    log_system_error(f"Git operations failed: {git_result.get('message')}", "config")
                git_info = git_result

            response_data = {
                'status': 'success',
                'message': 'GCS IP configuration updated successfully',
                'data': {
                    'old_ip': update_result.get('old_ip'),
                    'new_ip': new_gcs_ip
                },
                'warnings': []
            }

            # Add warnings
            if env_update_result:
                if env_update_result.get('success') and not env_update_result.get('no_change'):
                    response_data['warnings'].append(
                        '⚠️  Dashboard .env file updated. Run "npm run build" in app/dashboard/drone-dashboard to apply changes.'
                    )
                elif not env_update_result.get('success'):
                    response_data['warnings'].append(
                        f'⚠️  Failed to update .env file: {env_update_result.get("error")}'
                    )

            response_data['warnings'].append('⚠️  All drones and GCS must be restarted to apply changes')

            if git_info:
                response_data['git_info'] = git_info
                if git_info.get('success'):
                    response_data['git_status'] = f"Committed: {git_info.get('message', 'Changes committed')}"

            return jsonify(response_data), 200

        except Exception as e:
            log_system_error(f"Error saving GCS config: {e}", "config")
            return jsonify({
                'status': 'error',
                'message': f"Error saving GCS config: {e}"
            }), 500

    # ========================================================================
    # GIT STATUS ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/get-gcs-git-status', methods=['GET'])
    def get_gcs_git_status():
        """Retrieve the Git status of the GCS."""
        gcs_status = get_gcs_git_report()
        return jsonify(gcs_status)

    @app.route('/get-drone-git-status/<int:drone_id>', methods=['GET'])
    def fetch_drone_git_status(drone_id):
        """
        Endpoint to retrieve the Git status of a specific drone using its hardware ID (hw_id).
        :param drone_id: Hardware ID (hw_id) of the drone.
        :return: JSON response with Git status or an error message.
        """
        try:
            log_system_event(f"Fetching drone with ID {drone_id} from configuration", "DEBUG", "git")
            drones = load_config()
            drone = next((d for d in drones if int(d['hw_id']) == drone_id), None)

            if not drone:
                log_system_error(f'Drone with ID {drone_id} not found', "git")
                return jsonify({'error': f'Drone with ID {drone_id} not found'}), 404

            drone_uri = f"http://{drone['ip']}:{Params.drones_flask_port}"
            log_system_event(f"Constructed drone URI: {drone_uri}", "DEBUG", "git")
            drone_status = get_drone_git_status(drone_uri)

            if 'error' in drone_status:
                log_system_error(f"Error in drone status response: {drone_status['error']}", "git")
                return jsonify({'error': drone_status['error']}), 500

            log_system_event(f"Drone status retrieved successfully: {drone_status}", "DEBUG", "git")
            return jsonify(drone_status), 200
        except Exception as e:
            log_system_error(f"Exception occurred: {str(e)}", "git")
            return jsonify({'error': str(e)}), 500

    @app.route('/git-status', methods=['GET'])
    def get_git_status():
        """Endpoint to retrieve consolidated git status of all drones."""
        with data_lock_git_status:
            git_status_copy = git_status_data_all_drones.copy()
        return jsonify(git_status_copy)

    # ========================================================================
    # NETWORK AND HEARTBEAT ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/get-network-info', methods=['GET'])
    def get_network_info():
        """
        Endpoint to get network information for all drones.
        Now efficiently sourced from heartbeat data instead of separate polling.
        """
        try:
            network_info_list, status_code = get_network_info_from_heartbeats()
            return jsonify(network_info_list), status_code
        except Exception as e:
            log_system_error(f"Error getting network info from heartbeats: {e}", "network")
            return jsonify([]), 200  # Return empty array to prevent UI errors

    @app.route('/drone-heartbeat', methods=['POST'])
    def drone_heartbeat():
        return handle_heartbeat_post()

    @app.route('/get-heartbeats', methods=['GET'])
    def get_heartbeats():
        return get_all_heartbeats()

    # ========================================================================
    # LEADER ELECTION ENDPOINTS (preserving original)
    # ========================================================================
    
    @app.route('/request-new-leader', methods=['POST'])
    def request_new_leader():
        """
        Called by a drone proposing a new leader.
        For now we auto-accept and update our local swarm.csv.
        """
        # 1. Parse and validate input JSON
        data = request.get_json()
        if not data or "hw_id" not in data:
            return error_response("Missing or invalid data: 'hw_id' is required", 400)

        hw_id = str(data["hw_id"])
        log_system_event(f"Received new-leader request from HW_ID={hw_id}", "INFO", "leader")

        try:
            # 2. Load the entire swarm table as a list of dicts
            swarm_data = load_swarm()  # returns List[Dict[str,str]]

            # 3. Locate the row matching our hw_id
            #    Using Python's next() with a generator to avoid a manual loop.
            entry = next((row for row in swarm_data if row.get('hw_id') == hw_id), None)
            if entry is None:
                # No match → return 404
                return error_response(f"HW_ID {hw_id} not found", 404)

            # 4. Update only the fields we care about.
            #    Use data.get(..., entry[field]) to preserve existing values if missing.
            entry['follow']     = data.get('follow',     entry['follow'])
            entry['offset_n']   = data.get('offset_n',   entry['offset_n'])
            entry['offset_e']   = data.get('offset_e',   entry['offset_e'])
            entry['offset_alt'] = data.get('offset_alt', entry['offset_alt'])
            # Convert the 'body_coord' flag from string to boolean
            entry['body_coord'] = (data.get('body_coord') == '1')

            # 5. Persist the updated list back to CSV
            #    → Ensure save_swarm() takes a List[Dict] and overwrites the file.
            save_swarm(swarm_data)

            # 6. Respond success
            return jsonify({
                'status':  'success',
                'message': f'Leader updated for HW_ID {hw_id}'
            })

        except Exception as e:
            # 7. On unexpected errors, log full traceback for debugging
            log_system_error(f"Error in request-new-leader: {e}", "leader")
            return error_response(f"Error processing request-new-leader: {e}", 500)

    # ========================================================================
    # SYSTEM STATUS ENDPOINTS
    # ========================================================================
    
    @app.route('/ping', methods=['GET'])
    def ping():
        """Simple endpoint to confirm connectivity - no logging needed."""
        return jsonify({"status": "ok"}), 200

    # Log successful route initialization
    log_system_event("All API routes initialized successfully", "INFO", "startup")
    
    # Log metrics engine availability
    if not METRICS_AVAILABLE:
        log_system_warning("Enhanced metrics engine not available - comprehensive analysis features disabled", "startup")