import React from 'react';
import { buildCommandSchedule, COMMAND_SCHEDULE_MODES, formatClockOffsetLabel } from '../utilities/commandScheduling';
import { formatShowStart } from '../utilities/droneShowWorkspace';
import '../styles/ShowScheduleFields.css';

export default function ShowScheduleFields({ value, onChange, referenceNowMs, disabled = false }) {
  const schedule = buildCommandSchedule({ ...value, referenceNowMs });
  const clockWarning = formatClockOffsetLabel(Date.now() - referenceNowMs);
  return <div className="show-schedule-fields">
    <label>Start<select aria-label="Start timing" value={value.scheduleMode} disabled={disabled}
      onChange={e => onChange({ ...value, scheduleMode: e.target.value })}>
      <option value={COMMAND_SCHEDULE_MODES.NOW}>When ready</option>
      <option value={COMMAND_SCHEDULE_MODES.DELAY}>After delay</option>
      <option value={COMMAND_SCHEDULE_MODES.ABSOLUTE}>At time</option>
    </select></label>
    {value.scheduleMode === COMMAND_SCHEDULE_MODES.DELAY && <label>Delay (s)<input aria-label="Launch delay"
      type="number" min="0" step="1" value={value.timeDelay} disabled={disabled}
      onChange={e => onChange({ ...value, timeDelay: e.target.value })} /></label>}
    {value.scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE && <label>Time (browser local timezone)<input
      aria-label="Execution time" type="datetime-local" step="1" value={value.selectedDateTime} disabled={disabled}
      onChange={e => onChange({ ...value, selectedDateTime: e.target.value })} /></label>}
    <small>{schedule.error || (value.scheduleMode === COMMAND_SCHEDULE_MODES.NOW ? formatShowStart(0) : schedule.summary)}</small>
    {clockWarning && <small role="status">{clockWarning}</small>}
  </div>;
}
