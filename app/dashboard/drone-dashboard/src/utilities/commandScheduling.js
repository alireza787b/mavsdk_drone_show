import { getDroneReferenceNowMs } from './droneRuntimeStatus';

export const COMMAND_SCHEDULE_MODES = {
  NOW: 'now',
  DELAY: 'delay',
  ABSOLUTE: 'absolute',
};

export const COMMAND_DELAY_PRESETS = [10, 30, 60];
export const CLOCK_OFFSET_WARNING_THRESHOLD_MS = 30_000;

function pad(value) {
  return String(value).padStart(2, '0');
}

export function formatDateTimeLocalInput(dateLike) {
  const date = new Date(dateLike);
  if (Number.isNaN(date.getTime())) {
    return '';
  }

  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function getFleetReferenceClock(drones = [], nowMs = Date.now()) {
  const candidates = drones
    .filter(Boolean)
    .map((drone) => {
      const referenceNowMs = getDroneReferenceNowMs(drone, nowMs);
      const timestampMs = Number(drone?.update_time ?? drone?.timestamp ?? 0);
      return {
        referenceNowMs,
        timestampMs,
      };
    })
    .filter((entry) => Number.isFinite(entry.referenceNowMs));

  if (candidates.length === 0) {
    return {
      referenceNowMs: nowMs,
      offsetMs: 0,
      isServerAligned: false,
    };
  }

  candidates.sort((left, right) => right.timestampMs - left.timestampMs);
  const referenceNowMs = candidates[0].referenceNowMs;

  return {
    referenceNowMs,
    offsetMs: nowMs - referenceNowMs,
    isServerAligned: true,
  };
}

export function formatClockOffsetLabel(offsetMs = 0) {
  const roundedSeconds = Math.round(Math.abs(offsetMs) / 1000);
  if (roundedSeconds <= 0 || Math.abs(offsetMs) < CLOCK_OFFSET_WARNING_THRESHOLD_MS) {
    return null;
  }

  return `Browser clock ${offsetMs > 0 ? '+' : '-'}${roundedSeconds}s vs GCS`;
}

export function formatCommandAbsoluteTime(unixSeconds) {
  const numeric = Number(unixSeconds);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return 'Immediate on acceptance';
  }

  return new Date(numeric * 1000).toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  });
}

export function buildCommandSchedule({
  scheduleMode = COMMAND_SCHEDULE_MODES.DELAY,
  timeDelay = 10,
  selectedDateTime = '',
  referenceNowMs = Date.now(),
}) {
  const safeReferenceNowMs = Number.isFinite(referenceNowMs) ? referenceNowMs : Date.now();
  const delaySeconds = Math.max(0, Number.parseInt(timeDelay, 10) || 0);

  if (scheduleMode === COMMAND_SCHEDULE_MODES.NOW) {
    return {
      scheduleMode,
      triggerTimeSec: 0,
      absoluteMs: safeReferenceNowMs,
      summary: 'Immediate on acceptance',
      detail: 'Runs as soon as each target accepts the command.',
      isImmediate: true,
      error: null,
    };
  }

  if (scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE) {
    const selectedMs = Date.parse(selectedDateTime);
    if (!Number.isFinite(selectedMs)) {
      return {
        scheduleMode,
        triggerTimeSec: null,
        absoluteMs: null,
        summary: 'Select an exact execution time',
        detail: 'Choose a valid future date and time.',
        isImmediate: false,
        error: 'Choose a valid future execution time.',
      };
    }

    if (selectedMs <= safeReferenceNowMs) {
      return {
        scheduleMode,
        triggerTimeSec: null,
        absoluteMs: selectedMs,
        summary: 'Selected execution time has already passed',
        detail: 'Choose a future time based on the GCS clock.',
        isImmediate: false,
        error: 'The selected execution time has already passed on the GCS clock.',
      };
    }

    const triggerTimeSec = Math.floor(selectedMs / 1000);
    return {
      scheduleMode,
      triggerTimeSec,
      absoluteMs: selectedMs,
      summary: `Executes at ${formatCommandAbsoluteTime(triggerTimeSec)}`,
      detail: 'Absolute schedule using the GCS-aligned command clock.',
      isImmediate: false,
      error: null,
    };
  }

  const absoluteMs = safeReferenceNowMs + (delaySeconds * 1000);
  const triggerTimeSec = Math.floor(absoluteMs / 1000);

  return {
    scheduleMode: COMMAND_SCHEDULE_MODES.DELAY,
    triggerTimeSec,
    absoluteMs,
    summary: `Executes in ${delaySeconds}s · ${formatCommandAbsoluteTime(triggerTimeSec)}`,
    detail: `GCS trigger time: ${formatCommandAbsoluteTime(triggerTimeSec)}`,
    isImmediate: delaySeconds === 0,
    error: null,
  };
}
