"""
Swarm Trajectory API Routes
Flask routes for swarm trajectory management
"""
import os
import logging
from flask import request, jsonify
from utils import ensure_directory
from functions.swarm_analyzer import analyze_swarm_structure
from functions.swarm_trajectory_processor import process_swarm_trajectories, get_swarm_trajectory_folders
from functions.file_management import clear_directory
from src.params import Params

logger = logging.getLogger(__name__)

def register_swarm_trajectory_routes(app):
    """Register swarm trajectory routes to main Flask app"""
    
    @app.route('/api/swarm/leaders', methods=['GET'])
    def get_swarm_leaders():
        """Get list of top leaders from swarm configuration"""
        try:
            # Load swarm data from the same source as the existing endpoint
            from config import load_swarm
            swarm_data = load_swarm()
            
            # Analyze structure using direct data (no API call)
            structure = analyze_swarm_structure(swarm_data)
            
            # Get uploaded status for each leader
            folders = get_swarm_trajectory_folders()
            uploaded_leaders = []
            
            for leader_id in structure['top_leaders']:
                csv_path = os.path.join(folders['raw'], f'Drone {leader_id}.csv')
                if os.path.exists(csv_path):
                    uploaded_leaders.append(leader_id)
            
            return jsonify({
                'success': True,
                'leaders': structure['top_leaders'],
                'hierarchies': {k: len(v) for k, v in structure['hierarchies'].items()},
                'follower_details': structure['hierarchies'],  # Full follower lists for each leader
                'uploaded_leaders': uploaded_leaders,
                'simulation_mode': Params.sim_mode
            })
            
        except Exception as e:
            logger.error(f"Failed to get swarm leaders: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/upload/<int:leader_id>', methods=['POST'])
    def upload_leader_trajectory(leader_id):
        """Upload CSV trajectory for specific leader"""
        try:
            file = request.files.get('file')
            if not file:
                return jsonify({'success': False, 'error': 'No file provided'}), 400
            
            if not file.filename.endswith('.csv'):
                return jsonify({'success': False, 'error': 'File must be CSV format'}), 400
            
            # Ensure raw directory exists
            folders = get_swarm_trajectory_folders()
            ensure_directory(folders['raw'])
            
            # Save file with standard naming
            filepath = os.path.join(folders['raw'], f'Drone {leader_id}.csv')
            file.save(filepath)
            
            logger.info(f"Uploaded trajectory for leader {leader_id}: {filepath}")
            
            return jsonify({
                'success': True,
                'message': f'Drone {leader_id} trajectory uploaded successfully',
                'filepath': filepath
            })
            
        except Exception as e:
            logger.error(f"Failed to upload drone {leader_id} trajectory: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/process', methods=['POST'])
    def process_trajectories():
        """Process all uploaded leader trajectories"""
        try:
            logger.info("Starting swarm trajectory processing via API")
            result = process_swarm_trajectories()
            
            if result['success']:
                logger.info(f"Processing completed: {result['processed_drones']} drones")
            else:
                logger.error(f"Processing failed: {result.get('error', 'Unknown error')}")
            
            return jsonify(result)
            
        except Exception as e:
            logger.error(f"API processing error: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/status', methods=['GET'])
    def get_processing_status():
        """Get current processing status and file counts"""
        try:
            folders = get_swarm_trajectory_folders()
            
            # Count files in each directory
            raw_count = len([f for f in os.listdir(folders['raw']) if f.endswith('.csv')]) if os.path.exists(folders['raw']) else 0
            processed_count = len([f for f in os.listdir(folders['processed']) if f.endswith('.csv')]) if os.path.exists(folders['processed']) else 0
            plot_count = len([f for f in os.listdir(folders['plots']) if f.endswith('.jpg')]) if os.path.exists(folders['plots']) else 0
            
            return jsonify({
                'success': True,
                'status': {
                    'raw_trajectories': raw_count,
                    'processed_trajectories': processed_count,
                    'generated_plots': plot_count
                },
                'folders': folders
            })
            
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/clear', methods=['POST'])
    def clear_trajectories():
        """Clear all trajectory files from both sim and live modes"""
        try:
            import os
            current_dir = os.getcwd()
            if current_dir.endswith('gcs-server'):
                root_dir = os.path.dirname(current_dir)
            else:
                root_dir = current_dir
            
            # Clear from both shapes and shapes_sitl directories
            base_folders = ['shapes', 'shapes_sitl']
            all_cleared_dirs = []
            
            for base_folder in base_folders:
                base_path = os.path.join(root_dir, base_folder)
                if os.path.exists(base_path):
                    directories_to_clear = [
                        os.path.join(base_path, 'swarm_trajectory', 'raw'),
                        os.path.join(base_path, 'swarm_trajectory', 'processed'),
                        os.path.join(base_path, 'swarm_trajectory', 'plots')
                    ]
                    
                    for directory in directories_to_clear:
                        if os.path.exists(directory):
                            # Get file count before clearing
                            file_count = len([f for f in os.listdir(directory) 
                                            if os.path.isfile(os.path.join(directory, f))])
                            
                            if file_count > 0:
                                clear_directory(directory)
                                all_cleared_dirs.append(f"{directory} ({file_count} files)")
                                logger.info(f"Cleared directory: {directory} ({file_count} files)")
            
            # Only clean stray files from swarm_trajectory directory (not entire shapes folder)
            for base_folder in base_folders:
                swarm_traj_path = os.path.join(root_dir, base_folder, 'swarm_trajectory')
                if os.path.exists(swarm_traj_path):
                    # Look for any stray trajectory files only in swarm_trajectory folder
                    for root, dirs, files in os.walk(swarm_traj_path):
                        trajectory_files = [f for f in files if f.endswith('.csv') or f.endswith('.jpg') or 
                                          f.endswith('.png') or 'trajectory' in f.lower()]
                        for traj_file in trajectory_files:
                            file_path = os.path.join(root, traj_file)
                            os.remove(file_path)
                            all_cleared_dirs.append(f"Stray file: {file_path}")
                            logger.info(f"Removed stray trajectory file: {file_path}")
            
            return jsonify({
                'success': True,
                'message': f'All trajectory files cleared successfully from {len(all_cleared_dirs)} locations',
                'cleared_directories': all_cleared_dirs
            })
            
        except Exception as e:
            logger.error(f"Failed to clear trajectories: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/clear-leader/<int:leader_id>', methods=['POST'])
    def clear_leader_trajectory(leader_id):
        """Clear trajectory for specific leader and its followers"""
        try:
            folders = get_swarm_trajectory_folders()
            
            # Clear drone's raw trajectory
            leader_csv = os.path.join(folders['raw'], f'Drone {leader_id}.csv')
            if os.path.exists(leader_csv):
                os.remove(leader_csv)
                logger.info(f"Removed raw trajectory: {leader_csv}")
            
            # Clear drone's processed trajectory  
            leader_processed = os.path.join(folders['processed'], f'Drone {leader_id}.csv')
            if os.path.exists(leader_processed):
                os.remove(leader_processed)
                logger.info(f"Removed processed trajectory: {leader_processed}")
            
            # Clear leader's plot
            leader_plot = os.path.join(folders['plots'], f'drone_{leader_id}_trajectory.jpg')
            if os.path.exists(leader_plot):
                os.remove(leader_plot)
                logger.info(f"Removed plot: {leader_plot}")
            
            
            # Get followers for this leader and clear their trajectories too
            from config import load_swarm
            swarm_data = load_swarm()
            structure = analyze_swarm_structure(swarm_data)
            
            if leader_id in structure['hierarchies']:
                followers = structure['hierarchies'][leader_id]
                for follower_id in followers:
                    follower_csv = os.path.join(folders['processed'], f'Drone {follower_id}.csv')
                    if os.path.exists(follower_csv):
                        os.remove(follower_csv)
                        logger.info(f"Removed follower trajectory: {follower_csv}")
                    
                    follower_plot = os.path.join(folders['plots'], f'drone_{follower_id}_trajectory.jpg')
                    if os.path.exists(follower_plot):
                        os.remove(follower_plot)
                        logger.info(f"Removed follower plot: {follower_plot}")
                    
            
            return jsonify({
                'success': True,
                'message': f'Drone {leader_id} and associated trajectories cleared successfully'
            })
            
        except Exception as e:
            logger.error(f"Failed to clear drone {leader_id} trajectory: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    @app.route('/api/swarm/trajectory/download/<int:drone_id>', methods=['GET'])
    def download_drone_trajectory(drone_id):
        """Download specific drone's processed trajectory"""
        try:
            folders = get_swarm_trajectory_folders()
            filepath = os.path.join(folders['processed'], f'Drone {drone_id}.csv')
            
            if not os.path.exists(filepath):
                return jsonify({'success': False, 'error': f'Trajectory for drone {drone_id} not found'}), 404
            
            from flask import send_file
            return send_file(
                filepath,
                as_attachment=True,
                download_name=f'Drone {drone_id}_trajectory.csv',
                mimetype='text/csv'
            )
            
        except Exception as e:
            logger.error(f"Failed to download drone {drone_id} trajectory: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/download-kml/<int:drone_id>', methods=['GET'])
    def download_drone_kml(drone_id):
        """Generate and download KML file on-demand for specific drone"""
        try:
            folders = get_swarm_trajectory_folders()
            
            # Check if processed trajectory exists
            csv_path = os.path.join(folders['processed'], f'Drone {drone_id}.csv')
            if not os.path.exists(csv_path):
                return jsonify({
                    'success': False, 
                    'error': f'Processed trajectory for Drone {drone_id} not found. Make sure trajectory processing has been completed.'
                }), 404
            
            # Load trajectory data
            import pandas as pd
            trajectory_df = pd.read_csv(csv_path)
            
            # Validate required columns
            required_cols = ['t', 'lat', 'lon', 'alt']
            if not all(col in trajectory_df.columns for col in required_cols):
                return jsonify({
                    'success': False,
                    'error': f'Invalid trajectory data for Drone {drone_id}'
                }), 400
            
            # Generate KML on-demand
            from functions.swarm_kml_generator import generate_kml_for_drone
            import tempfile
            import os as os_module
            
            # Create temporary file for KML
            with tempfile.NamedTemporaryFile(mode='w', suffix='.kml', delete=False) as temp_file:
                temp_dir = os_module.path.dirname(temp_file.name)
                kml_path = generate_kml_for_drone(drone_id, trajectory_df, temp_dir)
            
            from flask import send_file
            
            # Send file and clean up
            def remove_file(response):
                try:
                    os_module.unlink(kml_path)
                except Exception:
                    pass
                return response
            
            return send_file(
                kml_path,
                as_attachment=True,
                download_name=f'Drone {drone_id}_trajectory.kml',
                mimetype='application/vnd.google-earth.kml+xml'
            )
            
        except Exception as e:
            logger.error(f"Failed to generate KML for Drone {drone_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/swarm/trajectory/clear-drone/<int:drone_id>', methods=['POST'])
    def clear_individual_drone(drone_id):
        """Clear trajectory for individual drone (processed file and plot only)"""
        try:
            folders = get_swarm_trajectory_folders()
            removed_files = []
            
            # Clear processed trajectory file
            processed_csv = os.path.join(folders['processed'], f'Drone {drone_id}.csv')
            if os.path.exists(processed_csv):
                os.remove(processed_csv)
                removed_files.append(f"Processed trajectory: {processed_csv}")
                logger.info(f"Removed processed trajectory: {processed_csv}")
            
            # Clear plot file
            plot_file = os.path.join(folders['plots'], f'drone_{drone_id}_trajectory.jpg')
            if os.path.exists(plot_file):
                os.remove(plot_file)
                removed_files.append(f"Plot file: {plot_file}")
                logger.info(f"Removed plot file: {plot_file}")
            
            if not removed_files:
                return jsonify({
                    'success': False,
                    'error': f'No trajectory files found for Drone {drone_id}'
                }), 404
            
            return jsonify({
                'success': True,
                'message': f'Drone {drone_id} trajectory files removed successfully',
                'removed_files': removed_files
            })
            
        except Exception as e:
            logger.error(f"Failed to clear individual drone {drone_id}: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500