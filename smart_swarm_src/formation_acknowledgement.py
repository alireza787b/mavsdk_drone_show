"""Confirm configuration installation, not geometric arrival or flight safety."""
from src.smart_swarm_contract import normalize_topology, topology_revision


def effective_revision(assignments, hw_id, *, is_leader, follow, offsets, frame,
                       controller_running, takeover=False):
    if takeover:
        return None
    members = normalize_topology(assignments)
    own = next((m for m in members if m["hw_id"] == str(hw_id)), None)
    if own is None or (own["follow"] == "0") != is_leader:
        return None
    if not is_leader and (str(follow) != own["follow"] or not controller_running):
        return None
    if frame != own["frame"] or any(
        offsets.get(axis) != own[f"offset_{axis}"] for axis in ("x", "y", "z")
    ):
        return None
    return topology_revision(members)
