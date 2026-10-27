import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { buildCommandSchedule, COMMAND_SCHEDULE_MODES } from './commandScheduling';

export const SHOW_MODES = [
  { value: 'global-auto', label: 'Global · auto correction' },
  { value: 'global-manual', label: 'Global · manual placement' },
  { value: 'local', label: 'Local · launch frame' },
];

export function showReadiness({ workspace, operation, mode, origin, deviations }) {
  const fleet = operation?.fleet || [];
  const slots = workspace?.package?.position_ids || [];
  const assigned = fleet.map((row) => String(row.pos_id));
  const packageReady = workspace?.package?.available === true && slots.length > 0;
  const mappingReady = packageReady && slots.length === assigned.length
    && new Set(assigned).size === assigned.length && slots.every((slot) => assigned.includes(String(slot)));
  const fleetReady = fleet.length > 0 && fleet.every((d) => d.telemetry_fresh && d.ready_to_arm && d.armed === false);
  const globalAuto = mode === 'global-auto';
  const originReady = !globalAuto || (origin?.lat != null && origin?.lon != null && origin.lat !== '' && origin.lon !== '');
  const geometryReady = !globalAuto || (originReady && fleet.every((d) => {
    const row = deviations?.deviations?.[d.hw_id];
    return row && ['ok', 'good', 'success', 'warning'].includes(row.status);
  }));
  const analysisReady = workspace?.validation?.validation_status !== 'FAIL';
  return { packageReady, mappingReady, fleetReady, originReady, geometryReady, analysisReady,
    ready: Boolean(packageReady && mappingReady && fleetReady && originReady && geometryReady && analysisReady) };
}

export function buildShowCommand(action, targetIds, { mode = 'global-auto', delay = 10, referenceNowMs } = {}) {
  if (!targetIds.length) throw new Error('No aircraft selected');
  const mission = { launch: DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV,
    hold: DRONE_ACTION_TYPES.HOLD, land: DRONE_ACTION_TYPES.LAND,
    rtl: DRONE_ACTION_TYPES.RETURN_RTL, cancel: DRONE_MISSION_TYPES.NONE }[action];
  if (mission == null) throw new Error('Unsupported show action');
  const command = { mission_type: mission, target_drone_ids: [...targetIds], trigger_time: 0,
    operator_label: `Drone Show · ${action}` };
  if (action === 'launch') {
    if (!Number.isFinite(Number(delay)) || Number(delay) < 10 || Number(delay) > 3600) throw new Error('Use a launch delay from 10 to 3600 seconds');
    const schedule = buildCommandSchedule({ scheduleMode: COMMAND_SCHEDULE_MODES.DELAY,
      timeDelay: delay, referenceNowMs });
    command.trigger_time = schedule.triggerTimeSec;
    command.auto_global_origin = mode === 'global-auto';
    command.use_global_setpoints = mode !== 'local';
  }
  return command;
}
