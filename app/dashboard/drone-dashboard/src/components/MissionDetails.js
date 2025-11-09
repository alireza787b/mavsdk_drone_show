import React from 'react';
import { Link } from 'react-router-dom';
import '../styles/MissionDetails.css';
import { DRONE_MISSION_IMAGES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import MissionReadinessCard from './MissionReadinessCard';
import useFetch from '../hooks/useFetch';

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
  
  // Check origin status for auto global origin correction mode
  const { data: originData } = useFetch('/get-origin');
  const isOriginSet = originData && 
    originData.lat !== undefined && 
    originData.lon !== undefined && 
    originData.lat !== null && 
    originData.lon !== null &&
    originData.lat !== '' && 
    originData.lon !== '';
  
  // Fetch deviation data when auto correction is enabled and origin is set
  const shouldFetchDeviations = isOriginSet && autoGlobalOrigin && useGlobalSetpoints;
  const { data: deviationData } = useFetch('/get-position-deviations', shouldFetchDeviations ? 5000 : null);
  
  // Only show hints for DRONE_SHOW_FROM_CSV mission type
  const showModeHints = missionType === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV;
  
  // Extract deviation summary
  const deviationSummary = deviationData?.summary || null;
  const deviations = deviationData?.deviations || {};
  
  // Find drones with worst deviation (with tolerance for floating point comparison)
  const getWorstDeviationDrones = () => {
    if (!deviationSummary || !deviationSummary.worst_deviation) return [];
    const worst = deviationSummary.worst_deviation;
    const tolerance = 0.01; // 1cm tolerance for floating point comparison
    return Object.entries(deviations)
      .filter(([_, dev]) => {
        const devValue = dev.deviation?.horizontal;
        return devValue !== undefined && devValue !== null && 
               Math.abs(devValue - worst) < tolerance;
      })
      .map(([hw_id, _]) => hw_id)
      .sort((a, b) => parseInt(a) - parseInt(b)); // Sort by hw_id numerically
  };
  
  const worstDeviationDrones = getWorstDeviationDrones();
  
  // Format origin coordinates
  const formatOrigin = () => {
    if (!isOriginSet) return null;
    const lat = parseFloat(originData.lat).toFixed(6);
    const lon = parseFloat(originData.lon).toFixed(6);
    return `${lat}°, ${lon}°`;
  };

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
      {showModeHints && (
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
      )}

      {/* Mode-specific hints and guidance */}
      {showModeHints && !useGlobalSetpoints && (
        <div className="mode-guidance-section">
          <div className="guidance-header">
            <span className="guidance-icon">ℹ️</span>
            <strong>LOCAL Mode Guidelines</strong>
          </div>
          <div className="guidance-content">
            <ul>
              <li>Uses <strong>local NED coordinates</strong> (North-East-Down) relative to launch position</li>
              <li>Works with both <strong>GPS and non-GPS</strong> setups</li>
              <li>Operator must place drones <strong>exactly</strong> on their launch positions manually</li>
              <li>For <strong>non-GPS operation</strong>: Configure PX4 failsafe and local estimator, disable "wait for GPS fix" parameter</li>
              <li>Position accuracy depends entirely on manual placement precision</li>
            </ul>
          </div>
        </div>
      )}

      {showModeHints && useGlobalSetpoints && !autoGlobalOrigin && (
        <div className="mode-guidance-section">
          <div className="guidance-header">
            <span className="guidance-icon">ℹ️</span>
            <strong>GLOBAL Mode Guidelines</strong>
          </div>
          <div className="guidance-content">
            <ul>
              <li>Uses <strong>global GPS coordinates</strong> with global position estimator</li>
              <li>Operator must place drones <strong>exactly</strong> based on Blender export and mission config plot</li>
              <li>Placement deviations will <strong>directly affect</strong> the drone show accuracy</li>
              <li>Ensure good GPS fix quality before launch</li>
              <li>Verify launch positions match the mission configuration visualization</li>
            </ul>
          </div>
        </div>
      )}

      {/* Auto Global Origin Correction (only for DRONE_SHOW_FROM_CSV + GLOBAL mode) */}
      {showModeHints && useGlobalSetpoints && (
        <div className="auto-origin-section">
          <div className="origin-checkbox-container">
            <label className="origin-checkbox-label">
              <input
                type="checkbox"
                checked={autoGlobalOrigin}
                onChange={(e) => onAutoGlobalOriginChange(e.target.checked)}
                className="origin-checkbox"
              />
              <span className="checkbox-text">
                🌍 Auto Global Launch Corrector
              </span>
            </label>
          </div>

          {autoGlobalOrigin && (
            <div className={`origin-warning ${!isOriginSet ? 'origin-missing' : ''}`}>
              <div className="warning-icon">{isOriginSet ? '✅' : '⚠️'}</div>
              <div className="warning-content">
                {!isOriginSet ? (
                  <>
                    <strong>Origin Not Set</strong>
                    <p>
                      Origin must be configured before using auto correction mode. 
                      <Link to="/mission-config" className="origin-link">
                        Set origin in Mission Config →
                      </Link>
                    </p>
                  </>
                ) : (
                  <>
                    <strong>Auto Correction Active</strong>
                    
                    {/* Origin confirmation */}
                    <div className="origin-confirmation">
                      <div className="origin-info-row">
                        <span className="origin-label">Origin:</span>
                        <span className="origin-coords">{formatOrigin()}</span>
                      </div>
                    </div>
                    
                    {/* Deviation summary */}
                    {deviationData && (
                      <div className="deviation-summary-compact">
                        {deviationSummary && deviationSummary.online > 0 ? (
                          <>
                            <div className="deviation-stat">
                              <span className="deviation-label">Avg Deviation:</span>
                              <span className="deviation-value">{deviationSummary.average_deviation?.toFixed(2) || '0.00'}m</span>
                            </div>
                            <div className="deviation-stat">
                              <span className="deviation-label">Worst:</span>
                              <span className="deviation-value">
                                {deviationSummary.worst_deviation?.toFixed(2) || '0.00'}m
                                {worstDeviationDrones.length > 0 && (
                                  <span className="deviation-drones"> (Drone{worstDeviationDrones.length > 1 ? 's' : ''} {worstDeviationDrones.join(', ')})</span>
                                )}
                              </span>
                            </div>
                            <div className="deviation-stat">
                              <span className="deviation-label">Online:</span>
                              <span className="deviation-value">{deviationSummary.online} drone{deviationSummary.online !== 1 ? 's' : ''}</span>
                            </div>
                            {deviationSummary.warnings > 0 && (
                              <div className="deviation-stat warning-stat">
                                <span className="deviation-label">⚠️ Warnings:</span>
                                <span className="deviation-value warning-value">{deviationSummary.warnings}</span>
                              </div>
                            )}
                            {deviationSummary.errors > 0 && (
                              <div className="deviation-stat error-stat">
                                <span className="deviation-label">❌ Errors:</span>
                                <span className="deviation-value error-value">{deviationSummary.errors}</span>
                              </div>
                            )}
                          </>
                        ) : (
                          <div className="deviation-stat">
                            <span className="deviation-label">Status:</span>
                            <span className="deviation-value">No drones online</span>
                          </div>
                        )}
                      </div>
                    )}
                    
                    <ul>
                      <li>Drones will <strong>automatically correct</strong> their positions after takeoff and initial climb</li>
                      <li>Approximate placement acceptable (±10m tolerance)</li>
                      <li>Requires <strong>good GPS fix</strong> for accurate correction</li>
                      <li>Ensure drones have <strong>network connectivity</strong> to fetch origin from GCS</li>
                      <li>⚠️ <strong>Safety:</strong> Place drones to avoid correction paths that cross or could cause collisions</li>
                      <li>⚠️ Flight will abort if drone is &gt;20m from expected position</li>
                    </ul>
                  </>
                )}
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
