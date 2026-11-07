"""Read-only, stationary formation capture; owns no flight or configuration I/O."""
from __future__ import annotations

import asyncio
import math
import time
import uuid

import navpy
from fastapi import HTTPException

from origin_reference import OriginReferenceError, validate_fresh_global_position
from src.smart_swarm_contract import normalize_topology, resolve_clusters, topology_revision
from src.px4_flight_modes import decode_px4_custom_mode, describe_px4_custom_mode
from swarm_configuration_guard import configuration_lock, require_no_pending_swarm
from swarm_design_service import changed_formation_ids


# Capture confidence limits, not PX4 preflight/arming or flight-controller gates.
CAPTURE_DWELL_SEC = 0.5
CAPTURE_MAX_SOURCE_AGE_MS = 750
CAPTURE_MAX_SKEW_MS = 500
CAPTURE_MAX_SPEED_M_S = 0.5
CAPTURE_MAX_DRIFT_M = 0.35
CAPTURE_MAX_YAW_RATE_DEG_S = 5.0
CAPTURE_MAX_YAW_CHANGE_DEG = 3.0


def reject(code, message, hw_id=None):
    detail = {'code': code, 'message': message}
    if hw_id is not None:
        detail['hw_id'] = str(hw_id)
    raise HTTPException(409, detail=detail)


def configured_targets(deps, hw_ids):
    fleet = deps.load_config() or []
    targets = []
    for hw in sorted(set(hw_ids), key=int):
        matches = [d for d in fleet if str(d.get('hw_id')) == hw]
        if len(matches) != 1:
            reject('capture_identity_invalid', 'Every captured aircraft must have one configured hardware identity.', hw)
        targets.append(matches[0])
    return targets


def _finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return float(value)


def _source_age(sample, field, hw):
    emitted, timestamp = _finite(sample.get('emitted_at_ms')), _finite(sample.get(field))
    if emitted is None or timestamp is None or timestamp <= 0 or emitted < timestamp:
        reject('capture_timestamp_invalid', 'A required native sample timestamp is missing or inconsistent.', hw)
    return emitted - timestamp


def observation_age_ms(record):
    received = _finite(record.get('received_monotonic'))
    round_trip = _finite(record.get('round_trip_ms'))
    if received is None or round_trip is None or round_trip < 0 or received > time.monotonic():
        return math.inf
    return round_trip + max(0, (time.monotonic() - received) * 1000)


def validate_inactive_sample(record, hw):
    """Trust fresh node activity, never the saved ``follow_mode`` relationship."""
    sample = record.get('sample') or {}
    if str(sample.get('hw_id')) != hw:
        reject('capture_telemetry_unavailable', 'Fresh telemetry with the expected hardware identity is required.', hw)
    activity = sample.get('capture_activity')
    if not isinstance(activity, dict) or activity.get('schema_version') != 1:
        reject('capture_activity_unavailable', 'Update aircraft software to provide native capture activity evidence.', hw)
    elapsed = observation_age_ms(record)
    for field in ('heartbeat_timestamp_ms', 'landed_state_timestamp_ms'):
        _source_age({**sample, **activity}, field, hw)
    remaining = _finite(activity.get('valid_for_ms'))
    # The node owns native activity lifetime (heartbeat/landed evidence may
    # arrive at 1 Hz). Position/heading capture freshness is deliberately
    # separate; subtract transport and collection wait on our monotonic clock.
    if remaining is None or remaining <= elapsed:
        reject('capture_activity_stale', 'Aircraft activity evidence is delayed. Refresh before continuing.', hw)
    if activity.get('swarm_active') is not False:
        reject('capture_swarm_active', 'Stop following and confirm it has stopped before capturing or applying.', hw)
    if activity.get('state') != 0:
        reject('capture_action_active', 'Wait for the current aircraft action to finish before capturing or applying.', hw)
    mode = activity.get('flight_mode')
    try:
        main, sub = decode_px4_custom_mode(mode)
    except (TypeError, ValueError, OverflowError):
        main, sub = 0, 0
    if main == 0:
        reject('capture_flight_state_unavailable', 'Current PX4 mode is unavailable. Refresh before continuing.', hw)
    if (main == 4 and sub in {2, 4, 5, 6, 8, 9, 10, 20}) or main == 10:
        reject('capture_action_active', f'Wait for PX4 {describe_px4_custom_mode(mode)} to finish before capturing or applying.', hw)
    if type(activity.get('is_armed')) is not bool or activity.get('landed_state') not in (1, 2):
        reject('capture_flight_state_unavailable', 'Wait for confirmed grounded or settled airborne aircraft state.', hw)
    return sample


