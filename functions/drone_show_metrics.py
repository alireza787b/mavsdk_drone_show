# functions/drone_show_metrics.py
import logging
import os
import json
import numpy as np
import pandas as pd
from typing import Dict, List
from scipy.spatial.distance import pdist, squareform
import warnings
warnings.filterwarnings('ignore')

class DroneShowMetrics:
    """
    Comprehensive metrics calculation engine for drone show analysis.
    Provides safety, performance, and formation quality metrics.
    """
    
    def __init__(self, processed_dir: str):
        self.processed_dir = processed_dir
        self.drone_data = {}
        self.global_metrics = {}
        self.logger = logging.getLogger(__name__)
        
    def load_drone_data(self) -> bool:
        """Load all processed drone CSV files into memory"""
        try:
            csv_files = [f for f in os.listdir(self.processed_dir) if f.endswith('.csv')]
            if not csv_files:
                self.logger.warning("No CSV files found in processed directory")
                return False
                
            for filename in csv_files:
                filepath = os.path.join(self.processed_dir, filename)
                df = pd.read_csv(filepath)
                drone_id = ''.join(filter(str.isdigit, filename))
                self.drone_data[drone_id] = df
                
            self.logger.info(f"Loaded {len(self.drone_data)} drone trajectory files")
            return True
        except Exception as e:
            self.logger.error(f"Error loading drone data: {e}")
            return False
    
    def calculate_comprehensive_metrics(self) -> Dict:
        """Calculate all metrics categories"""
        if not self.load_drone_data():
            return {'error': 'Failed to load drone data'}
            
        try:
            metrics = {
                'basic_metrics': self.calculate_basic_metrics(),
                'safety_metrics': self.calculate_safety_metrics(), 
                'performance_metrics': self.calculate_performance_metrics(),
                'formation_metrics': self.calculate_formation_metrics(),
                'quality_metrics': self.calculate_quality_metrics()
            }
            
            self.logger.info("Comprehensive metrics calculation completed")
            return metrics
        except Exception as e:
            self.logger.error(f"Error calculating comprehensive metrics: {e}")
            return {'error': str(e)}
    
    def calculate_basic_metrics(self) -> Dict:
        """Calculate basic show metrics (enhanced version of existing)"""
        try:
            if not self.drone_data:
                return {}
                
            drone_count = len(self.drone_data)
            max_duration = 0.0
            max_altitude = 0.0
            min_altitude_flight = float('inf')  # Minimum altitude during flight (excluding start/end)
            max_distance_from_launch = 0.0  # Maximum distance from launch position
            max_altitude_info = {'value': 0.0, 'drone_id': '', 'time_s': 0.0}
            min_altitude_info = {'value': float('inf'), 'drone_id': '', 'time_s': 0.0}
            max_distance_info = {'value': 0.0, 'drone_id': '', 'time_s': 0.0}
            
            for drone_id, df in self.drone_data.items():
                # Duration (time is in seconds)
                duration = df['t'].iloc[-1] if 't' in df.columns else 0
                max_duration = max(max_duration, duration)
                
                # Altitude and position analysis (up = -pz in NED)
                if 'pz' in df.columns and 't' in df.columns:
                    altitudes = -df['pz']  # Convert NED down to up
                    times = df['t']
                    
                    # Find max altitude with drone and time info
                    max_idx = altitudes.idxmax()
                    max_alt_value = altitudes.iloc[max_idx]
                    if max_alt_value > max_altitude_info['value']:
                        max_altitude_info = {
                            'value': round(max_alt_value, 2),
                            'drone_id': drone_id,
                            'time_s': round(times.iloc[max_idx], 1)
                        }
                    max_altitude = max(max_altitude, max_alt_value)
                    
                    # Calculate 3D distance from launch position (x,y,z)
                    if 'px' in df.columns and 'py' in df.columns and 'pz' in df.columns:
                        launch_x = df['px'].iloc[0]  # Launch position
                        launch_y = df['py'].iloc[0]
                        launch_z = df['pz'].iloc[0]
                        
                        # 3D distance calculation: sqrt(x^2 + y^2 + z^2)
                        distances_3d = np.sqrt((df['px'] - launch_x)**2 + 
                                             (df['py'] - launch_y)**2 + 
                                             (df['pz'] - launch_z)**2)
                        max_dist_idx = distances_3d.idxmax()
                        max_dist_value = distances_3d.iloc[max_dist_idx]
                        
                        if max_dist_value > max_distance_info['value']:
                            max_distance_info = {
                                'value': round(max_dist_value, 2),
                                'drone_id': drone_id,
                                'time_s': round(times.iloc[max_dist_idx], 1)
                            }
                        max_distance_from_launch = max(max_distance_from_launch, max_dist_value)
                    
                    # Minimum altitude during flight phase (exclude takeoff/landing based on position)
                    if 'px' in df.columns and 'py' in df.columns:
                        start_x, start_y = df['px'].iloc[0], df['py'].iloc[0]
                        end_x, end_y = df['px'].iloc[-1], df['py'].iloc[-1]
                        
                        # Create mask for points not near start/end positions (>5m away from both)
                        dist_from_start = np.sqrt((df['px'] - start_x)**2 + (df['py'] - start_y)**2)
                        dist_from_end = np.sqrt((df['px'] - end_x)**2 + (df['py'] - end_y)**2)
                        
                        # Points that are >5m from both start and end positions
                        flight_mask = (dist_from_start > 5.0) & (dist_from_end > 5.0)
                        
                        if flight_mask.any():
                            # Use only flight phase altitudes
                            flight_altitudes = altitudes[flight_mask]
                            flight_times = times[flight_mask]
                            
                            if len(flight_altitudes) > 0:
                                min_idx = flight_altitudes.idxmin()
                                min_alt_value = flight_altitudes.loc[min_idx]
                                if min_alt_value < min_altitude_info['value']:
                                    min_altitude_info = {
                                        'value': round(min_alt_value, 2),
                                        'drone_id': drone_id,
                                        'time_s': round(flight_times.loc[min_idx], 1)
                                    }
                                min_altitude_flight = min(min_altitude_flight, min_alt_value)
                        else:
                            # Fallback to excluding first/last 20% if position-based filtering fails
                            total_points = len(altitudes)
                            if total_points > 10:
                                start_exclude = int(total_points * 0.2)
                                end_exclude = int(total_points * 0.8)
                                flight_altitudes = altitudes.iloc[start_exclude:end_exclude]
                                flight_times = times.iloc[start_exclude:end_exclude]
                                
                                if len(flight_altitudes) > 0:
                                    min_idx = flight_altitudes.idxmin()
                                    min_alt_value = flight_altitudes.iloc[min_idx]
                                    if min_alt_value < min_altitude_info['value']:
                                        min_altitude_info = {
                                            'value': round(min_alt_value, 2),
                                            'drone_id': drone_id,
                                            'time_s': round(flight_times.iloc[min_idx], 1)
                                        }
                                    min_altitude_flight = min(min_altitude_flight, min_alt_value)
            
            # Handle edge cases
            if min_altitude_flight == float('inf'):
                min_altitude_flight = 0.0
                min_altitude_info = {'value': 0.0, 'drone_id': 'N/A', 'time_s': 0.0}
                
            if max_distance_info['value'] == 0.0 and max_distance_info['drone_id'] == '':
                max_distance_info = {'value': 0.0, 'drone_id': 'N/A', 'time_s': 0.0}
            
            return {
                'drone_count': drone_count,
                'duration_seconds': round(max_duration, 2),
                'duration_minutes': round(max_duration / 60, 2),
                'max_altitude_m': round(max_altitude, 2),
                'max_altitude_details': max_altitude_info,
                'min_altitude_flight_m': round(min_altitude_flight, 2),
                'min_altitude_details': min_altitude_info,
                'max_distance_from_launch_m': round(max_distance_from_launch, 2),
                'max_distance_details': max_distance_info,
                'altitude_range_m': round(max_altitude - min_altitude_flight, 2)
            }
        except Exception as e:
            self.logger.error(f"Error in basic metrics: {e}")
            return {}
    
    def calculate_safety_metrics(self) -> Dict:
        """Calculate safety-related metrics"""
        try:
            if len(self.drone_data) < 2:
                return {'min_inter_drone_distance': 'N/A (single drone)'}
                
            min_distance = float('inf')
            collision_warnings = []
            critical_distance_threshold = 2.0  # meters
            
            # Get all time points (assuming synchronized)
            first_drone = list(self.drone_data.values())[0]
            time_points = first_drone['t'].values
            
            for t_idx, t in enumerate(time_points):
                # Get positions of all drones at this time point
                positions = []
                drone_ids = []
                
                for drone_id, df in self.drone_data.items():
                    if t_idx < len(df):
                        pos = [df.iloc[t_idx]['px'], df.iloc[t_idx]['py'], -df.iloc[t_idx]['pz']]
                        positions.append(pos)
                        drone_ids.append(drone_id)
                
                if len(positions) >= 2:
                    # Calculate pairwise distances
                    positions = np.array(positions)
                    distances = pdist(positions)
                    min_dist_at_t = distances.min()
                    
                    if min_dist_at_t < min_distance:
                        min_distance = min_dist_at_t
                    
                    # Check for collision warnings
                    if min_dist_at_t < critical_distance_threshold:
                        # Find which drones are too close
                        dist_matrix = squareform(distances)
                        close_pairs = np.where((dist_matrix < critical_distance_threshold) & (dist_matrix > 0))
                        
                        for i, j in zip(close_pairs[0], close_pairs[1]):
                            if i < j:  # Avoid duplicates
                                collision_warnings.append({
                                    'time_s': round(t, 2),
                                    'drone_1': drone_ids[i],
                                    'drone_2': drone_ids[j], 
                                    'distance_m': round(dist_matrix[i, j], 2)
                                })
            
            # Ground clearance analysis
            ground_clearances = []
            for drone_id, df in self.drone_data.items():
                if 'pz' in df.columns:
                    altitudes = -df['pz']  # Convert to up
                    ground_clearances.extend(altitudes.values)
            
            min_ground_clearance = min(ground_clearances) if ground_clearances else 0
            
            return {
                'min_inter_drone_distance_m': round(min_distance, 2) if min_distance != float('inf') else 'N/A',
                'collision_warnings_count': len(collision_warnings),
                'collision_warnings': collision_warnings[:10],  # Limit to first 10
                'min_ground_clearance_m': round(min_ground_clearance, 2),
                'safety_status': 'SAFE' if len(collision_warnings) == 0 and min_ground_clearance > 1.0 else 'CAUTION'
            }
        except Exception as e:
            self.logger.error(f"Error in safety metrics: {e}")
            return {'error': str(e)}
    
    def calculate_performance_metrics(self) -> Dict:
        """Calculate performance-related metrics"""
        try:
            max_velocity = 0.0
            max_acceleration = 0.0
            velocity_stats = {}
            max_velocity_info = {'value': 0.0, 'drone_id': '', 'time_s': 0.0}
            max_acceleration_info = {'value': 0.0, 'drone_id': '', 'time_s': 0.0}
            
            for drone_id, df in self.drone_data.items():
                if all(col in df.columns for col in ['vx', 'vy', 'vz', 't']):
                    # Calculate 3D velocity magnitude
                    velocities = np.sqrt(df['vx']**2 + df['vy']**2 + df['vz']**2)
                    times = df['t']
                    
                    # Find max velocity with drone and time info
                    max_v_idx = velocities.idxmax()
                    max_v = velocities.iloc[max_v_idx]
                    
                    if max_v > max_velocity_info['value']:
                        max_velocity_info = {
                            'value': round(max_v, 2),
                            'drone_id': drone_id,
                            'time_s': round(times.iloc[max_v_idx], 1)
                        }
                    max_velocity = max(max_velocity, max_v)
                    
                    velocity_stats[drone_id] = {
                        'max_velocity_ms': round(max_v, 2),
                        'avg_velocity_ms': round(velocities.mean(), 2),
                        'velocity_std_ms': round(velocities.std(), 2)
                    }
                
                if all(col in df.columns for col in ['ax', 'ay', 'az', 't']):
                    # Calculate 3D acceleration magnitude
                    accelerations = np.sqrt(df['ax']**2 + df['ay']**2 + df['az']**2)
                    times = df['t']
                    
                    # Find max acceleration with drone and time info
                    max_a_idx = accelerations.idxmax()
                    max_a = accelerations.iloc[max_a_idx]
                    
                    if max_a > max_acceleration_info['value']:
                        max_acceleration_info = {
                            'value': round(max_a, 2),
                            'drone_id': drone_id,
                            'time_s': round(times.iloc[max_a_idx], 1)
                        }
                    max_acceleration = max(max_acceleration, max_a)
            
            # Performance assessment
            performance_status = 'EXCELLENT'
            if max_velocity > 10.0:  # > 10 m/s
                performance_status = 'HIGH_SPEED'
            elif max_acceleration > 5.0:  # > 5 m/s²
                performance_status = 'HIGH_ACCELERATION'
            
            return {
                'max_velocity_ms': round(max_velocity, 2),
                'max_velocity_kmh': round(max_velocity * 3.6, 2),
                'max_velocity_details': max_velocity_info,
                'max_acceleration_ms2': round(max_acceleration, 2),
                'max_acceleration_details': max_acceleration_info,
                'performance_status': performance_status,
                'per_drone_velocity': velocity_stats
            }
        except Exception as e:
            self.logger.error(f"Error in performance metrics: {e}")
            return {'error': str(e)}
    
    def calculate_formation_metrics(self) -> Dict:
        """Calculate formation-related metrics (formation quality removed per user request)"""
        try:
            if len(self.drone_data) < 3:
                return {'formation_analysis': 'N/A (insufficient drones for formation analysis)'}
                
            swarm_center_trajectory = []
            
            first_drone = list(self.drone_data.values())[0]
            time_points = first_drone['t'].values
            
            for t_idx, t in enumerate(time_points):
                positions = []
                for drone_id, df in self.drone_data.items():
                    if t_idx < len(df):
                        pos = [df.iloc[t_idx]['px'], df.iloc[t_idx]['py'], -df.iloc[t_idx]['pz']]
                        positions.append(pos)
                
                if len(positions) >= 3:
                    positions = np.array(positions)
                    
                    # Calculate swarm center
                    center = positions.mean(axis=0)
                    swarm_center_trajectory.append(center)
            
            # Formation complexity (based on swarm center movement)
            formation_complexity = 'SIMPLE'
            if len(swarm_center_trajectory) > 1:
                center_distances = []
                for i in range(1, len(swarm_center_trajectory)):
                    dist = np.linalg.norm(np.array(swarm_center_trajectory[i]) - np.array(swarm_center_trajectory[i-1]))
                    center_distances.append(dist)
                
                total_center_movement = sum(center_distances)
                if total_center_movement > 50:
                    formation_complexity = 'COMPLEX'
                elif total_center_movement > 20:
                    formation_complexity = 'MODERATE'
            
            return {
                'formation_complexity': formation_complexity,
                'swarm_center_total_movement_m': round(sum(center_distances) if 'center_distances' in locals() else 0, 2)
            }
        except Exception as e:
            self.logger.error(f"Error in formation metrics: {e}")
            return {'error': str(e)}
    
    def calculate_quality_metrics(self) -> Dict:
        """Calculate overall show quality metrics"""
        try:
            # Trajectory smoothness analysis
            smoothness_scores = []
            
            for drone_id, df in self.drone_data.items():
                if 'ax' in df.columns and 'ay' in df.columns and 'az' in df.columns:
                    # Calculate jerk (rate of change of acceleration)
                    jerk_x = np.gradient(df['ax'])
                    jerk_y = np.gradient(df['ay']) 
                    jerk_z = np.gradient(df['az'])
                    jerk_magnitude = np.sqrt(jerk_x**2 + jerk_y**2 + jerk_z**2)
                    
                    # Smoothness inversely related to jerk
                    avg_jerk = jerk_magnitude.mean()
                    smoothness = 1.0 / (1.0 + avg_jerk)
                    smoothness_scores.append(smoothness)
            
            avg_smoothness = np.mean(smoothness_scores) if smoothness_scores else 0
            
            # Overall quality assessment
            quality_score = avg_smoothness
            if quality_score > 0.8:
                quality_rating = 'EXCELLENT'
            elif quality_score > 0.6:
                quality_rating = 'GOOD'
            elif quality_score > 0.4:
                quality_rating = 'FAIR'
            else:
                quality_rating = 'NEEDS_OPTIMIZATION'
            
            return {
                'trajectory_smoothness_score': round(avg_smoothness, 3),
                'overall_quality_rating': quality_rating,
                'quality_score': round(quality_score, 3),
                'recommendations': self._generate_recommendations(quality_score, avg_smoothness)
            }
        except Exception as e:
            self.logger.error(f"Error in quality metrics: {e}")
            return {'error': str(e)}
    
    
    def _generate_recommendations(self, quality_score: float, smoothness: float) -> List[str]:
        """Generate optimization recommendations"""
        recommendations = []
        
        if quality_score < 0.6:
            recommendations.append("Consider increasing interpolation smoothing parameters")
        
        if smoothness < 0.5:
            recommendations.append("Trajectory has high jerk - consider smoothing waypoints")
            
        recommendations.append("Trajectory analysis completed successfully")
        return recommendations

    def save_metrics_to_file(self, metrics: Dict, filename: str = 'comprehensive_metrics.json', 
                           show_filename: str = None, upload_datetime: str = None) -> str:
        """Save calculated metrics to JSON file in swarm directory with show info"""
        try:
            # Add show file information to metrics
            if show_filename or upload_datetime:
                metrics['show_info'] = {
                    'filename': show_filename or 'Unknown',
                    'uploaded_at': upload_datetime or pd.Timestamp.now().isoformat(),
                    'processed_at': pd.Timestamp.now().isoformat()
                }
            
            # Save to swarm directory instead of processed
            swarm_dir = os.path.dirname(self.processed_dir)  # Go up one level from processed to swarm
            filepath = os.path.join(swarm_dir, filename)
            with open(filepath, 'w') as f:
                json.dump(metrics, f, indent=2, default=str)
            self.logger.info(f"Metrics saved to {filepath}")
            return filepath
        except Exception as e:
            self.logger.error(f"Error saving metrics: {e}")
            return ""