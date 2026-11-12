"""Finish an MDS recovery without leaving a grounded aircraft in Offboard.

This is postflight housekeeping, never a prerequisite for LAND/RTL. Native
fresh disarm, ON_GROUND and residual OFFBOARD must agree before one Hold request.
Other modes, unknown evidence and cancellation never trigger a mode command.
"""
import asyncio
import logging

from src.action_safety import observe_authoritative_vehicle_state


async def finish_grounded_offboard(drone, *, logger=None):
    logger = logger or logging.getLogger(__name__)
    result = {'status': 'unchanged', 'hold_requested': False}
    fields = ('armed', 'landed_state', 'flight_mode')
    try:
        before = await observe_authoritative_vehicle_state(drone, required_fields=fields)
        result['observation'] = before.as_dict()
        if not before.complete:
            result['status'] = 'state_unconfirmed'
            return result
        if before.armed is not False or before.landed_state != 'ON_GROUND':
            return result
        if before.field_value('flight_mode') != 'OFFBOARD':
            return result
        result['hold_requested'] = True
        # Exactly one request. A lost acknowledgement is not permission to replay.
        await asyncio.wait_for(drone.action.hold(), timeout=3)
        after = await observe_authoritative_vehicle_state(drone, required_fields=fields)
        result['observation'] = after.as_dict()
        if (after.complete and after.armed is False and after.landed_state == 'ON_GROUND'
                and after.field_value('flight_mode') == 'HOLD'):
            result['status'] = 'hold_confirmed'
            logger.info('Postflight: residual Offboard cleared to Hold after confirmed landing/disarm.')
        else:
            result['status'] = 'hold_unconfirmed'
            logger.warning('Landing completed; idle flight mode is unconfirmed. Review PX4 state before the next launch.')
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        # Preserve completed recovery; do not re-arm, disarm or retry a command.
        result.update(status='hold_unconfirmed' if result['hold_requested'] else 'state_unconfirmed',
                      error=type(exc).__name__)
        logger.warning('Postflight mode could not be confirmed (%s); review PX4 state before the next launch.', type(exc).__name__)
    return result
