import asyncio
import logging
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class MissionContext:
    """Holds the context for a running mission"""
    task: asyncio.Task
    mission_id: str
    start_time: float

class AsyncMissionScheduler:
    """
    Handles concurrent mission scheduling and execution with the ability to override
    running missions when new ones are triggered.
    """
    def __init__(self, drone_setup):
        self.drone_setup = drone_setup
        self._current_mission: Optional[MissionContext] = None
        self._scheduler_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._mission_lock = asyncio.Lock()
        
    async def start(self):
        """Start the mission scheduler"""
        if self._scheduler_task is None:
            self._scheduler_task = asyncio.create_task(self._schedule_loop())
            logging.info("Mission scheduler started")
    
    async def stop(self):
        """Stop the mission scheduler"""
        if self._scheduler_task is not None:
            self._stop_event.set()
            await self._scheduler_task
            self._scheduler_task = None
            logging.info("Mission scheduler stopped")

    async def _schedule_loop(self):
        """Main scheduling loop that runs continuously"""
        while not self._stop_event.is_set():
            try:
                # Check for new missions without blocking
                await self._check_and_schedule_mission()
                # Small sleep to prevent CPU spinning
                await asyncio.sleep(1.0 / self.drone_setup.params.schedule_mission_frequency)
            except Exception as e:
                logging.error(f"Error in schedule loop: {e}", exc_info=True)

    async def _check_and_schedule_mission(self):
        """Check for new missions and schedule them if conditions are met"""
        current_time = int(time.time())
        
        # Calculate trigger times
        try:
            trigger_time = int(self.drone_setup.drone_config.trigger_time)
            trigger_sooner = int(self.drone_setup.params.trigger_sooner_seconds)
            earlier_trigger_time = trigger_time - trigger_sooner
        except (AttributeError, ValueError, TypeError) as e:
            logging.error(f"Error calculating trigger time: {e}")
            return

        # Get current mission details
        current_mission = self.drone_setup.drone_config.mission
        current_state = self.drone_setup.drone_config.state

        async with self._mission_lock:
            if current_state == 1 and current_time >= earlier_trigger_time:
                # Check if we have a new mission that should override the current one
                if self._current_mission is not None:
                    logging.info("New mission triggered while another is running. Cancelling current mission.")
                    await self._cancel_current_mission()

                # Start the new mission
                mission_task = asyncio.create_task(
                    self._execute_mission(current_mission, current_time, earlier_trigger_time)
                )
                self._current_mission = MissionContext(
                    task=mission_task,
                    mission_id=str(current_mission),
                    start_time=current_time
                )

    async def _execute_mission(self, mission_code: int, current_time: int, earlier_trigger_time: int):
        """Execute a mission without blocking the scheduler"""
        try:
            # Get the appropriate handler for the mission
            handler = self.drone_setup.mission_handlers.get(
                mission_code, 
                self.drone_setup._handle_unknown_mission
            )
            
            # Execute the mission
            success, message = await handler(current_time, earlier_trigger_time)
            
            # Log the result
            self.drone_setup._log_mission_result(success, message)
            
            # Reset mission if needed
            await self.drone_setup._reset_mission_if_needed(success)
            
        except Exception as e:
            logging.error(f"Error executing mission {mission_code}: {e}", exc_info=True)
        finally:
            async with self._mission_lock:
                if self._current_mission and self._current_mission.mission_id == str(mission_code):
                    self._current_mission = None

    async def _cancel_current_mission(self):
        """Cancel the currently running mission if it exists"""
        if self._current_mission is not None:
            try:
                self._current_mission.task.cancel()
                await asyncio.shield(self.drone_setup.terminate_all_running_processes())
                logging.info(f"Cancelled mission {self._current_mission.mission_id}")
            except Exception as e:
                logging.error(f"Error cancelling mission: {e}", exc_info=True)
            self._current_mission = None

# Modified DroneSetup class integration
def setup_async_scheduler(drone_setup):
    """
    Set up the async scheduler in the DroneSetup class
    """
    scheduler = AsyncMissionScheduler(drone_setup)
    
    # Modify the original schedule_mission method
    async def new_schedule_mission():
        await scheduler._check_and_schedule_mission()
    
    # Replace the original method
    drone_setup.schedule_mission = new_schedule_mission
    
    return scheduler