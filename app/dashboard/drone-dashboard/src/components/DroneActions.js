// src/components/DroneActions.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
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
  FaWrench
} from 'react-icons/fa';
import { DRONE_ACTION_NAMES } from '../constants/droneConstants';
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

const DroneActions = ({ actionTypes, onSendCommand, targetCount = 0 }) => {
  // Altitude input for takeoff
  const [altitude, setAltitude] = useState(10);

  // Helper to build and send the commandData object
  const handleActionClick = (actionKey, extraData = {}) => {
    const actionTypeValue = actionTypes[actionKey];
    const commandData = {
      missionType: String(actionTypeValue),
      triggerTime: '0', // immediate
      ...extraData,
    };

    // If user clicks Takeoff, include altitude
    if (actionKey === 'TAKE_OFF') {
      commandData.takeoff_altitude = altitude;
    }

    commandData.uiMeta = {
      triggerSummary: 'Immediate on acceptance',
      details: [
        {
          label: 'Mode',
          value: 'Immediate override',
        },
        {
          label: 'Operator note',
          value: ACTION_DESCRIPTIONS[actionKey],
        },
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
      >
        <span className="action-button__icon"><Icon className="action-icon" /></span>
        <span className="action-button__content">
          <span className="action-button__title">{label}</span>
          <span className="action-button__description">{ACTION_DESCRIPTIONS[actionKey]}</span>
        </span>
      </button>
    );
  };

  return (
    <div className="drone-actions-container">
      <div className="action-parameter-bar">
        <div>
          <h3>Immediate Actions</h3>
          <p>These commands execute as soon as the targeted drones accept them. Use the mission tab for scheduled starts.</p>
        </div>
        <div className="action-parameter-bar__meta">
          <span>{targetCount} targeted drone{targetCount === 1 ? '' : 's'}</span>
        </div>
      </div>

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
        <span className="takeoff-section__hint">Used by the Take Off action only.</span>
      </div>

      {ACTION_SECTIONS.map((section) => (
        <div
          key={section.key}
          className={`action-group action-group--${section.key} ${section.key === 'danger' ? 'action-group--danger' : ''}`}
        >
          <div className="action-group__header">
            <div>
              <h2>{section.title}</h2>
              <p>{section.description}</p>
            </div>
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
};

export default DroneActions;
