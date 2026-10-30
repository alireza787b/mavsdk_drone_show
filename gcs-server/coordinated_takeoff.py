"""Command-journal-owned all-armed barrier for standalone fleet takeoff.

This is a tracker projection, not another mission manager. Monotonic receipts
are valid only in the issuing GCS process; a restart always fences old permits.
"""
from __future__ import annotations

import secrets
import time

STATE_KEY = '_coordinated_takeoff'


def coordinated(command):
    return command.mission_type == 10 and command.params.get('takeoff_mode') == 'coordinated' and len(command.target_drones) > 1


def public_snapshot(command):
    state = command.params.get(STATE_KEY)
    if not state:
        return None
    targets = {hw: {key: value for key, value in row.items()
                    if key in {'state', 'armed', 'landed_state', 'reason', 'received_at_ms'}}
               for hw, row in state.get('targets', {}).items()}
    return dict(phase=state['phase'], reason=state.get('reason'),
                armed_count=sum(row.get('verified_ready') or row.get('state') == 'airborne' for row in state.get('targets', {}).values()),
                total=len(command.target_drones), targets=targets,
                release_at_unix_ms=state.get('release_at_unix_ms'))


def durable_params(params):
    """Persist decisions/phase evidence, never process-local freshness authority."""
    result = dict(params)
    state = params.get(STATE_KEY)
    if state:
        result[STATE_KEY] = {key: value for key, value in state.items()
            if key in {'phase', 'reason', 'release_at_unix_ms'}}
        result[STATE_KEY]['targets'] = {hw: {key: value for key, value in row.items()
            if key in {'state', 'armed', 'landed_state', 'reason', 'received_at_ms'}}
            for hw, row in state.get('targets', {}).items()}
    return result


