import React, { useState } from 'react';

const DroneActions = ({ actionTypes, onSendCommand }) => {
  const [altitude, setAltitude] = useState(10);

  // Function to handle actions with confirmation
  const handleAction = (actionType, confirmationMessage) => {
    console.log('handleAction called with actionType:', actionType);
    console.log('Confirmation message:', confirmationMessage);

    if (!window.confirm(confirmationMessage)) {
      return; // Do nothing if the user cancels the action
    }

    console.log('actionTypes:', actionTypes);
    console.log('actionTypes[actionType]:', actionTypes[actionType]);

    const commandData = {
      missionType: actionTypes[actionType],
      triggerTime: '0' // Immediate action for these commands
    };

    // Additional fields for specific actions
    if (actionType === 'TAKE_OFF') {
      commandData.takeoff_altitude = altitude;
    }

    console.log('Command data:', commandData);

    onSendCommand(commandData);
  };

  return (
    <div className="actions-content">
      <div className="takeoff-section">
        <label htmlFor="takeoff-altitude">Initial Takeoff Altitude (m):</label>
        <input type="number" id="takeoff-altitude" value={altitude} onChange={(e) => setAltitude(e.target.value)} />
        <button className="action-button" onClick={() => handleAction('TAKE_OFF', `Are you sure you want to send the Takeoff command to all drones? The drones will take off to an altitude of ${altitude}m.`)}>
          Takeoff
        </button>
      </div>
      <button className="action-button" onClick={() => handleAction('LAND', 'Land All: This will land all drones at their current positions. Are you sure you want to proceed?')}>
        Land All
      </button>
      <button className="action-button" onClick={() => handleAction('HOLD', 'Hold Position: This will make all drones hold their current positions. Are you sure you want to proceed?')}>
        Hold Position
      </button>
      <button className="action-button test-button" onClick={() => handleAction('TEST', 'Test Action: Will arm the drones, wait for 3 seconds, then disarm. Are you sure you want to proceed?')}>
        Test
      </button>
      <button className="action-button test-button" onClick={() => handleAction('TEST_LED', 'Test Action: Will run the LED controller test script on the ground. Are you sure you want to proceed?')}>
        Test Light Show
      </button>
      <button className="action-button" onClick={() => handleAction('DISARM', 'Disarm Drones: This will disarm all drones immediately. Are you sure you want to proceed?')}
              style={{ backgroundColor: 'red', color: 'white' }}>
        Disarm Drones
      </button>
      <button className="action-button" onClick={() => handleAction('REBOOT', 'Reboot Drones: This will reboot all drones. Are you sure you want to proceed?')}
              style={{ backgroundColor: 'orange', color: 'white' }}>
        Reboot Drones
      </button>
    </div>
  );
};

export default DroneActions;