def validate_position_sample(record, hw, *, require_heading):
    sample = validate_inactive_sample(record, hw)
    elapsed = observation_age_ms(record)
    position_age = _source_age(sample, 'global_position_timestamp_ms', hw)
    if position_age + elapsed > CAPTURE_MAX_SOURCE_AGE_MS:
        reject('capture_position_stale', 'Current PX4 global position is delayed. Refresh before capturing.', hw)
    try:
        position = validate_fresh_global_position(
            {**sample, 'hw_id': hw, 'telemetry_available': True}, hw_id=hw,
            now_ms=int(sample['emitted_at_ms']), max_age_ms=CAPTURE_MAX_SOURCE_AGE_MS,
            require_disarmed=False,
        )
    except OriginReferenceError as exc:
        reject('capture_position_invalid', str(exc), hw)
    velocity = [_finite(sample.get(key)) for key in ('velocity_north', 'velocity_east', 'velocity_down')]
    if any(v is None for v in velocity):
        reject('capture_motion_unavailable', 'Current velocity evidence is unavailable.', hw)
    if math.sqrt(sum(v * v for v in velocity)) > CAPTURE_MAX_SPEED_M_S:
        reject('capture_aircraft_moving', 'Let every aircraft settle before capturing the formation.', hw)
    heading = _finite(sample.get('yaw_deg'))
    heading_time = _finite(sample.get('attitude_timestamp_ms'))
    emitted = float(sample['emitted_at_ms'])
    heading_fresh = (heading is not None and heading_time is not None and heading_time > 0
                     and 0 <= emitted - heading_time + elapsed <= CAPTURE_MAX_SOURCE_AGE_MS
                     and emitted >= heading_time)
    if require_heading and not heading_fresh:
        reject('capture_heading_stale', 'Body capture requires a fresh independent heading sample on every aircraft.', hw)
    yaw_rate = _finite(sample.get('yaw_rate_deg_s'))
    if heading_fresh and yaw_rate is not None and abs(yaw_rate) > CAPTURE_MAX_YAW_RATE_DEG_S:
        reject('capture_aircraft_turning', 'Let aircraft headings settle before capturing.', hw)
    return {**position, 'heading_deg': heading % 360 if heading_fresh else None,
            'attitude_timestamp_ms': int(heading_time) if heading_fresh else None,
            'position_age_ms': position_age + elapsed}


def inactive_scope(before, after, required):
    ids = set(required) | changed_formation_ids(before, after)
    members = [*normalize_topology(before), *normalize_topology(after)]
    # Include old/new upstream dependencies when the draft reparents a branch.
    while True:
        expanded = ids | {m['follow'] for m in members if m['hw_id'] in ids and m['follow'] != '0'}
        if expanded == ids:
            return sorted(ids, key=int)
        ids = expanded


async def read_inactive_scope(deps, hw_ids):
    await require_no_pending_swarm(deps, hw_ids)
    records = await deps.get_fleet_rpc_service().read_swarm_samples(configured_targets(deps, hw_ids))
    for hw in hw_ids:
        validate_inactive_sample(records.get(hw, {}), hw)
    return records


async def recheck_inactive_scope(deps, hw_ids, records):
    """Called inside the local Start/write lock; no network wait under that lock."""
    await require_no_pending_swarm(deps, hw_ids)
    for hw in hw_ids:
        validate_inactive_sample(records.get(hw, {}), hw)


def reroot_members(members, leader_hw_id):
    by_id = {str(m['hw_id']): m for m in members}
    if leader_hw_id not in by_id:
        reject('capture_leader_invalid', 'The selected leader must belong to the captured cluster.', leader_hw_id)
    current, previous = leader_hw_id, '0'
    while current != '0':
        parent = str(by_id[current].get('follow', 0))
        by_id[current]['follow'] = int(previous)
        previous, current = current, parent


