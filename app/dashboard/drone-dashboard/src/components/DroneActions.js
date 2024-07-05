import React, { useState } from 'react';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);

  const handleAction = (actionType, confirmMessage) => {
    if (confirmMessage && !window.confirm(confirmMessage)) {
      return; // If there's a confirmation message and user cancels, do nothing
    }

    const commandData = {
      missionType: actionTypes[actionType],
      takeoff_altitude: actionType === 'TAKE_OFF' ? altitude : undefined,
      triggerTime: '0' // Immediate action for these commands
    };
    onSendCommand(commandData);
  };

  return (
    <div className="actions-content">
      <div className="test-section">
        <button className="action-button test-button" onClick={() => handleAction('TEST')}>Test</button>
      </div>
      <div className="takeoff-section">
        <label>
          Initial Takeoff Altitude (m):&nbsp;
          <input type="number" value={altitude} onChange={(e) => setAltitude(e.target.value)} className="altitude-input" />
        </label>
        <button className="action-button" onClick={() => handleAction('TAKE_OFF')}>Takeoff</button>
      </div>
      <button className="action-button" onClick={() => handleAction('LAND')}>Land All</button>
      <button className="action-button" onClick={() => handleAction('HOLD')}>Hold Position</button>
      <button className="action-button" onClick={() => handleAction('DISARM', 'Are you sure you want to disarm all drones? This cannot be undone.')}
              style={{ backgroundColor: 'red', color: 'white' }}>Disarm Drones</button>
    </div>
  );
};

export default DroneActions;
