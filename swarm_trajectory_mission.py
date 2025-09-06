#!/usr/bin/env python3
"""
Swarm Trajectory Mission Executor
Executes individual drone's processed trajectory from swarm_trajectory/processed/
Reuses existing drone_show.py execution logic with global coordinates
"""
import asyncio
import logging
import sys
import os
from actions import read_hw_id
from src.params import Params

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Execute swarm trajectory mission for this drone"""
    try:
        logger.info("Starting Swarm Trajectory Mission")
        
        # Read hardware ID
        hw_id = read_hw_id()
        if hw_id is None:
            logger.error("Failed to read hardware ID from .hwID file")
            sys.exit(1)
        
        logger.info(f"Drone HW_ID: {hw_id}")
        
        # Determine trajectory file path based on simulation mode
        base_folder = 'shapes_sitl' if Params.sim_mode else 'shapes'
        trajectory_filename = f"swarm_trajectory/processed/Drone {hw_id}.csv"
        trajectory_path = os.path.join(base_folder, trajectory_filename)
        
        # Check if trajectory file exists
        if not os.path.exists(trajectory_path):
            logger.error(f"Trajectory file not found: {trajectory_path}")
            logger.error("Make sure swarm trajectory processing has been completed")
            sys.exit(1)
        
        logger.info(f"Using trajectory file: {trajectory_path}")
        
        # Import and execute using existing drone_show logic
        from drone_show import main as execute_trajectory
        
        logger.info("Executing swarm trajectory using global coordinates")
        
        # Execute trajectory with custom CSV and auto launch position
        await execute_trajectory(
            custom_csv=trajectory_filename,  # Relative path from shapes folder
            auto_launch_position=True,       # Enable auto launch position
            synchronized_start_time=None     # No synchronized start (use immediate)
        )
        
        logger.info("Swarm trajectory mission completed successfully")
        
    except Exception as e:
        logger.error(f"Swarm trajectory mission failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())