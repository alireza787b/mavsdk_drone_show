import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import {
  FaPlaneDeparture, FaHandHolding, FaPlaneArrival, FaVial, FaLightbulb,
  FaSyncAlt, FaPowerOff, FaHome, FaRocket, FaSkull, FaClock, FaCrosshairs, FaBan,
} from 'react-icons/fa';
import { DRONE_ACTION_NAMES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { COMMAND_METADATA_BY_KEY } from '../constants/missionCatalog';
import {
  buildCommandSchedule, COMMAND_DELAY_PRESETS, COMMAND_SCHEDULE_MODES, formatDateTimeLocalInput,
} from '../utilities/commandScheduling';
import { getActionExecutionPolicy, isSchedulableActionKey } from '../utilities/commandExecutionPolicy';
import '../styles/DroneActions.css';

const ACTION_SECTIONS = [
  { key: 'primary', title: 'Flight controls', actions: ['TAKE_OFF', 'HOLD', 'LAND', 'RETURN_RTL'] },
  { key: 'test', title: 'Ground tests', actions: ['TEST', 'TEST_LED'] },
  { key: 'flight', title: 'Flight actions', actions: ['HOVER_TEST', 'PRECISION_MOVE', 'NONE'] },
  { key: 'service', title: 'Service', actions: ['REBOOT_FC', 'REBOOT_SYS'] },
  { key: 'danger', title: 'Danger', actions: ['KILL_TERMINATE'] },
];

const ACTION_PRESENTATION = {
  TAKE_OFF: { icon: FaPlaneDeparture },
  HOLD: { icon: FaHandHolding },
  LAND: { icon: FaPlaneArrival },
  RETURN_RTL: { icon: FaHome },
  TEST: { icon: FaVial, label: 'Motor-arm test', description: 'Motors arm briefly. Remove propellers and secure aircraft.' },
  TEST_LED: { icon: FaLightbulb, label: 'LED test', description: 'Run the light pattern.' },
  HOVER_TEST: { icon: FaRocket, label: 'Hover flight test', description: 'Take off, fly the test, then land. Not Hold.' },
  PRECISION_MOVE: { icon: FaCrosshairs, label: 'Move', description: 'Move an offset, then hold.' },
  NONE: { icon: FaBan, label: 'Cancel mission', description: 'Cancel the mission. Not a Hold or landing command.' },
  REBOOT_FC: { icon: FaPowerOff, label: 'Restart flight controller', description: 'Restart PX4 and flight-control services.' },
  REBOOT_SYS: { icon: FaSyncAlt, label: 'Restart companion', description: 'Restart the computer or SITL container.' },
  KILL_TERMINATE: { icon: FaSkull, label: 'Stop motors', description: 'Immediate motor stop. Airborne aircraft will fall.' },
};

export default function DroneActions({
  actionTypes,
  onSendCommand,
  onRequestPrecisionMove,
  canPrecisionMove = false,
  includeFlightControls = false,
  targetCount = 0,
  takeoffAltitude = 10,
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
  runtimeMode = 'unknown',
}) {
  const [scheduleMode, setScheduleMode] = useState(COMMAND_SCHEDULE_MODES.NOW);
  const [timeDelay, setTimeDelay] = useState(30);
  const [selectedDateTime, setSelectedDateTime] = useState(() => formatDateTimeLocalInput(referenceNowMs + 60_000));
  const normalizedRuntimeMode = String(runtimeMode || '').trim().toLowerCase();
  const groundTestRuntimeKnown = ['real', 'sitl'].includes(normalizedRuntimeMode);
  const actionSchedule = useMemo(() => buildCommandSchedule({
    scheduleMode, timeDelay, selectedDateTime, referenceNowMs,
  }), [referenceNowMs, scheduleMode, selectedDateTime, timeDelay]);

  const disabledReason = (actionKey) => {
    if (targetCount < 1) return 'No aircraft targeted.';
    if (actionKey === 'TEST' && !groundTestRuntimeKnown) return 'Runtime mode unknown. Motor-arm test unavailable.';
    if (actionKey === 'PRECISION_MOVE' && (!canPrecisionMove || !onRequestPrecisionMove)) {
      return 'Requires current airborne telemetry for every target.';
    }
    return null;
  };

  const handleActionClick = (actionKey) => {
    if (disabledReason(actionKey)) return;
    if (actionKey === 'PRECISION_MOVE') {
      onRequestPrecisionMove();
      return;
    }
    const supportsScheduling = isSchedulableActionKey(actionKey);
    if (supportsScheduling && actionSchedule.error) {
      toast.error(actionSchedule.error);
      return;
    }
    const actionTypeValue = actionKey === 'NONE' ? DRONE_MISSION_TYPES.NONE : actionTypes[actionKey];
    const operatorLabel = DRONE_ACTION_NAMES[actionTypeValue] || COMMAND_METADATA_BY_KEY[actionKey].commandLabel;
    const commandData = {
      mission_type: actionTypeValue,
      trigger_time: supportsScheduling ? (actionSchedule.triggerTimeSec ?? 0) : 0,
      uiMeta: {
        actionKey,
        operatorLabel,
        triggerSummary: supportsScheduling ? actionSchedule.summary : 'Immediate on acceptance',
        confirmationMessage: actionKey === 'TEST'
          ? (normalizedRuntimeMode === 'sitl'
            ? `${operatorLabel} → ${targetCount} SITL drone${targetCount === 1 ? '' : 's'}. Confirm the simulation-only motor-arm test.`
            : `${operatorLabel} → ${targetCount} targeted drone${targetCount === 1 ? '' : 's'}. Confirm only after all propellers are removed, every airframe is secured, and the test area is clear.`)
          : `${operatorLabel} → ${targetCount} targeted drone${targetCount === 1 ? '' : 's'}. Confirm dispatch.`,
        details: [
          ...(supportsScheduling && !actionSchedule.isImmediate ? [{ label: 'Dispatch mode', value: 'Scheduled action' }] : []),
          ...(actionKey === 'TAKE_OFF' ? [{ label: 'Takeoff altitude', value: `${takeoffAltitude} m` }] : []),
          ...(actionKey === 'TEST' ? [{
            label: 'Ground-test safety',
            value: normalizedRuntimeMode === 'sitl'
              ? 'Simulation-only motor-arm test. Physical checks are not applicable in SITL.'
              : 'Motors will arm. Confirm propellers removed, airframes secured, and area clear in the action review.',
          }] : []),
          ...(actionKey === 'HOVER_TEST' ? [{
            label: 'Flight behavior',
            value: 'This action launches, flies the configured hover-test trajectory, and lands; it is not a Hold command.',
          }] : []),
          ...(actionKey === 'NONE' ? [{ label: 'Cancellation', value: 'Cancellation alone is not verified Hold or landing.' }] : []),
          {
            label: 'Execution policy',
            value: getActionExecutionPolicy({ actionKey, isImmediate: supportsScheduling ? actionSchedule.isImmediate : true }),
          },
        ],
      },
    };
    if (actionKey === 'TAKE_OFF') commandData.takeoff_altitude = takeoffAltitude;
    // This is an intent for review, never a physical safety acknowledgement.
    // The shared ActionReview collects checks and constructs ground_test_safety.
    onSendCommand(commandData);
  };

  return <div className="drone-actions">
    {ACTION_SECTIONS.filter((section) => includeFlightControls || section.key !== 'primary').map((section) => (
      <section key={section.key} className={`drone-actions__group drone-actions__group--${section.key}`} aria-label={section.title}>
        <h3>{section.title}</h3>
        {section.actions.map((actionKey) => {
          const { icon: Icon, label, description } = ACTION_PRESENTATION[actionKey];
          const metadata = COMMAND_METADATA_BY_KEY[actionKey];
          const unavailable = disabledReason(actionKey);
          const visibleLabel = label || metadata.shortLabel;
          const accessibleLabel = visibleLabel.toLowerCase() !== metadata.commandLabel.toLowerCase()
            ? `${visibleLabel} (${metadata.commandLabel})` : metadata.commandLabel;
          return <button key={actionKey} type="button" className="drone-actions__action"
            disabled={Boolean(unavailable)} onClick={() => handleActionClick(actionKey)}
            title={unavailable || metadata.commandLabel}
            aria-label={`${accessibleLabel}. ${description || metadata.description}`}>
            <Icon aria-hidden="true" />
            <span><strong>{visibleLabel}</strong><small>{unavailable || description || metadata.description}</small></span>
          </button>;
        })}
      </section>
    ))}
    <details className="drone-actions__timing">
      <summary tabIndex={0}><FaClock aria-hidden="true" /><span>Advanced timing</span><small>{actionSchedule.summary}</small></summary>
      <div className="drone-actions__timing-body">
        <div className="drone-actions__timing-modes" role="group" aria-label="Execution timing">
          {[
            [COMMAND_SCHEDULE_MODES.NOW, 'Now'], [COMMAND_SCHEDULE_MODES.DELAY, 'Delay'], [COMMAND_SCHEDULE_MODES.ABSOLUTE, 'Exact time'],
          ].map(([mode, label]) => <button key={mode} type="button" aria-pressed={scheduleMode === mode}
            onClick={() => setScheduleMode(mode)}>{label}</button>)}
        </div>
        {scheduleMode === COMMAND_SCHEDULE_MODES.DELAY && <>
          <div className="drone-actions__presets" role="group" aria-label="Delay presets">
            {COMMAND_DELAY_PRESETS.map((preset) => <button key={preset} type="button" aria-pressed={Number(timeDelay) === preset}
              onClick={() => setTimeDelay(preset)}>+{preset}s</button>)}
          </div>
          <label>Delay (s)<input type="number" min="0" step="1" value={timeDelay}
            onChange={(event) => setTimeDelay(Number(event.target.value))} /></label>
        </>}
        {scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE && <label>Trigger time (browser timezone)
          <input type="datetime-local" step="1" value={selectedDateTime} onChange={(event) => setSelectedDateTime(event.target.value)} />
        </label>}
        <p>Timing applies to flight and test actions. Move, cancellation, restarts and motor stop are immediate.
          {clockOffsetLabel ? ` ${clockOffsetLabel}.` : ' Uses the GCS clock.'}</p>
        {actionSchedule.error && <p role="alert">{actionSchedule.error}</p>}
      </div>
    </details>
  </div>;
}

DroneActions.propTypes = {
  actionTypes: PropTypes.object.isRequired,
  onSendCommand: PropTypes.func.isRequired,
  onRequestPrecisionMove: PropTypes.func,
  canPrecisionMove: PropTypes.bool,
  includeFlightControls: PropTypes.bool,
  targetCount: PropTypes.number,
  takeoffAltitude: PropTypes.number,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
  runtimeMode: PropTypes.oneOf(['real', 'sitl', 'unknown']),
};
