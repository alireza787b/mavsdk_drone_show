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
        <label className="mission-label">
          Mission Type:&nbsp;
          <select value={missionType} onChange={(e) => setMissionType(e.target.value)} className="mission-dropdown">
            <option value="">Select</option>
            {Object.entries(missionTypes).map(([key, value]) => (
              <option key={value} value={value}>{key.replace(/_/g, ' ')}</option>
            ))}
          </select>
        </label>
      </div>
      <div className="time-delay">
        <label className="delay-label">
          Time Delay (seconds):&nbsp;
          <input type="number" value={timeDelay} onChange={(e) => setTimeDelay(e.target.value)} className="delay-input" />
        </label>
      </div>
      <button onClick={handleSend} className="mission-button send-command">
        Send Command
      </button>
    </div>
  );
};

export default MissionTrigger;
