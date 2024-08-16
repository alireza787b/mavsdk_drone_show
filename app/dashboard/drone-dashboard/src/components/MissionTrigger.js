import React, { useState, useEffect } from 'react';
import '../style/MissionTrigger.css'; // Import the CSS file

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(10);  // Default time delay in seconds
  const [useSlider, setUseSlider] = useState(true);  // Toggle between slider and clock
  const [selectedTime, setSelectedTime] = useState('');  // For time picker input

  useEffect(() => {
    // Set default to current time + 30 seconds when component mounts
    const now = new Date();
    now.setSeconds(now.getSeconds() + 30);
    setSelectedTime(now.toISOString().slice(11, 19)); // Format as HH:MM:SS
  }, []);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
    setTimeDelay(10);  // Reset time delay to default when a new mission is selected
  };

  const handleSend = () => {
    if (!selectedMission || selectedMission === 'NONE') {
      alert('Please select a mission type.');
      return;
    }

    let triggerTime;

    if (useSlider) {
      triggerTime = Math.floor(Date.now() / 1000) + parseInt(timeDelay);
    } else {
      // Convert selectedTime to UNIX timestamp
      const now = new Date();
      const [hours, minutes, seconds] = selectedTime.split(':').map(Number);
      const selectedDateTime = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hours, minutes, seconds);
      triggerTime = Math.floor(selectedDateTime.getTime() / 1000);

      if (selectedDateTime < now) {
        alert('The selected time has already passed. Please select a future time.');
        return;
      }
    }

    const missionName = missionTypes[selectedMission];
    const confirmationMessage = `Are you sure you want to send the "${missionName}" command to all drones?\nTrigger time: ${new Date(triggerTime * 1000).toLocaleString()}`;

    if (!window.confirm(confirmationMessage)) {
      return;
    }

    const commandData = {
      missionType: selectedMission,
      triggerTime,
    };
    onSendCommand(commandData);
  };

  const handleBack = () => {
    setSelectedMission(''); // Reset mission selection
  };

  return (
    <div className="mission-trigger-content">
      {!selectedMission && (
        <div className="mission-cards">
          {Object.entries(missionTypes).map(([key, value]) => (
            <div
              key={value}
              className="mission-card"
              onClick={() => handleMissionSelect(value)}
            >
              <div className="mission-icon">
                {key === 'DRONE_SHOW_FROM_CSV' && '🛸'}
                {key === 'CUSTOM_CSV_DRONE_SHOW' && '🎯'}
                {key === 'SMART_SWARM' && '🐝'}
                {key === 'NONE' && '❌'}
              </div>
              <div className="mission-name">{key.replace(/_/g, ' ')}</div>
            </div>
          ))}
        </div>
      )}

      {selectedMission && (
        <div className="mission-details">
          <div className="selected-mission-card">
            <div className="mission-icon">
              {selectedMission === 'DRONE_SHOW_FROM_CSV' && '🛸'}
              {selectedMission === 'CUSTOM_CSV_DRONE_SHOW' && '🎯'}
              {selectedMission === 'SMART_SWARM' && '🐝'}
              {selectedMission === 'NONE' && '❌'}
            </div>
            <div className="mission-name">
              {Object.keys(missionTypes).find((key) => missionTypes[key] === selectedMission).replace(/_/g, ' ')}
            </div>
          </div>

          <div className="time-selection">
            <label>
              <input
                type="radio"
                checked={useSlider}
                onChange={() => setUseSlider(true)}
              />
              Set delay in seconds
            </label>
            <label>
              <input
                type="radio"
                checked={!useSlider}
                onChange={() => setUseSlider(false)}
              />
              Set exact time
            </label>
          </div>

          {useSlider ? (
            <div className="time-delay-slider">
              <label htmlFor="time-delay">Time Delay (seconds): {timeDelay}</label>
              <input
                type="range"
                id="time-delay"
                min="0"
                max="60"
                value={timeDelay}
                onChange={(e) => setTimeDelay(e.target.value)}
              />
            </div>
          ) : (
            <div className="time-picker">
              <label htmlFor="time-picker">Select Time:</label>
              <input
                type="time"
                id="time-picker"
                value={selectedTime}
                onChange={(e) => setSelectedTime(e.target.value)}
                step="1"
              />
            </div>
          )}

          <button onClick={handleSend} className="mission-button">
            Send Command
          </button>
          <button onClick={handleBack} className="back-button">
            Back
          </button>
        </div>
      )}
    </div>
  );
};

export default MissionTrigger;
