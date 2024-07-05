import React, { useState } from 'react';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);  // Default altitude for takeoff

  const handleAction = (actionType) => {
    const commandData = {
      missionType: actionTypes[actionType],
      takeoff_altitude: actionType === 'TAKE_OFF' ? altitude : undefined,
      triggerTime: '0'  // Immediate action for these commands
    };
    onSendCommand(commandData);
  };

  return (
    <div className="actions-content">
      <div className="takeoff-section">
        <label>
          Initial Takeoff Altitude (m):&nbsp;
          <input type="number" value={altitude} onChange={(e) => setAltitude(e.target.value)} className="altitude-input" />
        </label>
        <button className="action-button" onClick={() => handleAction('TAKE_OFF')}>Takeoff</button>
      </div>
      <button className="action-button" onClick={() => handleAction('LAND')}>Land All</button>
      <button className="action-button" onClick={() => handleAction('HOLD')}>Hold Position</button>
    </div>
  );
};

export default DroneActions;
