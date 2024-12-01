// src/components/DroneActions.js
import React, { useState } from 'react';
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
} from 'react-icons/fa';
import '../styles/DroneActions.css';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);

  const handleActionClick = (actionType) => {
    const commandData = {
      missionType: actionTypes[actionType],
      triggerTime: '0', // Immediate action
    };

    // Additional fields for specific actions
    if (actionType === 'TAKE_OFF') {
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
              Takeoff
            </button>
          </div>
          <button
            className="action-button land-button"
            onClick={() => handleActionClick('LAND')}
          >
            <FaPlaneArrival className="action-icon" />
            Land All
          </button>
          <button
            className="action-button hold-button"
            onClick={() => handleActionClick('HOLD')}
          >
            <FaHandHolding className="action-icon" />
            Hold Position
          </button>
          <button
            className="action-button rtl-button"
            onClick={() => handleActionClick('RETURN_RTL')}
          >
            <FaHome className="action-icon" />
            Return to Launch
          </button>
          <button
            className="action-button disarm-button"
            onClick={() => handleActionClick('DISARM')}
          >
            <FaBatteryFull className="action-icon" />
            Disarm Drones
          </button>
          <button
            className="action-button kill-button"
            onClick={() => handleActionClick('KILL_TERMINATE')}
          >
            <FaSkull className="action-icon" />
            Emergency KILL!
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
            Test
          </button>
          <button
            className="action-button test-led-button"
            onClick={() => handleActionClick('TEST_LED')}
          >
            <FaLightbulb className="action-icon" />
            Test Light Show
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
            Reboot Flight Controls
          </button>
          <button
            className="action-button reboot-sys-button"
            onClick={() => handleActionClick('REBOOT_SYS')}
          >
            <FaSyncAlt className="action-icon" />
            Reboot Companion Computer
          </button>
          <button
            className="action-button update-code-button"
            onClick={() => handleActionClick('UPDATE_CODE')}
          >
            <FaCodeBranch className="action-icon" />
            Update Code
          </button>
        </div>
      </div>
    </div>
  );
};

export default DroneActions;
