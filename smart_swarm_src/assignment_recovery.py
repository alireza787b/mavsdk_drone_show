"""Geometry and local assignment ownership during the existing failover policy."""
from __future__ import annotations

import math


def recovery_assignment(hw_id, new_leader, assignments, *, strategy="upstream_or_hold"):
    """Compose NED links when skipping ancestors; never guess missing body yaw."""
    hw_id, new_leader = str(hw_id), str(new_leader)
    result = dict(assignments[hw_id])
    result['follow'] = int(new_leader)
    if new_leader == '0' or strategy == 'next_hw_id':
        return result
    offsets = dict.fromkeys(('offset_x', 'offset_y', 'offset_z'), 0.0)
    current, visited = hw_id, set()
    while current != new_leader:
        if current in visited or current not in assignments:
            raise ValueError('No cycle-safe upstream offset chain; holding')
        visited.add(current)
        entry = assignments[current]
        if str(entry.get('frame', 'ned')).lower() != 'ned':
            raise ValueError('Cannot infer body-frame upstream offsets without current ancestor headings; holding')
        for axis in offsets:
            value = float(entry.get(axis, 0))
            if not math.isfinite(value):
                raise ValueError('Non-finite upstream offset; holding')
            offsets[axis] += value
        current = str(entry.get('follow', 0))
    result.update(offsets, frame='ned')
    return result


class LocalRecoveryOverride:
    """A failed GCS write must not let an unchanged saved slot undo local Hold.

    A genuinely edited own slot releases this override, so explicit operator
    leader/offset changes still use the normal runtime transition path.
    """
    def __init__(self):
        self.base = None
        self.assignment = None

    def remember(self, original, effective):
        self.base, self.assignment = dict(original), dict(effective)

    def resolve(self, incoming):
        if self.assignment is None:
            return incoming
        if incoming == self.base:
            return dict(self.assignment)
        self.base = self.assignment = None
        return incoming
