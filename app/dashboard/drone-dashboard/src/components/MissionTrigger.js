//app/dashboard/drone-dashboard/src/components/MissionTrigger.js
import React, { useState } from 'react';
import { defaultTriggerTimeDelay } from '../constants/droneConstants';

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [missionType, setMissionType] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);  // Assuming default delay is 10 seconds

  const handleSend = () => {
    if (missionType === '') {
      alert('Please select a mission type.');
      return;
    }
    if (timeDelay <= 0) {
      alert('Please enter a valid time delay.');
      return;
    }

    // Prepare the confirmation message
    const missionName = missionTypes[missionType];
    const triggerTime = new Date(Date.now() + timeDelay * 1000).toLocaleString();
    const confirmationMessage = `Are you sure you want to send the "${missionName}" command to all drones?
      Trigger time: ${triggerTime}`;

    // Show confirmation dialog
    if (!window.confirm(confirmationMessage)) {
      return; // Do nothing if the user cancels
    }

    const commandData = {
      missionType,
      triggerTime: Math.floor(Date.now() / 1000) + parseInt(timeDelay),
    };
    onSendCommand(commandData);
  };

  return (
    <div className="mission-trigger-content">
      <div className="mission-selection">
        <label htmlFor="mission-type">Mission Type:</label>
        <select id="mission-type" value={missionType} onChange={(e) => setMissionType(e.target.value)}>
          <option value="">Select</option>
          {Object.entries(missionTypes).map(([key, value]) => (
            <option key={value} value={value}>{key.replace(/_/g, ' ')}</option>
          ))}
        </select>
      </div>
      <div className="time-delay">
        <label htmlFor="time-delay">Time Delay (seconds):</label>
        <input type="number" id="time-delay" value={timeDelay} onChange={(e) => setTimeDelay(e.target.value)} />
      </div>
      <button onClick={handleSend} className="mission-button">
        Send Command
      </button>
    </div>
  );
};

export default MissionTrigger;