class CoordinatedTakeoffTrackerMixin:
    """Uses the owning CommandTracker's lock, callback auth and durable journal."""

    async def initialize_coordinated_takeoff(self, command_id, params):
        async with self._lock:
            command = self._commands.get(command_id)
            if command is None or self._is_terminal(command) or not coordinated(command):
                return False
            if STATE_KEY in command.params:
                return command.params[STATE_KEY]['phase'] != 'aborted'  # Never renew authority.
            command.params[STATE_KEY] = dict(phase='arming', targets={}, reason=None,
                release_at_unix_ms=None, first_armed_monotonic=None,
                boot_id=self._takeoff_boot_id,
                report_max_age_sec=float(getattr(params, 'COORDINATED_TAKEOFF_REPORT_MAX_AGE_SEC', 1.0)),
                release_delay_sec=float(getattr(params, 'COORDINATED_TAKEOFF_RELEASE_DELAY_SEC', 1.5)),
                release_guard_sec=float(getattr(params, 'COORDINATED_TAKEOFF_RELEASE_GUARD_SEC', .5)),
                arm_timeout_sec=float(getattr(params, 'COORDINATED_TAKEOFF_ARM_BARRIER_TIMEOUT_SEC', 8.0)))
            await self._persist_command_locked(command, event_type='takeoff_barrier_initialized')
            return True

    async def abort_coordinated_takeoff(self, command_id, reason, *, before_release_only=False):
        async with self._lock:
            command = self._commands.get(command_id)
            state = command.params.get(STATE_KEY) if command else None
            if not state:
                raise ValueError('No coordinated takeoff operation')
            if before_release_only and state.get('release_at_unix_ms') is not None:
                raise ValueError('Takeoff was released; use Hold or Return')
            if state['phase'] != 'aborted':
                state.update(phase='aborted', reason=str(reason)[:300])
                command.updated_at = int(time.time() * 1000)
                await self._persist_command_locked(command, event_type='takeoff_barrier_aborted',
                    event_data={'reason': state['reason']})
            return public_snapshot(command)

    async def record_takeoff_stage(self, report, callback_capability=None):
        # Import here avoids a circular dependency with the tracker owner.
        from command_tracker import CommandCallbackAuthenticationError
        async with self._lock:
            command = self._commands.get(report.command_id)
            if command is None or not self._callback_capability_matches_locked(command, report.hw_id, callback_capability):
                raise CommandCallbackAuthenticationError('Command callback authentication failed')
            state = command.params.get(STATE_KEY)
            now, wall_ms = time.monotonic(), int(time.time() * 1000)
            if not state or not coordinated(command):
                return dict(schema_version=1, decision='abort', reason='No coordinated takeoff operation', server_time_unix_ms=wall_ms)
            old_phase = state['phase']

            def abort(reason):
                state.update(phase='aborted', reason=reason)

            if state.get('boot_id') != self._takeoff_boot_id:
                abort('Ground system restarted; review and retry takeoff')
            if self._is_terminal(command) or command.params.get('_swarm_stop_requested'):
                abort('Takeoff operation ended or was superseded')
            if any(not item.success for item in command.executions.values()):
                abort('A required aircraft failed takeoff')
            if any(ack.category != 'accepted' for ack in command.acks.values()):
                abort('A required aircraft did not accept takeoff')
            if state['phase'] == 'aborted':
                if old_phase != 'aborted':
                    await self._persist_command_locked(command, event_type='takeoff_barrier_aborted')
                return dict(schema_version=1, decision='abort', reason=state.get('reason'), server_time_unix_ms=wall_ms)

            previous = state['targets'].get(report.hw_id, {})
            fresh_challenge = (bool(report.challenge) and secrets.compare_digest(report.challenge, previous.get('challenge', ''))
                and 0 <= now - previous.get('challenge_issued_monotonic', float('-inf')) <= state['report_max_age_sec'])
            new_sequence = report.sequence > previous.get('sequence', -1)
            if new_sequence:
                row = {**report.model_dump(exclude={'command_id', 'hw_id', 'challenge'}),
                       'received_at_ms': wall_ms, 'received_monotonic': now,
                       'verified_ready': fresh_challenge and report.state == 'armed_ready'
                           and report.armed and report.landed_state == 'ON_GROUND'}
                if report.state == 'failed':
                    abort(report.reason or f'Aircraft {report.hw_id} could not take off')
                elif report.state == 'armed_ready' and (not report.armed or report.landed_state != 'ON_GROUND'):
                    abort(f'Aircraft {report.hw_id} no longer confirms armed on ground')
                elif report.state == 'airborne' and (state.get('release_at_unix_ms') is None
                        or wall_ms < state['release_at_unix_ms'] or not report.armed
                        or report.landed_state not in {'TAKING_OFF', 'IN_AIR'}):
                    abort(f'Aircraft {report.hw_id} flight state does not match launch')
                elif report.state == 'armed_ready' and previous.get('verified_ready') and not fresh_challenge:
                    abort(f'Aircraft {report.hw_id} readiness confirmation expired')
                if row['verified_ready'] and state['first_armed_monotonic'] is None:
                    state['first_armed_monotonic'] = now
                row.update(challenge=secrets.token_urlsafe(24), challenge_issued_monotonic=now)
                state['targets'][report.hw_id] = row
            else:
                row = previous

            rows = state['targets']
            if state['phase'] not in {'aborted', 'airborne'}:
                if state['first_armed_monotonic'] is not None and now - state['first_armed_monotonic'] >= state['arm_timeout_sec'] and state['phase'] == 'arming':
                    abort('Not all aircraft armed before the launch window expired')
                # Once observed armed-ready, a missing heartbeat fences the
                # whole operation, including the scheduled pre-release window.
                elif (state.get('release_at_unix_ms') is None or wall_ms < state['release_at_unix_ms']) and any(item.get('verified_ready') and now - item['received_monotonic'] > state['report_max_age_sec']
                         for item in rows.values()):
                    abort('An aircraft readiness heartbeat expired')
                elif state['phase'] == 'arming' and all(rows.get(hw, {}).get('verified_ready') for hw in command.target_drones) and all(
                    hw in command.acks and command.acks[hw].category == 'accepted' for hw in command.target_drones
                ):
                    minimum_lease = min(item['lease_remaining_ms'] - (now - item['received_monotonic']) * 1000 for item in rows.values())
                    if minimum_lease <= (state['release_delay_sec'] + state['release_guard_sec']) * 1000:
                        abort('Armed waiting window is too short to release takeoff')
                    else:
                        state.update(phase='released', release_at_unix_ms=wall_ms + int(state['release_delay_sec'] * 1000))
                elif all(rows.get(hw, {}).get('state') == 'airborne' for hw in command.target_drones):
                    state['phase'] = 'airborne'
            command.updated_at = wall_ms
            if old_phase != state['phase'] or previous.get('state') != row.get('state') or previous.get('verified_ready') != row.get('verified_ready'):
                await self._persist_command_locked(command, event_type='takeoff_stage', hw_ids=[report.hw_id],
                    event_data={'state': report.state, 'phase': state['phase']})
            return dict(schema_version=1, decision='abort' if state['phase'] == 'aborted' else
                'release' if state['phase'] in {'released', 'airborne'} else 'wait',
                release_at_unix_ms=state.get('release_at_unix_ms') if state['phase'] in {'released', 'airborne'} else None, reason=state.get('reason'),
                challenge=row.get('challenge'), server_time_unix_ms=wall_ms)
