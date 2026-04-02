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
    actions: ['TAKE_OFF', 'HOVER_TEST', 'HOLD', 'LAND', 'RETURN_RTL'],
  },
  {
    key: 'test',
    title: 'Checks',
    description: 'Bench and rehearsal checks.',
    actions: ['TEST', 'TEST_LED'],
  },
  {
    key: 'maintenance',
    title: 'Service',
    description: 'Repo, identity, restart.',
    actions: ['UPDATE_CODE', 'INIT_SYSID', 'APPLY_COMMON_PARAMS', 'REBOOT_FC', 'REBOOT_SYS'],
  },
  {
    key: 'danger',
    title: 'Emergency',
    description: 'Last-resort stop.',
    actions: ['DISARM', 'KILL_TERMINATE'],
  },
];

const ACTION_SHORT_LABELS = {
  TAKE_OFF: 'Take Off',
  LAND: 'Land',
  HOLD: 'Hold',
  RETURN_RTL: 'RTL',
  DISARM: 'Disarm',
  KILL_TERMINATE: 'Kill',
  TEST: 'Bench Test',
  TEST_LED: 'LED Test',
  HOVER_TEST: 'Hover',
  REBOOT_FC: 'Reboot PX4',
  REBOOT_SYS: 'Reboot System',
  UPDATE_CODE: 'Update Repo',
  INIT_SYSID: 'Init SysID',
  APPLY_COMMON_PARAMS: 'Apply Params',
};

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
  TAKE_OFF: 'Climb to the configured takeoff altitude.',
  LAND: 'Land the selected aircraft now.',
  HOLD: 'Freeze current motion and hold position.',
  RETURN_RTL: 'Return the selected aircraft to launch.',
  DISARM: 'Disarm motors when the airframe is safe.',
  KILL_TERMINATE: 'Emergency motor stop.',
  TEST: 'Run the generic bench test.',
  TEST_LED: 'Run the light-pattern test.',
  HOVER_TEST: 'Lift, hover briefly, then land.',
  REBOOT_FC: 'Restart PX4 and flight-control services.',
  REBOOT_SYS: 'Restart the companion computer or container.',
  UPDATE_CODE: 'Pull the repo and refresh services.',
  INIT_SYSID: 'Reapply system identity.',
  APPLY_COMMON_PARAMS: 'Apply the common PX4 params.',
};

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
  const [scheduleOpen, setScheduleOpen] = useState(false);

  const actionSchedule = useMemo(() => buildCommandSchedule({
    scheduleMode,
    timeDelay,
    selectedDateTime,
    referenceNowMs,
  }), [referenceNowMs, scheduleMode, selectedDateTime, timeDelay]);

  const handleActionClick = (actionKey, extraData = {}) => {
    const supportsScheduling = isSchedulableActionKey(actionKey);
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
    const label = ACTION_SHORT_LABELS[actionKey] || DRONE_ACTION_NAMES[actionTypeValue];
    const fullLabel = DRONE_ACTION_NAMES[actionTypeValue];
    const isDanger = actionKey === 'KILL_TERMINATE' || actionKey === 'DISARM';
    const isCritical = actionKey === 'KILL_TERMINATE';

    return (
      <button
        key={actionKey}
        className={`action-button action-button--${sectionKey}${isDanger ? ' action-button--danger' : ''}${isCritical ? ' action-button--critical' : ''}`}
        onClick={() => handleActionClick(actionKey, actionKey === 'APPLY_COMMON_PARAMS' ? { reboot_after: true } : {})}
        title={`${fullLabel}. ${ACTION_DESCRIPTIONS[actionKey]}`}
        aria-label={`${fullLabel}. ${ACTION_DESCRIPTIONS[actionKey]}`}
      >
        <span className="action-button__icon"><Icon className="action-icon" /></span>
        <span className="action-button__content">
          <span className="action-button__title">{label}</span>
          <small className="action-button__summary">{ACTION_DESCRIPTIONS[actionKey]}</small>
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
            value={altitude}
            onChange={(e) => setAltitude(Number(e.target.value))}
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
  targetCount: PropTypes.number,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
};

export default DroneActions;
