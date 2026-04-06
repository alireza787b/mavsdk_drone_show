# tests/fixtures/command_samples.py
"""
Command Sample Fixtures
=======================
Pre-built command payloads for testing all mission types.
Includes valid, invalid, and edge case commands.
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import time

# Path configuration is handled by conftest.py
from src.enums import Mission


# ============================================================================
# Mission Type Constants (imported from src/enums.py)
# ============================================================================

class MissionType:
    """Mission type constants - wrapper for src.enums.Mission"""
    NONE = Mission.NONE.value
    DRONE_SHOW_FROM_CSV = Mission.DRONE_SHOW_FROM_CSV.value
    SMART_SWARM = Mission.SMART_SWARM.value
    CUSTOM_CSV_DRONE_SHOW = Mission.CUSTOM_CSV_DRONE_SHOW.value
    SWARM_TRAJECTORY = Mission.SWARM_TRAJECTORY.value
    REBOOT_FC = Mission.REBOOT_FC.value
    REBOOT_SYS = Mission.REBOOT_SYS.value
    TEST_LED = Mission.TEST_LED.value
    TAKE_OFF = Mission.TAKE_OFF.value
    TEST = Mission.TEST.value
    LAND = Mission.LAND.value
    HOLD = Mission.HOLD.value
    UPDATE_CODE = Mission.UPDATE_CODE.value
    RETURN_RTL = Mission.RETURN_RTL.value
    KILL_TERMINATE = Mission.KILL_TERMINATE.value
    HOVER_TEST = Mission.HOVER_TEST.value
    INIT_SYSID = Mission.INIT_SYSID.value
    APPLY_COMMON_PARAMS = Mission.APPLY_COMMON_PARAMS.value
    PRECISION_MOVE = Mission.PRECISION_MOVE.value


# ============================================================================
# Command Builder
# ============================================================================

@dataclass
class CommandBuilder:
    """Builder for command payloads"""
    mission_type: int
    trigger_time: Optional[int] = None
    target_drones: Optional[List[int]] = None
    auto_global_origin: bool = False
    use_global_setpoints: bool = False
    origin: Optional[Dict[str, float]] = None
    takeoff_altitude: Optional[float] = None

    def __post_init__(self):
        if self.trigger_time is None:
            # Default to 5 seconds from now
            self.trigger_time = int(time.time()) + 5

    def build(self) -> Dict[str, Any]:
        """Build the command payload"""
        cmd = {
            "missionType": str(self.mission_type),
            "triggerTime": str(self.trigger_time)
        }

        if self.target_drones is not None:
            cmd["target_drones"] = self.target_drones

        if self.auto_global_origin:
            cmd["auto_global_origin"] = True

        if self.use_global_setpoints:
            cmd["use_global_setpoints"] = True

        if self.origin is not None:
            cmd["origin"] = self.origin

        if self.takeoff_altitude is not None:
            cmd["takeoff_altitude"] = self.takeoff_altitude

        return cmd


# ============================================================================
# Valid Command Samples
# ============================================================================

def cmd_takeoff(altitude: float = 10.0, trigger_time: int = None) -> Dict[str, Any]:
    """Takeoff command"""
    return CommandBuilder(
        mission_type=MissionType.TAKE_OFF,
        trigger_time=trigger_time,
        takeoff_altitude=altitude
    ).build()


def cmd_land(trigger_time: int = None) -> Dict[str, Any]:
    """Land command"""
    return CommandBuilder(
        mission_type=MissionType.LAND,
        trigger_time=trigger_time
    ).build()


def cmd_hold(trigger_time: int = None) -> Dict[str, Any]:
    """Hold position command"""
    return CommandBuilder(
        mission_type=MissionType.HOLD,
        trigger_time=trigger_time
    ).build()


def cmd_rtl(trigger_time: int = None) -> Dict[str, Any]:
    """Return to launch command"""
    return CommandBuilder(
        mission_type=MissionType.RETURN_RTL,
        trigger_time=trigger_time
    ).build()


def cmd_kill_terminate(trigger_time: int = None) -> Dict[str, Any]:
    """Emergency kill/terminate command"""
    return CommandBuilder(
        mission_type=MissionType.KILL_TERMINATE,
        trigger_time=trigger_time
    ).build()


def cmd_drone_show(
    trigger_time: int = None,
    auto_origin: bool = True,
    origin: Dict[str, float] = None
) -> Dict[str, Any]:
    """Drone show from CSV command"""
    return CommandBuilder(
        mission_type=MissionType.DRONE_SHOW_FROM_CSV,
        trigger_time=trigger_time,
        auto_global_origin=auto_origin,
        origin=origin or {'lat': 47.397742, 'lon': 8.545594, 'alt': 488.0}
    ).build()


def cmd_smart_swarm(trigger_time: int = None) -> Dict[str, Any]:
    """Smart swarm command"""
    return CommandBuilder(
        mission_type=MissionType.SMART_SWARM,
        trigger_time=trigger_time
    ).build()


def cmd_swarm_trajectory(
    trigger_time: int = None,
    origin: Dict[str, float] = None
) -> Dict[str, Any]:
    """Swarm trajectory command"""
    return CommandBuilder(
        mission_type=MissionType.SWARM_TRAJECTORY,
        trigger_time=trigger_time,
        auto_global_origin=True,
        origin=origin or {'lat': 47.397742, 'lon': 8.545594, 'alt': 488.0}
    ).build()


def cmd_hover_test(trigger_time: int = None) -> Dict[str, Any]:
    """Hover test command"""
    return CommandBuilder(
        mission_type=MissionType.HOVER_TEST,
        trigger_time=trigger_time
    ).build()


def cmd_reboot_fc(trigger_time: int = None) -> Dict[str, Any]:
    """Reboot flight controller command"""
    return CommandBuilder(
        mission_type=MissionType.REBOOT_FC,
        trigger_time=trigger_time
    ).build()


def cmd_reboot_sys(trigger_time: int = None) -> Dict[str, Any]:
    """Reboot system command"""
    return CommandBuilder(
        mission_type=MissionType.REBOOT_SYS,
        trigger_time=trigger_time
    ).build()


def cmd_update_code(trigger_time: int = None) -> Dict[str, Any]:
    """Update code (git pull) command"""
    return CommandBuilder(
        mission_type=MissionType.UPDATE_CODE,
        trigger_time=trigger_time
    ).build()


def cmd_test_led(trigger_time: int = None) -> Dict[str, Any]:
    """Test LED command"""
    return CommandBuilder(
        mission_type=MissionType.TEST_LED,
        trigger_time=trigger_time
    ).build()


def cmd_init_sysid(trigger_time: int = None) -> Dict[str, Any]:
    """Initialize system ID command"""
    return CommandBuilder(
        mission_type=MissionType.INIT_SYSID,
        trigger_time=trigger_time
    ).build()


def cmd_apply_common_params(trigger_time: int = None) -> Dict[str, Any]:
    """Apply common parameters command"""
    return CommandBuilder(
        mission_type=MissionType.APPLY_COMMON_PARAMS,
        trigger_time=trigger_time
    ).build()


def cmd_precision_move(trigger_time: int = 0) -> Dict[str, Any]:
    """Precision move command."""
    command = CommandBuilder(
        mission_type=MissionType.PRECISION_MOVE,
        trigger_time=trigger_time,
    ).build()
    command["precision_move"] = {
        "frame": "body",
        "translation_m": {
            "forward": 2.0,
            "right": 0.5,
            "up": 1.0,
        },
        "yaw": {
            "mode": "relative_delta",
            "degrees": 30.0,
        },
        "speed_m_s": 1.0,
        "position_tolerance_m": 0.15,
        "yaw_tolerance_deg": 5.0,
        "settle_time_sec": 1.0,
        "timeout_sec": 30.0,
        "hold_mode": "px4_hold",
    }
    return command


# ============================================================================
# Targeted Commands (for specific drones)
# ============================================================================

def cmd_takeoff_single_drone(
    drone_id: int,
    altitude: float = 10.0,
    trigger_time: int = None
) -> Dict[str, Any]:
    """Takeoff command for a single drone"""
    return CommandBuilder(
        mission_type=MissionType.TAKE_OFF,
        trigger_time=trigger_time,
        target_drones=[drone_id],
        takeoff_altitude=altitude
    ).build()


def cmd_land_multiple_drones(
    drone_ids: List[int],
    trigger_time: int = None
) -> Dict[str, Any]:
    """Land command for multiple specific drones"""
    return CommandBuilder(
        mission_type=MissionType.LAND,
        trigger_time=trigger_time,
        target_drones=drone_ids
    ).build()


# ============================================================================
# Invalid Command Samples (for error handling tests)
# ============================================================================

def cmd_invalid_mission_type() -> Dict[str, Any]:
    """Command with invalid mission type"""
    return {
        "missionType": "999",  # Invalid
        "triggerTime": str(int(time.time()) + 5)
    }


def cmd_missing_mission_type() -> Dict[str, Any]:
    """Command missing mission type"""
    return {
        "triggerTime": str(int(time.time()) + 5)
    }


def cmd_missing_trigger_time() -> Dict[str, Any]:
    """Command missing trigger time"""
    return {
        "missionType": str(MissionType.TAKE_OFF)
    }


def cmd_empty() -> Dict[str, Any]:
    """Empty command"""
    return {}


def cmd_invalid_trigger_time() -> Dict[str, Any]:
    """Command with invalid trigger time"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": "not_a_timestamp"
    }


