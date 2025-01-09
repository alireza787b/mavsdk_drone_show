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
  FaSkull,
  FaToolbox,
  FaWrench
} from 'react-icons/fa';
import { DRONE_ACTION_NAMES } from '../constants/droneConstants';
import '../styles/DroneActions.css';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);
  const [rebootAfter, setRebootAfter] = useState(false);

  // Helper to build the commandData
  const handleActionClick = (actionKey, extraData = {}) => {
    const actionTypeValue = actionTypes[actionKey];
    const commandData = {
      missionType: actionTypeValue,
      triggerTime: '0', // immediate
      ...extraData
    };

    if (actionKey === 'TAKE_OFF') {
      commandData.takeoff_altitude = altitude;
    }

    onSendCommand(commandData);
  };

  return (
    <div className="drone-actions-container">
      {/* Flight Control Actions */}
      <div className="action-group">
        <h2>Flight Control Actions</h2>
        <div className="action-buttons">
          {/* Takeoff Section */}
          <div className="takeoff-section">
            <label htmlFor="takeoff-altitude">Takeoff Altitude (m):</label>
            <input
              type="number"
              id="takeoff-altitude"
              value={altitude}
              onChange={(e) => setAltitude(Number(e.target.value))}
              min="1"
              max="1000"
              className="altitude-input"
            />
            <button
              className="action-button takeoff-button"
              onClick={() => handleActionClick('TAKE_OFF')}
            >
              <FaPlaneDeparture className="action-icon" />
              {DRONE_ACTION_NAMES[actionTypes.TAKE_OFF]}
            </button>
          </div>

          <button
            className="action-button land-button"
            onClick={() => handleActionClick('LAND')}
          >
            <FaPlaneArrival className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.LAND]}
          </button>

          <button
            className="action-button hold-button"
            onClick={() => handleActionClick('HOLD')}
          >
            <FaHandHolding className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.HOLD]}
          </button>

          <button
            className="action-button rtl-button"
            onClick={() => handleActionClick('RETURN_RTL')}
          >
            <FaHome className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.RETURN_RTL]}
          </button>

          <button
            className="action-button disarm-button"
            onClick={() => handleActionClick('DISARM')}
          >
            <FaBatteryFull className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.DISARM] || 'Disarm'}
          </button>

          <button
            className="action-button kill-button"
            onClick={() => handleActionClick('KILL_TERMINATE')}
          >
            <FaSkull className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.KILL_TERMINATE]}
          </button>
        </div>
      </div>

      {/* Test Actions */}
      <div className="action-group">
        <h2>Test Actions</h2>
        <div className="action-buttons">
          <button
            className="action-button test-button"
            onClick={() => handleActionClick('TEST')}
          >
            <FaVial className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.TEST]}
          </button>
          <button
            className="action-button test-led-button"
            onClick={() => handleActionClick('TEST_LED')}
          >
            <FaLightbulb className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.TEST_LED]}
          </button>
        </div>
      </div>

      {/* System Actions */}
      <div className="action-group">
        <h2>System Actions</h2>
        <div className="action-buttons">
          <button
            className="action-button reboot-fc-button"
            onClick={() => handleActionClick('REBOOT_FC')}
          >
            <FaPowerOff className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.REBOOT_FC]}
          </button>

          <button
            className="action-button reboot-sys-button"
            onClick={() => handleActionClick('REBOOT_SYS')}
          >
            <FaSyncAlt className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.REBOOT_SYS]}
          </button>

          <button
            className="action-button update-code-button"
            onClick={() => handleActionClick('UPDATE_CODE')}
          >
            <FaCodeBranch className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.UPDATE_CODE]}
          </button>
        </div>
      </div>

      {/* NEW: Setup / Maintenance Actions */}
      <div className="action-group">
        <h2>Setup / Maintenance</h2>
        <div className="action-buttons">
          {/* Init SysID */}
          <button
            className="action-button"
            style={{ backgroundColor: '#6f42c1' }}
            onClick={() => handleActionClick('INIT_SYSID')}
          >
            <FaToolbox className="action-icon" />
            {DRONE_ACTION_NAMES[actionTypes.INIT_SYSID]}
          </button>

          {/* Apply Common Params */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'start' }}>
            <button
              className="action-button"
              style={{ backgroundColor: '#795548' }}
              onClick={() =>
                handleActionClick('APPLY_COMMON_PARAMS', { reboot_after: rebootAfter })
              }
            >
              <FaWrench className="action-icon" />
              {DRONE_ACTION_NAMES[actionTypes.APPLY_COMMON_PARAMS]}
            </button>

            <label style={{ marginTop: '8px', fontWeight: 'bold' }}>
              <input
                type="checkbox"
                style={{ marginRight: '5px' }}
                checked={rebootAfter}
                onChange={(e) => setRebootAfter(e.target.checked)}
              />
              Reboot after apply?
            </label>
          </div>
        </div>
      </div>
    </div>
  );
};

DroneActions.propTypes = {
  actionTypes: PropTypes.object.isRequired,
  onSendCommand: PropTypes.func.isRequired,
};

export default DroneActions;