def planned_heights(members):
    by_id = {m['hw_id']: m for m in normalize_topology(members)}
    heights = {}

    def height(hw):
        if hw not in heights:
            parent = by_id[hw]['follow']
            heights[hw] = 0.0 if parent == '0' else height(parent) + by_id[hw]['offset_z']
        return heights[hw]

    return {hw: height(hw) for hw in by_id}


def captured_assignments(draft, observations, cluster_hw_ids, leader_hw_id, frame, height_mode):
    """Derive an editable candidate from one frozen bundle, preserving other clusters."""
    candidate = [dict(member) for member in draft]
    ids = set(cluster_hw_ids)
    selected = [m for m in candidate if str(m['hw_id']) in ids]
    reroot_members(selected, leader_hw_id)
    for member in selected:
        hw, parent = str(member['hw_id']), str(member['follow'])
        member['frame'] = frame
        if parent == '0':
            member.update(offset_x=0.0, offset_y=0.0, offset_z=0.0)
            continue
        north = observations[hw]['north_m'] - observations[parent]['north_m']
        east = observations[hw]['east_m'] - observations[parent]['east_m']
        if frame == 'body':
            heading = _finite(observations[parent].get('heading_deg'))
            if heading is None:
                reject('capture_heading_stale', 'Body capture requires a fresh captured heading for every parent.', parent)
            yaw = math.radians(heading)
            x, y = math.cos(yaw) * north + math.sin(yaw) * east, -math.sin(yaw) * north + math.cos(yaw) * east
        else:
            x, y = north, east
        height_field = 'current_up_m' if height_mode == 'current' else 'planned_up_m'
        member.update(offset_x=x, offset_y=y, offset_z=(
            observations[hw][height_field] - observations[parent][height_field]
            if height_mode != 'level' else 0.0))
    normalize_topology(candidate)
    return candidate


