"""Return scope checks for tracked Smart Swarm producers, never extra targets."""
from src.smart_swarm_contract import required_reference_ids
from src.control_release_protocol import ControlReleaseResult


def omitted_followers(commands, targets):
    """Find pending/active followers whose saved source chain is being returned.

    The caller supplies nonterminal tracked work. Missing terminal evidence is
    not proof a pending/started producer stopped. A native per-target execution
    result with confirmed control release can remove that producer from this
    particular still-running multi-aircraft command.
    """
    returning = set(targets)
    conflicts = set()
    for command in commands:
        if command.get('mission_type') != 2:
            continue
        assignments = command.get('params', {}).get('smart_swarm', {}).get('assignments')
        candidates = set(command.get('target_drones', [])) - returning
        if not candidates:
            continue
        if not assignments:
            # Old active work without its topology cannot authorize a partial return.
            conflicts.update(candidates)
            continue
        for hw_id in candidates:
            result = command.get('executions', {}).get('details', {}).get(hw_id, {})
            try:
                release = ControlReleaseResult.model_validate(result.get('control_release'))
                released = release.hw_id == hw_id and release.command_id == command.get('command_id') and release.released
            except (ValueError, TypeError):
                released = False
            if released:
                continue
            if returning.intersection(required_reference_ids(assignments, [hw_id])):
                conflicts.add(hw_id)
    return sorted(conflicts, key=int)
