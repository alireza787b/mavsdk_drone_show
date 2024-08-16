import React from 'react';

const MissionDetails = ({
  missionType,
  icon,
  label,
  description,
  useSlider,
  timeDelay,
  selectedTime,
  onTimeDelayChange,
  onTimePickerChange,
  onSliderToggle,
  onSend,
  onBack,
}) => (
  <div className="mission-details">
    <div className="selected-mission-card">
      <div className="mission-icon">{icon}</div>
      <div className="mission-name">{label}</div>
      <div className="mission-description">{description}</div>
    </div>

    <div className="time-selection">
      <label>
        <input
          type="radio"
          checked={useSlider}
          onChange={() => onSliderToggle(true)}
        />
        Set delay in seconds
      </label>
      <label>
        <input
          type="radio"
          checked={!useSlider}
          onChange={() => onSliderToggle(false)}
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
          onChange={(e) => onTimeDelayChange(e.target.value)}
        />
      </div>
    ) : (
      <div className="time-picker">
        <label htmlFor="time-picker">Select Time:</label>
        <input
          type="time"
          id="time-picker"
          value={selectedTime}
          onChange={(e) => onTimePickerChange(e.target.value)}
          step="1"
        />
      </div>
    )}

    <button onClick={onSend} className="mission-button">
      Send Command
    </button>
    <button onClick={onBack} className="back-button">
      Back
    </button>
  </div>
);

export default MissionDetails;
