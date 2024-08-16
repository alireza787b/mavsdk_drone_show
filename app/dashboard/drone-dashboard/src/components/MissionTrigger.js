import React, { useState, useEffect } from 'react';
import { defaultTriggerTimeDelay } from '../constants/droneConstants';
import TimePicker from 'react-time-picker'; // You may need to install react-time-picker library
import '../styles/MissionTrigger.css'; // Import the CSS file

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);
  const [useSlider, setUseSlider] = useState(true);  // Toggle between slider and clock
  const [selectedTime, setSelectedTime] = useState(new Date());  // Used for clock-style input

  useEffect(() => {
    // Default to current time + 30 seconds when the time picker is first opened
    const now = new Date();
    now.setSeconds(now.getSeconds() + 30);
    setSelectedTime(now);
  }, []);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);

    // If 'NONE' is selected, send a cancel mission immediately
    if (missionType === 'NONE') {
      const commandData = {
        missionType,
        triggerTime: Math.floor(Date.now() / 1000),
      };
      onSendCommand(commandData);
      return;
    }
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
      const now = new Date();
      const selectedDateTime = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
        selectedTime.getHours(),
        selectedTime.getMinutes(),
        selectedTime.getSeconds()
      );
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

  return (
    <div className="mission-trigger-content">
      <div className="mission-cards">
        {Object.entries(missionTypes).map(([key, value]) => (
          <div
            key={value}
            className={`mission-card ${selectedMission === value ? 'selected' : ''} ${key === 'NONE' ? 'cancel-mission' : ''}`}
            onClick={() => handleMissionSelect(value)}
          >
            <div className="mission-icon">
              {/* Using simple text-based icons for now */}
              {key === 'DRONE_SHOW_FROM_CSV' && '🛸'}
              {key === 'CUSTOM_CSV_DRONE_SHOW' && '🎯'}
              {key === 'SMART_SWARM' && '🐝'}
              {key === 'NONE' && '❌'}
            </div>
            <div className="mission-name">{key.replace(/_/g, ' ')}</div>
          </div>
        ))}
      </div>

      {selectedMission !== 'NONE' && (
        <>
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
              <TimePicker
                onChange={setSelectedTime}
                value={selectedTime}
                disableClock={true}  // Using 24-hour format
                format="HH:mm:ss"  // 24-hour format
                clearIcon={null}
                hourPlaceholder="HH"
                minutePlaceholder="MM"
                secondPlaceholder="SS"
              />
            </div>
          )}

          <button onClick={handleSend} className="mission-button">
            Send Command
          </button>
        </>
      )}
    </div>
  );
};

export default MissionTrigger;
