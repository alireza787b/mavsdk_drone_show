// src/components/DroneActions.js

import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import {
  FaPlaneDeparture,
  FaHandHolding,
  FaPlaneArrival,
  FaVial,
  FaLightbulb,
  FaSyncAlt,
  FaPowerOff,
  FaHome,
  FaRocket,
  FaSkull,
  FaClock,
  FaCrosshairs,
} from 'react-icons/fa';
import { DRONE_ACTION_NAMES } from '../constants/droneConstants';
import { COMMAND_METADATA_BY_KEY } from '../constants/missionCatalog';
import {
  buildCommandSchedule,
  COMMAND_DELAY_PRESETS,
  COMMAND_SCHEDULE_MODES,
  formatDateTimeLocalInput,
} from '../utilities/commandScheduling';
import {
  getActionExecutionPolicy,
  isSchedulableActionKey,
} from '../utilities/commandExecutionPolicy';
import '../styles/DroneActions.css';

const ACTION_SECTIONS = [
  {
    key: 'routine',
    title: 'Flight',
    description: 'Launch, hold, land, recover.',
    actions: ['TAKE_OFF', 'HOVER_TEST', 'HOLD', 'PRECISION_MOVE', 'LAND', 'RETURN_RTL'],
  },
  {
    key: 'test',
    title: 'Ground Checks',
    description: 'Physical aircraft checks; follow the displayed safety conditions.',
    actions: ['TEST', 'TEST_LED'],
  },
  {
    key: 'maintenance',
    title: 'Service',
    description: 'Restart flight-control or companion services.',
    actions: ['REBOOT_FC', 'REBOOT_SYS'],
  },
  {
    key: 'danger',
    title: 'Emergency',
    description: 'Last-resort stop.',
    actions: ['KILL_TERMINATE'],
  },
];

const ACTION_ICONS = {
  TAKE_OFF: FaPlaneDeparture,
  LAND: FaPlaneArrival,
  HOLD: FaHandHolding,
  RETURN_RTL: FaHome,
  KILL_TERMINATE: FaSkull,
  TEST: FaVial,
  TEST_LED: FaLightbulb,
  HOVER_TEST: FaRocket,
  PRECISION_MOVE: FaCrosshairs,
  REBOOT_FC: FaPowerOff,
  REBOOT_SYS: FaSyncAlt,
};