def cmd_past_trigger_time() -> Dict[str, Any]:
    """Command with trigger time in the past"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) - 3600)  # 1 hour ago
    }


def cmd_invalid_origin() -> Dict[str, Any]:
    """Command with invalid origin coordinates"""
    return {
        "missionType": str(MissionType.DRONE_SHOW_FROM_CSV),
        "triggerTime": str(int(time.time()) + 5),
        "origin": {
            "lat": 999.0,  # Invalid
            "lon": 999.0,  # Invalid
            "alt": -1000.0  # Invalid
        }
    }


def cmd_invalid_target_drones() -> Dict[str, Any]:
    """Command with invalid target drone IDs"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) + 5),
        "target_drones": [-1, 0, "invalid"]  # Invalid IDs
    }


def cmd_invalid_altitude() -> Dict[str, Any]:
    """Command with invalid takeoff altitude"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) + 5),
        "takeoff_altitude": -10.0  # Negative altitude
    }


def cmd_excessive_altitude() -> Dict[str, Any]:
    """Command with excessive takeoff altitude"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) + 5),
        "takeoff_altitude": 1000.0  # Way too high
    }


# ============================================================================
# Edge Case Commands
# ============================================================================

def cmd_immediate_trigger() -> Dict[str, Any]:
    """Command with immediate trigger (trigger_time = now)"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()))
    }


def cmd_far_future_trigger() -> Dict[str, Any]:
    """Command with far future trigger"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) + 86400 * 365)  # 1 year
    }


