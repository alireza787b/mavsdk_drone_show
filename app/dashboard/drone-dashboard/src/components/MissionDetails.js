import React from 'react';
import '../styles/MissionDetails.css';
import { DRONE_MISSION_IMAGES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import MissionReadinessCard from './MissionReadinessCard';

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
}) => {
  const missionImageSrc = DRONE_MISSION_IMAGES[missionType];

  return (
    <div className="mission-details">
      <div className="selected-mission-card">
        <div className="mission-icon">{icon}</div>
        <div className="mission-name">{label}</div>
        <div className="mission-description">{description}</div>
      </div>

      {/* Display mission-specific image */}
      {missionImageSrc && (
        <div className="mission-preview">
          <h3>Mission Preview:</h3>
          <img src={missionImageSrc} alt={label} className="mission-image" />
        </div>
      )}

      {/* Enhanced Mission Readiness for Swarm Trajectory Mode */}
      {missionType === DRONE_MISSION_TYPES.SWARM_TRAJECTORY && (
        <MissionReadinessCard refreshTrigger={0} />
      )}

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
};

export default MissionDetails;
