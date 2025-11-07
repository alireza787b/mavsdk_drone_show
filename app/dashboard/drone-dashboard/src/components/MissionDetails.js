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
  autoGlobalOrigin,
  onAutoGlobalOriginChange,
  useGlobalSetpoints,
  onUseGlobalSetpointsChange,
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

      {/* Mode Selection: Local vs Global */}
      <div className="mode-selection-section">
        <h3 className="mode-selection-title">Control Mode</h3>
        <div className="mode-toggle-container">
          <label className={`mode-option ${!useGlobalSetpoints ? 'active' : ''}`}>
            <input
              type="radio"
              name="controlMode"
              checked={!useGlobalSetpoints}
              onChange={() => onUseGlobalSetpointsChange(false)}
              className="mode-radio"
            />
            <div className="mode-content">
              <span className="mode-icon">🧭</span>
              <span className="mode-label">LOCAL Mode</span>
              <span className="mode-description">NED feedforward, no GPS required</span>
            </div>
          </label>
          <label className={`mode-option ${useGlobalSetpoints ? 'active' : ''}`}>
            <input
              type="radio"
              name="controlMode"
              checked={useGlobalSetpoints}
              onChange={() => onUseGlobalSetpointsChange(true)}
              className="mode-radio"
            />
            <div className="mode-content">
              <span className="mode-icon">🌍</span>
              <span className="mode-label">GLOBAL Mode</span>
              <span className="mode-description">GPS-based positioning</span>
            </div>
          </label>
        </div>
      </div>

      {/* Phase 2: Auto Global Origin Checkbox (only for DRONE_SHOW_FROM_CSV + GLOBAL mode) */}
      {missionType === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV && useGlobalSetpoints && (
        <div className="phase2-origin-section">
          <div className="origin-checkbox-container">
            <label className="origin-checkbox-label">
              <input
                type="checkbox"
                checked={autoGlobalOrigin}
                onChange={(e) => onAutoGlobalOriginChange(e.target.checked)}
                className="origin-checkbox"
              />
              <span className="checkbox-text">
                🌍 Auto Global Origin Correction (Phase 2)
              </span>
            </label>
          </div>

          {autoGlobalOrigin && (
            <div className="origin-warning">
              <div className="warning-icon">⚠️</div>
              <div className="warning-content">
                <strong>Important Requirements:</strong>
                <ul>
                  <li>✓ Ensure the <strong>origin is set</strong> in the GCS dashboard</li>
                  <li>✓ Drones must have <strong>network connectivity</strong> to fetch origin</li>
                  <li>✓ Place drones <strong>approximately</strong> (±10m tolerance OK)</li>
                  <li>✓ System will <strong>auto-correct</strong> positions after initial climb</li>
                  <li>⚠️ Flight will abort if drone >20m from expected position</li>
                </ul>
              </div>
            </div>
          )}
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
