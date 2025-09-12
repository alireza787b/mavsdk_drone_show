"""
Swarm Trajectory Plotter
Generates visualization plots for swarm trajectories
"""
import os
import logging
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for server environments
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
import pandas as pd
import numpy as np
from functions.file_management import ensure_directory_exists

logger = logging.getLogger(__name__)

def generate_swarm_plots(all_trajectories, swarm_structure, plots_dir):
    """
    Generate plots following existing plot_drone_paths.py pattern
    - Individual drone plots
    - Cluster plots (for each top leader + followers)  
    - Combined swarm plot
    """
    ensure_directory_exists(plots_dir)
    logger.info(f"Generating plots for {len(all_trajectories)} drones to {plots_dir}")
    
    # Verify directory is writable
    if not os.access(plots_dir, os.W_OK):
        logger.error(f"Plots directory not writable: {plots_dir}")
        raise PermissionError(f"Cannot write to plots directory: {plots_dir}")
    
    try:
        # Individual drone plots
        for hw_id, trajectory in all_trajectories.items():
            plot_single_drone(hw_id, trajectory, plots_dir)
        
        # Cluster plots (each top leader + followers)
        for leader_id in swarm_structure['top_leaders']:
            if leader_id in all_trajectories:  # Only if leader was processed
                cluster_drones = [leader_id] + swarm_structure['hierarchies'][leader_id]
                cluster_trajectories = {
                    hw_id: all_trajectories[hw_id] 
                    for hw_id in cluster_drones 
                    if hw_id in all_trajectories
                }
                
                if cluster_trajectories:
                    plot_cluster(leader_id, cluster_trajectories, plots_dir)
        
        # Combined swarm plot
        plot_combined_swarm(all_trajectories, plots_dir)
        
        logger.info(f"Generated plots saved to {plots_dir}")
        
    except Exception as e:
        logger.error(f"Failed to generate plots: {e}")
        raise

def plot_single_drone(hw_id, trajectory, plots_dir):
    """Plot individual drone trajectory"""
    try:
        fig = plt.figure(figsize=(12, 8))
        ax = fig.add_subplot(111, projection='3d')
        
        lats = trajectory['lat'].values
        lons = trajectory['lon'].values
        alts = trajectory['alt'].values
        
        # Plot trajectory path
        ax.plot(lats, lons, alts, linewidth=2, label=f'Drone {hw_id}', alpha=0.8)
        
        # Mark start and end points
        ax.scatter(lats[0], lons[0], alts[0], color='green', s=100, label='Start', edgecolors='black')
        ax.scatter(lats[-1], lons[-1], alts[-1], color='red', s=100, label='End', edgecolors='black')
        
        # Set labels and title
        ax.set_xlabel('Latitude (deg)')
        ax.set_ylabel('Longitude (deg)')
        ax.set_zlabel('Altitude (m)')
        ax.set_title(f'Drone {hw_id} Swarm Trajectory')
        ax.legend()
        
        # Set viewing angle
        ax.view_init(elev=30, azim=-60)
        
        plt.tight_layout()
        plot_path = os.path.join(plots_dir, f'drone_{hw_id}_trajectory.jpg')
        plt.savefig(plot_path, dpi=90, bbox_inches='tight', facecolor='white')
        plt.close()
        
        # Verify file was created
        if os.path.exists(plot_path):
            logger.debug(f"✓ Generated plot: {plot_path} ({os.path.getsize(plot_path)} bytes)")
        else:
            logger.error(f"✗ Failed to create plot: {plot_path}")
        
        logger.debug(f"Generated individual plot for drone {hw_id}")
        
    except Exception as e:
        logger.error(f"Failed to plot drone {hw_id}: {e}")

def plot_cluster(leader_id, cluster_trajectories, plots_dir):
    """Plot cluster formation (leader + all followers)"""
    try:
        fig = plt.figure(figsize=(14, 10))
        ax = fig.add_subplot(111, projection='3d')
        
        # Generate colors for drones in cluster
        colors = plt.cm.viridis(np.linspace(0, 1, len(cluster_trajectories)))
        
        for i, (hw_id, trajectory) in enumerate(cluster_trajectories.items()):
            lats = trajectory['lat'].values
            lons = trajectory['lon'].values
            alts = trajectory['alt'].values
            
            # Label appropriately
            label = f'Leader {hw_id}' if hw_id == leader_id else f'Follower {hw_id}'
            
            # Plot trajectory
            ax.plot(lats, lons, alts, color=colors[i], linewidth=2, label=label, alpha=0.8)
            
            # Mark start point
            ax.scatter(lats[0], lons[0], alts[0], color=colors[i], s=80, edgecolors='black')
        
        ax.set_xlabel('Latitude (deg)')
        ax.set_ylabel('Longitude (deg)')
        ax.set_zlabel('Altitude (m)')
        ax.set_title(f'Cluster Formation - Leader {leader_id} ({len(cluster_trajectories)} drones)')
        ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        ax.view_init(elev=30, azim=-60)
        
        plt.tight_layout()
        plot_path = os.path.join(plots_dir, f'cluster_leader_{leader_id}.jpg')
        plt.savefig(plot_path, dpi=90, bbox_inches='tight', facecolor='white')
        plt.close()
        
        # Verify file was created
        if os.path.exists(plot_path):
            logger.debug(f"✓ Generated cluster plot: {plot_path} ({os.path.getsize(plot_path)} bytes)")
        else:
            logger.error(f"✗ Failed to create cluster plot: {plot_path}")
        
        logger.debug(f"Generated cluster plot for leader {leader_id}")
        
    except Exception as e:
        logger.error(f"Failed to plot cluster {leader_id}: {e}")

def plot_combined_swarm(all_trajectories, plots_dir):
    """Plot all drones in combined view"""
    try:
        fig = plt.figure(figsize=(16, 12))
        ax = fig.add_subplot(111, projection='3d')
        
        # Generate colors for all drones
        colors = plt.cm.tab20(np.linspace(0, 1, len(all_trajectories)))
        
        for i, (hw_id, trajectory) in enumerate(all_trajectories.items()):
            lats = trajectory['lat'].values
            lons = trajectory['lon'].values
            alts = trajectory['alt'].values
            
            # Plot trajectory with alpha for clarity
            ax.plot(lats, lons, alts, color=colors[i], linewidth=1.5, 
                   label=f'Drone {hw_id}', alpha=0.7)
            
            # Mark start point
            ax.scatter(lats[0], lons[0], alts[0], color=colors[i], s=60, edgecolors='black')
        
        ax.set_xlabel('Latitude (deg)')
        ax.set_ylabel('Longitude (deg)')
        ax.set_zlabel('Altitude (m)')
        ax.set_title(f'Complete Swarm Formation ({len(all_trajectories)} drones)')
        
        # Legend only if reasonable number of drones
        if len(all_trajectories) <= 20:
            ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        
        ax.view_init(elev=30, azim=-60)
        
        plt.tight_layout()
        plot_path = os.path.join(plots_dir, 'combined_swarm.jpg')
        plt.savefig(plot_path, dpi=100, bbox_inches='tight', facecolor='white')
        plt.close()
        
        # Verify file was created
        if os.path.exists(plot_path):
            logger.info(f"✓ Generated combined swarm plot: {plot_path} ({os.path.getsize(plot_path)} bytes)")
        else:
            logger.error(f"✗ Failed to create combined swarm plot: {plot_path}")
        
        logger.info("Generated combined swarm plot")
        
    except Exception as e:
        logger.error(f"Failed to plot combined swarm: {e}")