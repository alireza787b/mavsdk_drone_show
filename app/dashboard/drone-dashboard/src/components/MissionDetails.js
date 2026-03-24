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
  const customShowHints = missionType === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW;
  const { data: showInfo, error: showInfoError, loading: showInfoLoading } = useFetch(
    showModeHints ? '/get-show-info' : null
  );
  const { data: customShowInfo, error: customShowError, loading: customShowLoading } = useFetch(
    customShowHints ? '/get-custom-show-info' : null
  );
  
  // Extract deviation summary
  const deviationSummary = deviationData?.summary || null;
  const deviations = deviationData?.deviations || {};
  
  // Thresholds for placement status (matches backend)
  const thresholdWarning = 3.0;  // acceptable_deviation
  const thresholdError = 7.5;    // threshold_warning * 2.5
  
  // Analyze warnings to categorize them
  const analyzeWarnings = () => {
    if (!deviationSummary || !deviationSummary.warnings) {
      return { placementWarnings: 0, gpsWarnings: 0, warningDetails: [] };
    }
    
    const placementWarnings = [];
    const gpsWarnings = [];
    const warningDetails = [];
    
    Object.entries(deviations).forEach(([hw_id, dev]) => {
      if (dev.status === 'warning' || dev.status === 'error') {
        const devValue = dev.deviation?.horizontal || 0;
        const message = dev.message || '';
        
        // Check if warning is due to GPS quality or placement
        const messageLower = message.toLowerCase();
        const isGpsWarning = messageLower.includes('gps') || 
                             messageLower.includes('poor') ||
                             messageLower.includes('quality') ||
                             messageLower.includes('satellite') ||
                             messageLower.includes('hdop');
        
        // If deviation is excellent (<= threshold) but status is warning, it's GPS related
        const isExcellentPlacement = devValue <= thresholdWarning;
        
        if (isGpsWarning || (isExcellentPlacement && dev.status === 'warning')) {
          gpsWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'gps',
            message: message || 'GPS quality issue',
            deviation: devValue
          });
        } else if (devValue > thresholdWarning) {
          // Placement warning - deviation exceeds threshold
          placementWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'placement',
            message: message || `Deviation ${devValue.toFixed(2)}m exceeds threshold`,
            deviation: devValue
          });
        } else {
          // Unknown warning type, but deviation is good - treat as GPS
          gpsWarnings.push({ hw_id, message, deviation: devValue });
          warningDetails.push({
            hw_id,
            type: 'gps',
            message: message || 'Non-placement issue detected',
            deviation: devValue
          });
        }
      }
    });
    
    return {
      placementWarnings: placementWarnings.length,
      gpsWarnings: gpsWarnings.length,
      warningDetails
    };
  };
  
  const warningAnalysis = analyzeWarnings();
  
  // Get placement status based on actual deviation
  const getPlacementStatus = () => {
    if (!deviationSummary || !deviationSummary.worst_deviation) return null;
    const worst = deviationSummary.worst_deviation;
    
    if (worst <= thresholdWarning) {
      return { status: 'excellent', color: '#4caf50', icon: '✅', text: 'Excellent' };
    } else if (worst <= thresholdError) {
      return { status: 'warning', color: '#ff9800', icon: '⚠️', text: 'Warning' };
    } else {
      return { status: 'error', color: '#f44336', icon: '❌', text: 'Error' };
    }
  };
  
  const placementStatus = getPlacementStatus();
  const showImported = Boolean(showInfo && showInfo.drone_count > 0);
  const customShowReady = Boolean(customShowInfo && customShowInfo.exists);
  const droneShowBlockers = [];
  const droneShowWarnings = [];
  const customShowBlockers = [];
  const customShowWarnings = [];

  if (showModeHints && showInfoLoading) {
    droneShowBlockers.push('Verifying imported Drone Show package...');
  }

  if (showModeHints && !showInfoLoading) {
    if (!showImported) {
      droneShowBlockers.push('No processed Drone Show is loaded. Import a SkyBrush ZIP on the Show Design page first.');
    }

    if (showInfoError && !showImported) {
      droneShowWarnings.push('Show metadata could not be verified from the backend.');
    }

    if (useGlobalSetpoints && autoGlobalOrigin && !isOriginSet) {
      droneShowBlockers.push('Auto Global Launch Corrector requires a configured shared origin.');
    }

    if (useGlobalSetpoints && autoGlobalOrigin && isOriginSet && deviationSummary) {
      if (deviationSummary.online === 0) {
        droneShowBlockers.push('No live drone telemetry is available for launch-position verification.');
      }
      if (deviationSummary.errors > 0) {
        droneShowBlockers.push('Critical launch-position errors must be resolved before launch.');
      }
      if (warningAnalysis.placementWarnings > 0) {
        droneShowWarnings.push('Some drones still have placement warnings. Review Mission Config before launch.');
      }
      if (warningAnalysis.gpsWarnings > 0) {
        droneShowWarnings.push('Some drones have GPS quality warnings. Confirm these are acceptable before launch.');
      }
    }

    if (useGlobalSetpoints && !autoGlobalOrigin) {
      droneShowWarnings.push('GLOBAL manual mode assumes operators placed every drone exactly on its assigned launch point.');
    }
  }

  if (customShowHints && customShowLoading) {
    customShowBlockers.push('Verifying active custom CSV package...');
  }

  if (customShowHints && !customShowLoading) {
    if (!customShowReady) {
      customShowBlockers.push('Custom CSV mode requires shapes_sitl/active.csv (or shapes/active.csv in real mode).');
    }

    if (customShowError && !customShowReady) {
      customShowWarnings.push('Custom CSV metadata could not be verified from the backend.');
    }

    if (customShowReady && !customShowInfo.preview_exists) {
      customShowWarnings.push('Preview image is missing. Regenerate the custom trajectory plot if operators need a visual cross-check.');
    }
  }

  const missionBlockers = showModeHints ? droneShowBlockers : customShowHints ? customShowBlockers : [];
  const missionWarnings = showModeHints ? droneShowWarnings : customShowHints ? customShowWarnings : [];
  const canSendMission = missionBlockers.length === 0;
  
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
                            {/* Placement Status - Most prominent */}
                            {placementStatus && (
                              <div className="deviation-stat placement-status-header" style={{ borderLeft: `4px solid ${placementStatus.color}`, backgroundColor: `${placementStatus.color}15` }}>
                                <span className="deviation-label">Placement Accuracy:</span>
                                <span className="deviation-value placement-status-value" style={{ color: placementStatus.color, fontSize: 'var(--font-size-base)', fontWeight: 'var(--font-weight-bold)' }}>
                                  {placementStatus.icon} {placementStatus.text}
                                </span>
                              </div>
                            )}
                            
                            {/* Metrics Section */}
                            <div className="deviation-metrics-section">
                              <div className="deviation-stat">
                                <span className="deviation-label">Average Deviation:</span>
                                <span className="deviation-value">{deviationSummary.average_deviation?.toFixed(2) || '0.00'}m</span>
                              </div>
                              <div className="deviation-stat">
                                <span className="deviation-label">Worst Deviation:</span>
                                <span className="deviation-value">
                                  {deviationSummary.worst_deviation?.toFixed(2) || '0.00'}m
                                  {worstDeviationDrones.length > 0 && (
                                    <span className="deviation-drones"> (Drone{worstDeviationDrones.length > 1 ? 's' : ''} {worstDeviationDrones.join(', ')})</span>
                                  )}
                                </span>
                              </div>
                              <div className="deviation-stat">
                                <span className="deviation-label">Drones Online:</span>
                                <span className="deviation-value">{deviationSummary.online} drone{deviationSummary.online !== 1 ? 's' : ''}</span>
                              </div>
                            </div>
                            
                            {/* Status Summary - Only show if there are issues */}
                            {(warningAnalysis.gpsWarnings > 0 || warningAnalysis.placementWarnings > 0 || deviationSummary.errors > 0) && (
                              <div className="deviation-issues-section">
                                <div className="deviation-section-title">Status Issues:</div>
                                
                                {/* GPS Warnings (if any) */}
                                {warningAnalysis.gpsWarnings > 0 && (
                                  <div className="deviation-stat gps-warning-stat" title={warningAnalysis.warningDetails.filter(w => w.type === 'gps').map(w => `Drone ${w.hw_id}: ${w.message}`).join('\n')}>
                                    <span className="deviation-label">📡 GPS Quality:</span>
                                    <span className="deviation-value gps-warning-value">
                                      {warningAnalysis.gpsWarnings} warning{warningAnalysis.gpsWarnings !== 1 ? 's' : ''}
                                      <span className="warning-info-note"> (not affecting placement)</span>
                                    </span>
                                  </div>
                                )}
                                
                                {/* Placement Warnings (only if deviation is actually bad) */}
                                {warningAnalysis.placementWarnings > 0 && (
                                  <div className="deviation-stat placement-warning-stat" title={warningAnalysis.warningDetails.filter(w => w.type === 'placement').map(w => `Drone ${w.hw_id}: ${w.message} (${w.deviation.toFixed(2)}m)`).join('\n')}>
                                    <span className="deviation-label">⚠️ Placement:</span>
                                    <span className="deviation-value placement-warning-value">
                                      {warningAnalysis.placementWarnings} drone{warningAnalysis.placementWarnings !== 1 ? 's' : ''} needs adjustment
                                    </span>
                                  </div>
                                )}
                                
                                {/* Errors */}
                                {deviationSummary.errors > 0 && (
                                  <div className="deviation-stat error-stat" title={Object.entries(deviations).filter(([_, d]) => d.status === 'error').map(([hw_id, d]) => `Drone ${hw_id}: ${d.message || 'Error'}`).join('\n')}>
                                    <span className="deviation-label">❌ Critical:</span>
                                    <span className="deviation-value error-value">
                                      {deviationSummary.errors} error{deviationSummary.errors !== 1 ? 's' : ''} detected
                                    </span>
                                  </div>
                                )}
                              </div>
                            )}
                            
                            {/* All Good Message */}
                            {warningAnalysis.gpsWarnings === 0 && warningAnalysis.placementWarnings === 0 && deviationSummary.errors === 0 && placementStatus?.status === 'excellent' && (
                              <div className="deviation-all-good">
                                <span className="all-good-icon">✅</span>
                                <span className="all-good-text">All drones are properly positioned and ready for launch</span>
                              </div>
                            )}
                            
                            {/* Warning details expandable - Only show if there are warnings/errors */}
                            {warningAnalysis.warningDetails.length > 0 && (
                              <details className="warning-details">
                                <summary className="warning-details-summary">
                                  {warningAnalysis.warningDetails.length === 1 
                                    ? 'View warning details' 
                                    : `View ${warningAnalysis.warningDetails.length} warning details`}
                                </summary>
                                <div className="warning-details-content">
                                  {warningAnalysis.warningDetails.map((warning, idx) => (
                                    <div key={idx} className="warning-detail-item">
                                      <div className="warning-detail-header">
                                        <strong>Drone {warning.hw_id}</strong>
                                        <span className={`warning-type-badge ${warning.type}-badge`}>
                                          {warning.type === 'gps' ? 'GPS' : 'Placement'}
                                        </span>
                                      </div>
                                      <div className="warning-detail-message">{warning.message}</div>
                                      {warning.deviation !== undefined && (
                                        <div className="warning-deviation">Deviation: {warning.deviation.toFixed(2)}m</div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </details>
                            )}
                          </>
                        ) : (
                          <div className="deviation-stat">
                            <span className="deviation-label">Status:</span>
                            <span className="deviation-value">Waiting for drone telemetry...</span>
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

      {showModeHints && (
        <div className={`origin-warning ${canSendMission ? '' : 'origin-missing'}`}>
          <div className="warning-icon">{canSendMission ? '✅' : '⚠️'}</div>
          <div className="warning-content">
            <strong>Launch Readiness Snapshot</strong>
            <div className="origin-confirmation">
              <div className="origin-info-row">
                <span className="origin-label">Imported Show:</span>
                <span className="origin-coords">
                  {showImported
                    ? `${showInfo.drone_count} drones • ${showInfo.duration_minutes}m ${showInfo.duration_seconds}s`
                    : 'Not available'}
                </span>
              </div>
              {showImported && (
                <div className="origin-info-row">
                  <span className="origin-label">Max Altitude:</span>
                  <span className="origin-coords">{showInfo.max_altitude} m</span>
                </div>
              )}
            </div>

            {droneShowBlockers.length > 0 && (
              <ul>
                {droneShowBlockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            )}

            {droneShowWarnings.length > 0 && (
              <ul>
                {droneShowWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}

            <p>
              Review the imported geometry in{' '}
              <Link to="/manage-drone-show" className="origin-link">
                Show Design
              </Link>{' '}
              and the live launch setup in{' '}
              <Link to="/mission-config" className="origin-link">
                Mission Config
              </Link>{' '}
              before scheduling launch.
            </p>
          </div>
        </div>
      )}

      {customShowHints && (
        <div className={`origin-warning ${canSendMission ? '' : 'origin-missing'}`}>
          <div className="warning-icon">{canSendMission ? '✅' : '⚠️'}</div>
          <div className="warning-content">
            <strong>Custom CSV Readiness Snapshot</strong>
            <div className="origin-confirmation">
              <div className="origin-info-row">
                <span className="origin-label">Execution Mode:</span>
                <span className="origin-coords">LOCAL launch-frame only</span>
              </div>
              <div className="origin-info-row">
                <span className="origin-label">Active CSV:</span>
                <span className="origin-coords">
                  {customShowReady
                    ? `${customShowInfo.filename} • ${customShowInfo.duration_sec}s • ${customShowInfo.row_count} samples`
                    : 'Not available'}
                </span>
              </div>
              {customShowReady && (
                <div className="origin-info-row">
                  <span className="origin-label">Max Altitude:</span>
                  <span className="origin-coords">{customShowInfo.max_altitude} m</span>
                </div>
              )}
            </div>

            {missionBlockers.length > 0 && (
              <ul>
                {missionBlockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            )}

            {missionWarnings.length > 0 && (
              <ul>
                {missionWarnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}

            <ul>
              <li>Each drone runs the same CSV relative to its own launch point.</li>
              <li>GLOBAL origin correction and shared-origin placement checks do not apply in this mode.</li>
              <li>Use this for advanced/manual testing, not for the normal SkyBrush multi-drone show pipeline.</li>
            </ul>

            <p>
              Review the authored path in{' '}
              <Link to="/custom-show" className="origin-link">
                Custom Show
              </Link>{' '}
              and confirm launch spacing in{' '}
              <Link to="/mission-config" className="origin-link">
                Mission Config
              </Link>{' '}
              before scheduling launch.
            </p>
          </div>
        </div>
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

      <button onClick={onSend} className="mission-button" disabled={!canSendMission}>
        Send Command
      </button>
      <button onClick={onBack} className="back-button">
        Back
      </button>
    </div>
  );
};

export default MissionDetails;
