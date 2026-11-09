import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { buildCommandSchedule, COMMAND_SCHEDULE_MODES, formatCommandAbsoluteTime } from './commandScheduling';

export function formatShowStart(triggerTimeSec) {
  return Number(triggerTimeSec) === 0 ? 'Synchronized start after aircraft checks' : formatCommandAbsoluteTime(triggerTimeSec);
}

export function formatShowOperationStart(operation, referenceNowMs, fresh) {
  const command = operation?.command;
  if (operation?.state !== 'active' || ![1, 3].includes(Number(command?.mission_type ?? operation?.mission_type))) return null;
  if (!fresh || !Number.isFinite(referenceNowMs)) return 'Start timing unconfirmed';
  const seconds = Number(command?.params?.trigger_time);
  const triggerMs = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000
    : Number(command?.progress?.scheduled_trigger_time);
  if (!Number.isFinite(triggerMs) || triggerMs <= 0) return 'Preparing synchronized start';
  const remaining = Math.ceil((triggerMs - referenceNowMs) / 1000);
  return remaining > 0 ? `Start in ${remaining} s · ${formatShowStart(triggerMs / 1000)}`
    : `Scheduled start · ${formatShowStart(triggerMs / 1000)}`;
}

export const SHOW_MODES = [
  { value: 'global-auto', label: 'Global · auto correction' },
  { value: 'global-manual', label: 'Global · manual placement' },
  { value: 'local', label: 'Local · launch frame' },
];

export function showReadiness({ workspace, operation, mode, origin, deviations, targetIds }) {
  const allFleet = operation?.fleet || [];
  const ids = targetIds?.map(String);
  const fleet = ids ? allFleet.filter(d => ids.includes(String(d.hw_id))) : allFleet;
  const slots = workspace?.package?.position_ids || [];
  const assigned = fleet.map((row) => String(row.pos_id));
  const packageReady = workspace?.package?.available === true && slots.length > 0;
  const mappingReady = packageReady && fleet.length > 0 && (!ids || fleet.length === ids.length)
    && new Set(assigned).size === assigned.length
    && assigned.every(slot => slots.map(String).includes(slot))
    && assigned.every(slot => allFleet.filter(d => String(d.pos_id) === slot).length === 1);
  const fleetReady = fleet.length > 0 && fleet.every((d) => d.telemetry_fresh && d.ready_to_arm && d.armed === false);
  const globalAuto = mode === 'global-auto';
  const originReady = !globalAuto || (origin?.lat != null && origin?.lon != null && origin.lat !== '' && origin.lon !== '');
  const geometrySummary = deviations?.summary || {};
  const geometryRows = fleet.map((d) => deviations?.deviations?.[d.hw_id]).filter(Boolean);
  const hasGeometryErrors = geometryRows.some((row) => ['error', 'no_telemetry'].includes(row.status));
  const geometryWarning = geometryRows.some((row) => row.status === 'warning');
  const geometryReady = !globalAuto || (originReady && geometryRows.length === fleet.length && !hasGeometryErrors);
  const analysisStatus = workspace?.validation?.validation_status || 'UNKNOWN';
  const analysisReady = analysisStatus !== 'FAIL' && analysisStatus !== 'UNKNOWN';
  const geometryState = !globalAuto ? 'review'
    : !originReady || !geometryRows.length ? 'blocked'
      : hasGeometryErrors ? 'blocked' : geometryWarning ? 'review' : 'ready';
  const readinessState = !packageReady || !mappingReady || !fleetReady || !originReady || !geometryReady || !analysisReady
    ? 'blocked' : geometryState === 'review' || analysisStatus === 'WARNING' ? 'review' : 'ready';
  return {
    packageReady, mappingReady, fleetReady, originReady, geometryReady, analysisReady,
    geometryState, geometrySummary, geometryRows, analysisStatus,
    ready: readinessState !== 'blocked', readinessState,
  };
}

export function buildShowCommand(action, targetIds, { mode = 'global-auto', delay = 10, referenceNowMs,
  scheduleMode = COMMAND_SCHEDULE_MODES.DELAY, selectedDateTime = '', custom = false } = {}) {
  if (!targetIds.length) throw new Error('No aircraft selected');
  const mission = { launch: custom ? DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW : DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV,
    hold: DRONE_ACTION_TYPES.HOLD, land: DRONE_ACTION_TYPES.LAND,
    rtl: DRONE_ACTION_TYPES.RETURN_RTL, cancel: DRONE_MISSION_TYPES.NONE }[action];
  if (mission == null) throw new Error('Unsupported show action');
  const command = { mission_type: mission, target_drone_ids: [...new Set(targetIds.map(String))], trigger_time: 0,
    operator_label: `${custom ? 'Custom CSV' : 'Drone Show'} · ${action}` };
  if (action === 'launch') {
    if (scheduleMode === COMMAND_SCHEDULE_MODES.DELAY
      && (String(delay).trim() === '' || !Number.isInteger(Number(delay)) || Number(delay) < 0)) {
      throw new Error('Use a non-negative whole-second launch delay');
    }
    const schedule = buildCommandSchedule({ scheduleMode, selectedDateTime, timeDelay: delay, referenceNowMs });
    if (schedule.error) throw new Error(schedule.error);
    command.trigger_time = schedule.triggerTimeSec;
    command.auto_global_origin = !custom && mode === 'global-auto';
    command.use_global_setpoints = !custom && mode !== 'local';
  }
  return command;
}
