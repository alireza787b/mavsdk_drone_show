import React, { useState } from 'react';
import { defaultTriggerTimeDelay } from '../constants/droneConstants';
import TimePicker from 'react-time-picker'; // You may need to install react-time-picker library
import '../styles/MissionTrigger.css'; // Import the CSS file

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);
  const [useSlider, setUseSlider] = useState(true);  // Toggle between slider and clock
  const [selectedTime, setSelectedTime] = useState(new Date());  // Used for clock-style input

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
  };

  const handleSend = () => {
    if (!selectedMission) {
      alert('Please select a mission type.');
      return;
    }

    let triggerTime;

    if (useSlider) {
      triggerTime = Math.floor(Date.now() / 1000) + parseInt(timeDelay);
    } else {
      // Get the selected time from the TimePicker and convert to UNIX timestamp
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
            className={`mission-card ${selectedMission === value ? 'selected' : ''}`}
            onClick={() => handleMissionSelect(value)}
          >
            <div className="mission-icon">
              {/* Add an icon or image relevant to the mission */}
              <img src={`/icons/${key.toLowerCase()}.png`} alt={key} />
            </div>
            <div className="mission-name">{key.replace(/_/g, ' ')}</div>
          </div>
        ))}
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
          <TimePicker
            onChange={setSelectedTime}
            value={selectedTime}
            disableClock={false}
            clearIcon={null}
          />
        </div>
      )}

      <button onClick={handleSend} className="mission-button">
        Send Command
      </button>
    </div>
  );
};

export default MissionTrigger;
