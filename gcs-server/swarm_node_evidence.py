"""Per-aircraft operation ownership; a busy old leader cannot hide a retry."""
def swarm_node_evidence(commands, hw_ids, revision, now_ms):
    wanted, latest, known = set(hw_ids), {}, set()
    for command in commands:
        for hw in wanted.intersection(command.target_drones):
            if command.mission_type == 2:
                known.add(hw)
            previous = latest.get(hw)
            if previous is None or (command.created_at, command.command_id) > (previous.created_at, previous.command_id):
                latest[hw] = command
    result = {}
    for hw in wanted:
        command = latest.get(hw)
        snapshot = command.params.get('smart_swarm', {}) if command else {}
        report = (command.params.get('_swarm_runtime', {}).get(hw) if command and command.mission_type == 2 else None)
        # A new recovery/failed intent cannot be proof the previous controller
        # stopped. Unknown ownership is explicit until native evidence returns.
        stale = not report or snapshot.get('revision') != revision or not 0 <= now_ms - report.get('received_at_ms', 0) <= 15000
        result[hw] = {'command_id': command.command_id if command else None,
                      'has_session': hw in known, 'report': report, 'stale': stale}
    return result
