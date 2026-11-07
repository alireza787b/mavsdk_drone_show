"""Local serialization of formation writes and Smart Swarm Start registration.

This is not a node reservation or distributed flight transaction. Fresh native
observations remain required for inactive-only saves; recovery never waits here.
"""
from __future__ import annotations

import asyncio

from fastapi import HTTPException


def configuration_lock(deps):
    lock = getattr(deps, '_swarm_configuration_lock', None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(deps, '_swarm_configuration_lock', lock)
    return lock


async def require_no_pending_swarm(deps, hw_ids):
    """Include queued/preparing Starts, not only controller callback reports."""
    factory = getattr(deps, 'get_command_tracker', None)
    if not callable(factory):
        raise HTTPException(409, detail={
            'code': 'capture_activity_unavailable',
            'message': 'Swarm activity cannot be verified. Refresh before capturing or applying.',
        })
    wanted = set(hw_ids)
    for command in await factory().get_active_commands():
        if command.get('mission_type') != 2:
            continue
        overlap = wanted & {str(hw) for hw in command.get('target_drones', [])}
        if overlap:
            raise HTTPException(409, detail={
                'code': 'capture_swarm_active', 'hw_id': min(overlap, key=int),
                'message': 'Stop following and confirm it has stopped before capturing or applying this draft.',
            })