async def capture_preview(deps, request):
    try:
        draft = [m.model_dump(exclude_none=True) for m in request.assignments]
        clusters = resolve_clusters(draft)
        saved = normalize_topology(deps.load_swarm() or [])
        current_revision = topology_revision(saved)
    except (ValueError, TypeError, KeyError) as exc:
        reject('capture_topology_invalid', f'The formation is invalid: {exc}')
    if request.revision != current_revision:
        reject('capture_revision_conflict', 'The saved formation changed. Review it before capturing this draft.')
    draft_ids = {str(m['hw_id']) for m in draft}
    if draft_ids != {m['hw_id'] for m in saved}:
        reject('capture_fleet_changed', 'Capture requires the complete current formation. Review and apply fleet membership changes first.')
    configured_targets(deps, draft_ids)
    cluster = next((c for c in clusters if c['cluster_id'] == request.cluster_id), None)
    if cluster is None:
        reject('capture_cluster_invalid', 'Select a complete draft cluster to capture.')
    ids = [m['hw_id'] for m in cluster['members']]
    leader = request.leader_hw_id or request.cluster_id
    if leader not in ids:
        reject('capture_leader_invalid', 'The selected leader must belong to the captured cluster.', leader)
    heights = planned_heights(cluster['members'])
    targets = configured_targets(deps, ids)
    await require_no_pending_swarm(deps, ids)
    rpc = deps.get_fleet_rpc_service()
    first = await rpc.read_swarm_samples(targets)
    first_positions = {hw: validate_position_sample(first.get(hw, {}), hw,
                         require_heading=request.frame == 'body') for hw in ids}
    await asyncio.sleep(CAPTURE_DWELL_SEC)
    second = await rpc.read_swarm_samples(targets)
    positions = {hw: validate_position_sample(second.get(hw, {}), hw,
                    require_heading=request.frame == 'body') for hw in ids}
    # One immutable tangent reference for the entire snapshot. It is never
    # written to the mission origin, PX4 home, or the assignment resource.
    reference_position = positions[request.cluster_id]
    reference = (reference_position['latitude'], reference_position['longitude'], reference_position['altitude_msl'])
    observations, earliest, latest = {}, [], []
    current_heights_reason = None
    for hw in ids:
        position, prior = positions[hw], first_positions[hw]
        activity = second[hw]['sample']['capture_activity']
        prior_activity = first[hw]['sample']['capture_activity']
        # Keep-plan and level capture do not import GNSS/barometric height noise.
        # Current heights are an explicit airborne-only option using one MSL datum,
        # never unrelated local-down or above-home coordinates.
        height_reason = None
        if any(a.get('is_armed') is not True or a.get('landed_state') != 2
               for a in (activity, prior_activity)):
            height_reason = 'Current heights require every aircraft hovering. On the ground, use Keep plan or Same height.'
        elif abs(position['altitude_msl'] - prior['altitude_msl']) > CAPTURE_MAX_DRIFT_M:
            height_reason = f'H{hw}: Height changed during capture. Let the aircraft settle and Refresh.'
        if current_heights_reason is None and height_reason:
            current_heights_reason = height_reason
        if position['position_timestamp_ms'] <= prior['position_timestamp_ms']:
            reject('capture_position_not_advancing', 'Position samples did not advance during capture. Refresh telemetry.', hw)
        north, east, down = navpy.lla2ned(position['latitude'], position['longitude'], position['altitude_msl'],
                                         *reference, latlon_unit='deg', alt_unit='m', model='wgs84')
        drift = navpy.lla2ned(position['latitude'], position['longitude'], position['altitude_msl'],
                            prior['latitude'], prior['longitude'], prior['altitude_msl'],
                            latlon_unit='deg', alt_unit='m', model='wgs84')
        if math.hypot(float(drift[0]), float(drift[1])) > CAPTURE_MAX_DRIFT_M:
            reject('capture_aircraft_moving', 'Aircraft position changed during capture. Let the formation settle.', hw)
        heading, old_heading = position['heading_deg'], prior['heading_deg']
        if heading is not None and old_heading is not None:
            if position['attitude_timestamp_ms'] <= prior['attitude_timestamp_ms']:
                reject('capture_heading_not_advancing', 'Heading samples did not advance during capture.', hw)
            if abs((heading - old_heading + 180) % 360 - 180) > CAPTURE_MAX_YAW_CHANGE_DEG:
                reject('capture_aircraft_turning', 'Aircraft heading changed during capture. Let the formation settle.', hw)
        received = second[hw]['received_monotonic'] * 1000
        source_age = _source_age(second[hw]['sample'], 'global_position_timestamp_ms', hw)
        earliest.append(received - source_age - second[hw]['round_trip_ms'])
        latest.append(received - source_age)
        observations[hw] = {**position, 'altitude_msl_m': position['altitude_msl'],
            'north_m': float(north), 'east_m': float(east), 'planned_up_m': heights[hw],
            'current_up_m': position['altitude_msl'] - reference[2],
            'received_at_ms': second[hw]['received_at_ms'], 'round_trip_ms': second[hw]['round_trip_ms']}
    if max(latest) - min(earliest) > CAPTURE_MAX_SKEW_MS:
        reject('capture_samples_incoherent', 'Aircraft samples are too far apart in time. Refresh after links settle.')
    if request.height_mode == 'current' and current_heights_reason:
        reject('capture_current_heights_unavailable', current_heights_reason)
    candidate = captured_assignments(draft, observations, ids, leader, request.frame, request.height_mode)
    async with configuration_lock(deps):
        if topology_revision(deps.load_swarm() or []) != current_revision:
            reject('capture_revision_conflict', 'The saved formation changed during capture. Review it before retrying.')
        await recheck_inactive_scope(deps, ids, second)
    return {'capture_id': str(uuid.uuid4()), 'captured_at_ms': int(time.time() * 1000),
            'revision': current_revision, 'cluster_id': leader, 'assignments': candidate,
            'headings': {hw: p['heading_deg'] for hw, p in positions.items() if p['heading_deg'] is not None},
            'observations': observations, 'height_mode': request.height_mode,
            'current_heights_available': current_heights_reason is None,
            'current_heights_reason': current_heights_reason,
            'reference': {'latitude': reference[0], 'longitude': reference[1], 'altitude_msl_m': reference[2]},
            'saved': False, 'commands_sent': False}
