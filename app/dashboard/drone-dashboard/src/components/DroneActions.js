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
  FaBatteryFull,
  FaSyncAlt,
  FaPowerOff,
  FaCodeBranch,
  FaHome,
  FaRocket,
  FaSkull,
  FaToolbox,
  FaWrench,
  FaClock,
} from 'react-icons/fa';
import { DRONE_ACTION_NAMES } from '../constants/droneConstants';
import {
  buildCommandSchedule,
  COMMAND_DELAY_PRESETS,
  COMMAND_SCHEDULE_MODES,
  formatDateTimeLocalInput,
} from '../utilities/commandScheduling';
import '../styles/DroneActions.css';

const ACTION_SECTIONS = [
  {
    key: 'routine',
    title: 'Routine Flight Control',
    description: 'Normal airborne overrides and rehearsal tools.',
    actions: ['TAKE_OFF', 'HOVER_TEST', 'HOLD', 'LAND', 'RETURN_RTL'],
  },
  {
    key: 'test',
    title: 'Bench & Visual Tests',
    description: 'Non-mission checks before a live operation.',
    actions: ['TEST', 'TEST_LED'],
  },
  {
    key: 'maintenance',
    title: 'System Maintenance',
    description: 'Repo, parameters, and reboot operations for recovery or servicing.',
    actions: ['UPDATE_CODE', 'INIT_SYSID', 'APPLY_COMMON_PARAMS', 'REBOOT_FC', 'REBOOT_SYS'],
  },
  {
    key: 'danger',
    title: 'Danger Zone',
    description: 'Only use if the aircraft must be forced out of normal behavior immediately.',
    actions: ['DISARM', 'KILL_TERMINATE'],
  },
];

const ACTION_ICONS = {
  TAKE_OFF: FaPlaneDeparture,
  LAND: FaPlaneArrival,
  HOLD: FaHandHolding,
  RETURN_RTL: FaHome,
  DISARM: FaBatteryFull,
  KILL_TERMINATE: FaSkull,
  TEST: FaVial,
  TEST_LED: FaLightbulb,
  HOVER_TEST: FaRocket,
  REBOOT_FC: FaPowerOff,
  REBOOT_SYS: FaSyncAlt,
  UPDATE_CODE: FaCodeBranch,
  INIT_SYSID: FaToolbox,
  APPLY_COMMON_PARAMS: FaWrench,
};

const ACTION_DESCRIPTIONS = {
  TAKE_OFF: 'Climb every target to the configured takeoff altitude.',
  LAND: 'Land the targeted drones immediately.',
  HOLD: 'Freeze current motion and hold position.',
  RETURN_RTL: 'Return the targeted drones to launch.',
  DISARM: 'Disarm motors. Use only when safe to do so.',
  KILL_TERMINATE: 'Emergency motor stop. Use only as a last resort.',
  TEST: 'Run the generic test routine.',
  TEST_LED: 'Run the light-show test pattern.',
  HOVER_TEST: 'Quick lift, hover, and land rehearsal.',
  REBOOT_FC: 'Restart PX4 or the flight-controller side.',
  REBOOT_SYS: 'Restart the companion computer container/system.',
  UPDATE_CODE: 'Pull the configured repo/branch and restart services if needed.',
  INIT_SYSID: 'Reapply system ID / identity setup.',
  APPLY_COMMON_PARAMS: 'Apply the common PX4 parameter set and reboot.',
};

const SCHEDULABLE_ACTIONS = new Set([
  'TAKE_OFF',
  'HOVER_TEST',
  'HOLD',
  'LAND',
  'RETURN_RTL',
  'TEST',
  'TEST_LED',
]);

const DroneActions = ({
  actionTypes,
  onSendCommand,
  targetCount = 0,
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
}) => {
  const [altitude, setAltitude] = useState(10);
  const [scheduleMode, setScheduleMode] = useState(COMMAND_SCHEDULE_MODES.NOW);
  const [timeDelay, setTimeDelay] = useState(30);
  const [selectedDateTime, setSelectedDateTime] = useState(() => formatDateTimeLocalInput(referenceNowMs + 60_000));

  const actionSchedule = useMemo(() => buildCommandSchedule({
    scheduleMode,
    timeDelay,
    selectedDateTime,
    referenceNowMs,
  }), [referenceNowMs, scheduleMode, selectedDateTime, timeDelay]);

  const handleActionClick = (actionKey, extraData = {}) => {
    const supportsScheduling = SCHEDULABLE_ACTIONS.has(actionKey);
    if (supportsScheduling && actionSchedule.error) {
      toast.error(actionSchedule.error);
      return;
    }

    const actionTypeValue = actionTypes[actionKey];
    const commandData = {
      missionType: String(actionTypeValue),
      triggerTime: String(supportsScheduling ? (actionSchedule.triggerTimeSec ?? 0) : 0),
      ...extraData,
    };

    if (actionKey === 'TAKE_OFF') {
      commandData.takeoff_altitude = altitude;
    }

    commandData.uiMeta = {
      operatorLabel: DRONE_ACTION_NAMES[actionTypeValue],
      triggerSummary: supportsScheduling ? actionSchedule.summary : 'Immediate on acceptance',
      confirmationMessage: `${DRONE_ACTION_NAMES[actionTypeValue]} → ${targetCount} targeted drone${targetCount === 1 ? '' : 's'}. Confirm dispatch.`,
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
            value: `${altitude} m`,
          }]
          : []),
      ],
    };

    onSendCommand(commandData);
  };

  const renderActionButton = (actionKey) => {
    const Icon = ACTION_ICONS[actionKey];
    const actionTypeValue = actionTypes[actionKey];
    const label = DRONE_ACTION_NAMES[actionTypeValue];
    const isDanger = actionKey === 'KILL_TERMINATE' || actionKey === 'DISARM';

    return (
      <button
        key={actionKey}
        className={`action-button ${actionKey.toLowerCase().replace(/_/g, '-').replace('return-rtl', 'rtl').replace('kill-terminate', 'kill')} ${isDanger ? 'danger' : ''}`}
        onClick={() => handleActionClick(actionKey, actionKey === 'APPLY_COMMON_PARAMS' ? { reboot_after: true } : {})}
        title={ACTION_DESCRIPTIONS[actionKey]}
        aria-label={`${label}. ${ACTION_DESCRIPTIONS[actionKey]}`}
      >
        <span className="action-button__icon"><Icon className="action-icon" /></span>
        <span className="action-button__title">{label}</span>
      </button>
    );
  };

  return (
    <div className="drone-actions-container">
      <div className="action-parameter-bar">
        <div>
          <h3>Action Overrides</h3>
          <p>Direct fleet interventions outside the mission scheduler.</p>
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
            value={altitude}
            onChange={(e) => setAltitude(Number(e.target.value))}
            min="1"
            max="1000"
            className="altitude-input"
          />
          <span className="takeoff-section__hint">Used by Take Off only.</span>
        </div>

        <details className="action-schedule">
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
              Flight and test actions may be scheduled. Maintenance and danger actions still dispatch immediately.
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
          </div>
          <div className="action-buttons">
            {section.actions.map((actionKey) => renderActionButton(actionKey))}
          </div>
        </div>
      ))}
    </div>
  );
};

DroneActions.propTypes = {
  actionTypes: PropTypes.object.isRequired,
  onSendCommand: PropTypes.func.isRequired,
  targetCount: PropTypes.number,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
};

export default DroneActions;