const DroneActions = ({
  actionTypes,
  onSendCommand,
  onRequestPrecisionMove,
  targetCount = 0,
  takeoffAltitude = 10,
  onTakeoffAltitudeChange = () => {},
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
  runtimeMode = 'unknown',
}) => {
  const [scheduleMode, setScheduleMode] = useState(COMMAND_SCHEDULE_MODES.NOW);
  const [timeDelay, setTimeDelay] = useState(30);
  const [selectedDateTime, setSelectedDateTime] = useState(() => formatDateTimeLocalInput(referenceNowMs + 60_000));
  const [scheduleOpen, setScheduleOpen] = useState(false);
  const normalizedRuntimeMode = String(runtimeMode || '').trim().toLowerCase();
  const groundTestRuntimeKnown = ['real', 'sitl'].includes(normalizedRuntimeMode);

  const actionSchedule = useMemo(() => buildCommandSchedule({
    scheduleMode,
    timeDelay,
    selectedDateTime,
    referenceNowMs,
  }), [referenceNowMs, scheduleMode, selectedDateTime, timeDelay]);

  const handleActionClick = (actionKey, extraData = {}) => {
    if (actionKey === 'TEST' && !groundTestRuntimeKnown) {
      toast.error('Arm/Disarm Ground Test is unavailable until the active runtime mode is known.');
      return;
    }

    const supportsScheduling = isSchedulableActionKey(actionKey);
    if (supportsScheduling && actionSchedule.error) {
      toast.error(actionSchedule.error);
      return;
    }

    const actionTypeValue = actionTypes[actionKey];
    const commandData = {
      mission_type: actionTypeValue,
      trigger_time: supportsScheduling ? (actionSchedule.triggerTimeSec ?? 0) : 0,
      ...extraData,
    };

    if (actionKey === 'TAKE_OFF') {
      commandData.takeoff_altitude = takeoffAltitude;
    }
    if (actionKey === 'TEST') {
      commandData.ground_test_safety = normalizedRuntimeMode === 'sitl'
        ? { mode: 'sitl_not_applicable' }
        : {
          mode: 'operator_acknowledged',
          props_removed: true,
          airframe_secured: true,
          area_clear: true,
        };
    }

    commandData.uiMeta = {
      operatorLabel: DRONE_ACTION_NAMES[actionTypeValue],
      triggerSummary: supportsScheduling ? actionSchedule.summary : 'Immediate on acceptance',
      confirmationMessage: actionKey === 'TEST'
        ? (
          normalizedRuntimeMode === 'sitl'
            ? `${DRONE_ACTION_NAMES[actionTypeValue]} → ${targetCount} SITL drone${targetCount === 1 ? '' : 's'}. Confirm the simulation-only motor-arm test.`
            : `${DRONE_ACTION_NAMES[actionTypeValue]} → ${targetCount} targeted drone${targetCount === 1 ? '' : 's'}. Confirm only after all propellers are removed, every airframe is secured, and the test area is clear.`
        )
        : `${DRONE_ACTION_NAMES[actionTypeValue]} → ${targetCount} targeted drone${targetCount === 1 ? '' : 's'}. Confirm dispatch.`,
      details: [
        ...(supportsScheduling && !actionSchedule.isImmediate
          ? [{
            label: 'Dispatch mode',
            value: 'Scheduled action',
          }]
          : []),
        ...(actionKey === 'TAKE_OFF'
          ? [{
            label: 'Takeoff altitude',
            value: `${takeoffAltitude} m`,
          }]
          : []),
        ...(actionKey === 'TEST'
          ? [{
            label: 'Ground-test safety',
            value: normalizedRuntimeMode === 'sitl'
              ? 'SITL-only acknowledgement: physical propeller, restraint, and area-clear conditions are not applicable.'
              : 'Motors will arm. Dispatch acknowledges that propellers are removed, every airframe is secured, and the area is clear.',
          }]
          : []),
        ...(actionKey === 'HOVER_TEST'
          ? [{
            label: 'Flight behavior',
            value: 'This action launches, flies the configured hover-test trajectory, and lands; it is not a Hold command.',
          }]
          : []),
        {
          label: 'Execution policy',
          value: getActionExecutionPolicy({
            actionKey,
            isImmediate: supportsScheduling ? actionSchedule.isImmediate : true,
          }),
        },
      ],
    };

    onSendCommand(commandData);
  };

  const renderActionButton = (actionKey, sectionKey) => {
    const Icon = ACTION_ICONS[actionKey];
    const actionTypeValue = actionTypes[actionKey];
    const metadata = COMMAND_METADATA_BY_KEY[actionKey];
    const label = metadata?.shortLabel || DRONE_ACTION_NAMES[actionTypeValue];
    const fullLabel = DRONE_ACTION_NAMES[actionTypeValue];
    const description = metadata?.description || '';
    const isDanger = actionKey === 'KILL_TERMINATE';
    const isCritical = actionKey === 'KILL_TERMINATE';
    const isPrecisionMove = actionKey === 'PRECISION_MOVE';
    const disabledReason = actionKey === 'TEST' && !groundTestRuntimeKnown
      ? 'Active runtime mode is unavailable; the motor-arm test is blocked.'
      : null;

    return (
      <button
        key={actionKey}
        className={`action-button action-button--${sectionKey}${isDanger ? ' action-button--danger' : ''}${isCritical ? ' action-button--critical' : ''}`}
        onClick={() => {
          if (isPrecisionMove) {
            onRequestPrecisionMove();
            return;
          }

          handleActionClick(actionKey);
        }}
        disabled={Boolean(disabledReason)}
        title={disabledReason || `${fullLabel}. ${description}`}
        aria-label={`${fullLabel}. ${description}`}
      >
        <span className="action-button__icon"><Icon className="action-icon" /></span>
        <span className="action-button__content">
          <span className="action-button__title">{label}</span>
          <small className="action-button__summary">{description}</small>
        </span>
      </button>
    );
  };

  return (
    <div className="drone-actions-container">
      <div className="action-parameter-bar">
        <div>
          <h3>Action Overrides</h3>
          <p>Direct flight, service, and recovery commands.</p>
        </div>
        <div className="action-parameter-bar__meta">
          <span>{targetCount} targeted drone{targetCount === 1 ? '' : 's'}</span>
          <span>{actionSchedule.summary}</span>
        </div>
      </div>

      <div className="action-configuration-grid">
        <div className="takeoff-section">
          <label htmlFor="takeoff-altitude">Takeoff Altitude (m)</label>
          <input
            type="number"
            id="takeoff-altitude"
            value={takeoffAltitude}
            onChange={(e) => onTakeoffAltitudeChange(Number(e.target.value))}
            min="1"
            max="1000"
            className="altitude-input"
          />
          <span className="takeoff-section__hint">Used by Take Off only.</span>
        </div>

        <details
          className="action-schedule"
          open={scheduleOpen}
          onToggle={(event) => setScheduleOpen(event.currentTarget.open)}
        >
          <summary>
            <FaClock aria-hidden="true" />
            <span>Execution Timing</span>
            <small>{actionSchedule.summary}</small>
          </summary>
          <div className="action-schedule__body">
            <div className="action-schedule__modes">
              <button
                type="button"
                className={scheduleMode === COMMAND_SCHEDULE_MODES.NOW ? 'active' : ''}
                onClick={() => setScheduleMode(COMMAND_SCHEDULE_MODES.NOW)}
              >
                Now
              </button>
              <button
                type="button"
                className={scheduleMode === COMMAND_SCHEDULE_MODES.DELAY ? 'active' : ''}
                onClick={() => setScheduleMode(COMMAND_SCHEDULE_MODES.DELAY)}
              >
                Delay
              </button>
              <button
                type="button"
                className={scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE ? 'active' : ''}
                onClick={() => setScheduleMode(COMMAND_SCHEDULE_MODES.ABSOLUTE)}
              >
                Exact UTC
              </button>
            </div>

            {scheduleMode === COMMAND_SCHEDULE_MODES.DELAY && (
              <div className="action-schedule__inputs">
                <div className="action-schedule__presets">
                  {COMMAND_DELAY_PRESETS.map((preset) => (
                    <button
                      key={preset}
                      type="button"
                      className={Number(timeDelay) === preset ? 'active' : ''}
                      onClick={() => setTimeDelay(preset)}
                    >
                      +{preset}s
                    </button>
                  ))}
                </div>
                <label>
                  Delay (s)
                  <input
                    type="number"
                    min="0"
                    step="1"
                    value={timeDelay}
                    onChange={(event) => setTimeDelay(Number(event.target.value))}
                  />
                </label>
              </div>
            )}

            {scheduleMode === COMMAND_SCHEDULE_MODES.ABSOLUTE && (
              <div className="action-schedule__inputs">
                <label>
                  Trigger Time
                  <input
                    type="datetime-local"
                    value={selectedDateTime}
                    onChange={(event) => setSelectedDateTime(event.target.value)}
                  />
                </label>
              </div>
            )}

            <p className="action-schedule__note">
              Flight and test actions may be queued. Maintenance and emergency actions still dispatch immediately.
              {clockOffsetLabel ? ` ${clockOffsetLabel}.` : ' Scheduler uses the GCS clock.'}
            </p>
          </div>
        </details>
      </div>

      {ACTION_SECTIONS.map((section) => (
        <div
          key={section.key}
          className={`action-group action-group--${section.key} ${section.key === 'danger' ? 'action-group--danger' : ''}`}
        >
          <div className="action-group__header">
            <h2>{section.title}</h2>
            <p>{section.description}</p>
          </div>
          <div className="action-buttons">
            {section.actions.map((actionKey) => renderActionButton(actionKey, section.key))}
          </div>
        </div>
      ))}
    </div>
  );
};

DroneActions.propTypes = {
  actionTypes: PropTypes.object.isRequired,
  onSendCommand: PropTypes.func.isRequired,
  onRequestPrecisionMove: PropTypes.func.isRequired,
  targetCount: PropTypes.number,
  takeoffAltitude: PropTypes.number,
  onTakeoffAltitudeChange: PropTypes.func,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
  runtimeMode: PropTypes.oneOf(['real', 'sitl', 'unknown']),
};

export default DroneActions;