def cmd_with_extra_fields() -> Dict[str, Any]:
    """Command with extra unexpected fields"""
    return {
        "missionType": str(MissionType.TAKE_OFF),
        "triggerTime": str(int(time.time()) + 5),
        "unexpected_field": "should be ignored",
        "another_unknown": 12345
    }


# ============================================================================
# Batch Command Generators
# ============================================================================

def all_valid_commands() -> List[Dict[str, Any]]:
    """Generate all valid command types"""
    return [
        cmd_takeoff(),
        cmd_land(),
        cmd_hold(),
        cmd_rtl(),
        cmd_kill_terminate(),
        cmd_drone_show(),
        cmd_smart_swarm(),
        cmd_swarm_trajectory(),
        cmd_hover_test(),
        cmd_reboot_fc(),
        cmd_reboot_sys(),
        cmd_update_code(),
        cmd_test_led(),
        cmd_init_sysid(),
        cmd_apply_common_params(),
        cmd_precision_move(),
    ]


def all_invalid_commands() -> List[Dict[str, Any]]:
    """Generate all invalid command types for error testing"""
    return [
        cmd_invalid_mission_type(),
        cmd_missing_mission_type(),
        cmd_missing_trigger_time(),
        cmd_empty(),
        cmd_invalid_trigger_time(),
        cmd_invalid_origin(),
        cmd_invalid_target_drones(),
        cmd_invalid_altitude(),
        cmd_excessive_altitude()
    ]


# ============================================================================
# Exports
# ============================================================================

__all__ = [
    'MissionType',
    'CommandBuilder',
    'cmd_takeoff',
    'cmd_land',
    'cmd_hold',
    'cmd_rtl',
    'cmd_kill_terminate',
    'cmd_drone_show',
    'cmd_smart_swarm',
    'cmd_swarm_trajectory',
    'cmd_hover_test',
    'cmd_reboot_fc',
    'cmd_reboot_sys',
    'cmd_update_code',
    'cmd_test_led',
    'cmd_init_sysid',
    'cmd_apply_common_params',
    'cmd_takeoff_single_drone',
    'cmd_land_multiple_drones',
    'cmd_invalid_mission_type',
    'cmd_missing_mission_type',
    'cmd_missing_trigger_time',
    'cmd_empty',
    'cmd_invalid_trigger_time',
    'cmd_past_trigger_time',
    'cmd_invalid_origin',
    'cmd_invalid_target_drones',
    'cmd_invalid_altitude',
    'cmd_excessive_altitude',
    'cmd_immediate_trigger',
    'cmd_far_future_trigger',
    'cmd_with_extra_fields',
    'all_valid_commands',
    'all_invalid_commands',
]
