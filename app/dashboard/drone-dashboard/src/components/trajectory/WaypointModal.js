// src/components/trajectory/WaypointModal.js

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { 
  calculateSpeed, 
  getSpeedStatus, 
  calculateHeadingForNewWaypoint, 
  YAW_CONSTANTS,
  normalizeHeading,
  formatHeading
} from '../../utilities/SpeedCalculator';
import { getTerrainElevation } from '../../services/ElevationService';
import '../../styles/WaypointModal.css';

const WaypointModal = ({
  isOpen,
  onClose,
  onConfirm,
  position,
  previousWaypoint,
  waypointIndex = 1,
}) => {
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [isLoadingTerrain, setIsLoadingTerrain] = useState(false);
  const [terrainError, setTerrainError] = useState(null);
  const [terrainElapsed, setTerrainElapsed] = useState(0);
  const [terrainFallbackMsg, setTerrainFallbackMsg] = useState(null);
  const [validationMessage, setValidationMessage] = useState(null);

  // Heading state (aviation standard)
  const [heading, setHeading] = useState(0);
  const [headingMode, setHeadingMode] = useState(YAW_CONSTANTS.AUTO);
  const [calculatedHeading, setCalculatedHeading] = useState(0);

  const altitudeRef = useRef(null);
  const elevationAbortRef = useRef(null);

  useEffect(() => {
    if (isOpen && altitudeRef.current) {
      altitudeRef.current.focus();
      altitudeRef.current.select();
    }
  }, [isOpen]);

  // Elapsed timer while loading terrain
  useEffect(() => {
    if (!isLoadingTerrain) {
      setTerrainElapsed(0);
      return;
    }
    setTerrainElapsed(0);
    const interval = setInterval(() => {
      setTerrainElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(interval);
  }, [isLoadingTerrain]);

  // Enhanced pre-population logic based on waypoint index and previous waypoint data
  useEffect(() => {
    if (isOpen && position) {
      setValidationMessage(null);
      // Initialize altitude based on previous waypoint or intelligent defaults
      let defaultAltitude = 100; // Base default
      
      if (previousWaypoint) {
        // Use previous waypoint's altitude as starting point
        defaultAltitude = previousWaypoint.altitude;
      }
      
      // Initialize time based on distance and speed logic
      let defaultTime = 10; // Base default for first waypoint
      
      if (previousWaypoint) {
        // Calculate distance to this new position
        const distanceToNew = Math.sqrt(
          Math.pow((position.latitude - previousWaypoint.latitude) * 111000, 2) + // Rough lat to meters
          Math.pow((position.longitude - previousWaypoint.longitude) * 111000 * Math.cos(position.latitude * Math.PI / 180), 2) // Rough lng to meters
        );
        
        // Determine recommended speed based on waypoint sequence
        let recommendedSpeed = 8; // Default moderate speed
        
        if (waypointIndex === 2) {
          // Second waypoint: use default moderate speed
          recommendedSpeed = 8;
        } else if (waypointIndex > 2 && previousWaypoint.estimatedSpeed > 0) {
          // Third waypoint onwards: use speed from previous leg
          recommendedSpeed = Math.min(previousWaypoint.estimatedSpeed, 15); // Cap at 15 m/s for safety
        }
        
        // Calculate recommended time based on distance and speed
        const recommendedTimeIncrement = Math.max(3, distanceToNew / recommendedSpeed);
        defaultTime = (previousWaypoint.timeFromStart || 0) + Math.ceil(recommendedTimeIncrement);
      }
      
      setAltitude(defaultAltitude);
      setTimeFromStart(defaultTime);
      
      // Initialize heading data - calculate default heading to next waypoint (aviation standard)
      const headingData = calculateHeadingForNewWaypoint(position, { headingMode: YAW_CONSTANTS.AUTO }, previousWaypoint ? [previousWaypoint] : []);
      setHeading(headingData.heading);
      setHeadingMode(headingData.headingMode);
      setCalculatedHeading(headingData.calculatedHeading);
    }
  }, [isOpen, previousWaypoint, position, waypointIndex]);

  useEffect(() => {
    if (!isOpen || !position) return;

    // Abort any previous in-flight fetch
    if (elevationAbortRef.current) {
      elevationAbortRef.current.abort();
    }

    const abortController = new AbortController();
    elevationAbortRef.current = abortController;

    const fetchElevation = async (latitude, longitude) => {
      try {
        setIsLoadingTerrain(true);
        setTerrainError(null);
        setTerrainFallbackMsg(null);

        const result = await getTerrainElevation(latitude, longitude);

        // Check if aborted during fetch
        if (abortController.signal.aborted) return;

        const elevation = result.elevation;

        if (elevation !== null && elevation !== undefined) {
          setGroundElevation(elevation);

          setAltitude(prev => {
            if (prev < elevation + 50) {
              return elevation + 100;
            }
            return prev;
          });

          if (result.error) {
            setTerrainError(result.error);
            setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
          }

        } else {
          setTerrainError('No elevation data available');
          const estimatedGround = estimateBasicElevation(latitude, longitude);
          setGroundElevation(estimatedGround);
          setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
          setAltitude(prev => {
            if (prev < estimatedGround + 50) {
              return estimatedGround + 100;
            }
            return prev;
          });
        }
      } catch (error) {
        if (abortController.signal.aborted) return;
        setTerrainError('Query failed, using estimated data');
        setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
        const estimatedGround = estimateBasicElevation(latitude, longitude);
        setGroundElevation(estimatedGround);
        setAltitude(prev => {
          if (prev < estimatedGround + 50) {
            return estimatedGround + 100;
          }
          return prev;
        });
      } finally {
        if (!abortController.signal.aborted) {
          setIsLoadingTerrain(false);
        }
      }
    };

    fetchElevation(position.latitude, position.longitude);

    return () => {
      abortController.abort();
    };
  }, [isOpen, position]);

  useEffect(() => {
    if (previousWaypoint && position && timeFromStart > (previousWaypoint.timeFromStart || 0)) {
      const speed = calculateSpeed(
        previousWaypoint,
        { ...position, timeFromStart, altitude },
        position
      );
      setEstimatedSpeed(speed);
      setSpeedStatus(getSpeedStatus(speed));
    } else {
      setEstimatedSpeed(0);
      setSpeedStatus('unknown');
    }
  }, [position, previousWaypoint, timeFromStart, altitude]);

  // Use refs to hold latest handler versions, avoiding stale closures in keydown listener
  const handleConfirmRef = useRef(null);
  const handleCancelRef = useRef(null);

  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!isOpen) return;
      if (e.key === 'Escape') {
        handleCancelRef.current?.();
      } else if (e.key === 'Enter' && e.ctrlKey) {
        handleConfirmRef.current?.();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const estimateBasicElevation = (latitude, longitude) => {
    if (Math.abs(latitude) > 60) return 300; // Polar regions
    if (Math.abs(latitude) < 30) return 50;  // Tropical regions

    if (latitude > 25 && latitude < 50 && longitude > -125 && longitude < -100) return 1500; // Rocky Mountains
    if (latitude > 25 && latitude < 45 && longitude > 65 && longitude < 105) return 2000;   // Himalayas

    return 150; // Default continental
  };

  const handleSkipElevation = () => {
    // Cancel in-flight fetch
    if (elevationAbortRef.current) {
      elevationAbortRef.current.abort();
    }
    setIsLoadingTerrain(false);
    const estimatedGround = estimateBasicElevation(
      position?.latitude || 0,
      position?.longitude || 0
    );
    setGroundElevation(estimatedGround);
    setTerrainError('Using estimate (skipped API)');
    setTerrainFallbackMsg('Using estimated elevation (skipped by user)');
    setAltitude((prev) => {
      if (prev < estimatedGround + 50) {
        return estimatedGround + 100;
      }
      return prev;
    });
  };

  const handleConfirm = () => {
    const isUnderground = altitude < groundElevation;

    if (isUnderground) {
      setValidationMessage({
        tone: 'error',
        text: `Altitude must stay above ground. Minimum safe entry here is ${groundElevation.toFixed(1)} m MSL.`,
      });
      altitudeRef.current?.focus();
      return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed,
      speedFeasible: true,
      groundElevation,
      terrainAccurate: !terrainError,
      // Aviation standard heading data
      heading: parseFloat(heading),
      headingMode,
      calculatedHeading
    };

    onConfirm(waypointData);
  };

  const handleCancel = () => {
    onClose();
  };

  // Keep refs in sync for keyboard handler
  handleConfirmRef.current = handleConfirm;
  handleCancelRef.current = handleCancel;

  const handleAltitudeChange = (e) => {
    const newAltitude = parseFloat(e.target.value) || 0;
    setValidationMessage(null);
    setAltitude(newAltitude);
  };

  const handleTimeChange = (e) => {
    const newTime = parseFloat(e.target.value) || 0;
    setValidationMessage(null);
    setTimeFromStart(Math.max(0, newTime));
  };

  const handleHeadingModeChange = (newMode) => {
    setHeadingMode(newMode);
    
    if (newMode === YAW_CONSTANTS.AUTO) {
      // Switch to auto mode: use calculated heading
      setHeading(calculatedHeading);
    }
    // Manual mode: keep current heading value
  };

  const handleHeadingChange = (e) => {
    const newHeading = parseFloat(e.target.value) || 0;
    const normalizedHeading = normalizeHeading(newHeading);
    setValidationMessage(null);
    setHeading(normalizedHeading);
    
    // Switch to manual mode when user enters custom heading
    if (headingMode === YAW_CONSTANTS.AUTO) {
      setHeadingMode(YAW_CONSTANTS.MANUAL);
    }
  };

  const getSpeedStatusStyle = (status) => {
    switch (status) {
      case 'feasible': return { color: '#28a745', backgroundColor: '#d4edda' };
      case 'marginal': return { color: '#ffc107', backgroundColor: '#fff3cd' };
      case 'impossible': return { color: '#dc3545', backgroundColor: '#f8d7da' };
      default: return { color: '#6c757d', backgroundColor: '#e9ecef' };
    }
  };

  const isUnderground = altitude < groundElevation;
  const aglAltitude = Math.max(0, altitude - groundElevation);

  if (!isOpen) return null;

  return (
    <div className="waypoint-modal-overlay" onClick={handleCancel}>
      <div className="waypoint-modal" onClick={(e) => e.stopPropagation()}>
        <div className="waypoint-modal-header">
          <h3>Add Waypoint {waypointIndex}</h3>
          <button
            className="waypoint-modal-close"
            onClick={handleCancel}
            title="Close (Esc)"
          >
            ✕
          </button>
        </div>

        <div className="waypoint-modal-body">
          <div className="waypoint-location-info">
            <div className="location-item">
              <label>📍 Coordinates</label>
              <span>{position?.latitude?.toFixed(6)}, {position?.longitude?.toFixed(6)}</span>
            </div>
            
            {/* Smart defaults info */}
            {previousWaypoint && (
              <div className="smart-defaults-info">
                <small className="defaults-note">
                  💡 Smart defaults: Altitude from previous waypoint
                  {waypointIndex === 2 && ', moderate speed (8 m/s)'}
                  {waypointIndex > 2 && previousWaypoint.estimatedSpeed > 0 && `, continuing at ${Math.min(previousWaypoint.estimatedSpeed, 15).toFixed(1)} m/s`}
                </small>
              </div>
            )}
          </div>

          <div className="altitude-section">
            {/* Terrain loading banner */}
            {isLoadingTerrain && (
              <div className="wm-terrain-banner">
                <div className="wm-terrain-progress" />
                <div className="wm-terrain-banner-content">
                  <span className="wm-terrain-banner-text">
                    Loading terrain elevation... {terrainElapsed > 0 && `(${terrainElapsed}s)`}
                  </span>
                  <button
                    className="wm-terrain-skip-btn"
                    onClick={handleSkipElevation}
                    type="button"
                  >
                    Use Estimate
                  </button>
                </div>
              </div>
            )}

            {/* Fallback message + editable ground elevation after API unavailable */}
            {!isLoadingTerrain && terrainFallbackMsg && (
              <div className="wm-terrain-fallback-msg">
                <div>{terrainFallbackMsg}</div>
                <div className="wm-ground-elevation-edit">
                  <label htmlFor="groundElevationOverride" className="wm-ground-elevation-label">
                    Ground elevation (m MSL):
                  </label>
                  <input
                    id="groundElevationOverride"
                    type="number"
                    className="wm-ground-elevation-input"
                    value={groundElevation}
                    onChange={(e) => {
                      const val = parseFloat(e.target.value);
                      if (!isNaN(val)) setGroundElevation(val);
                    }}
                    step="1"
                    min="0"
                    max="9000"
                  />
                </div>
              </div>
            )}

            <div className="altitude-input-group">
              <label htmlFor="altitude" className="input-label">
                🏔️ Altitude (MSL)
                {isLoadingTerrain && <span className="loading-indicator"> ⟳</span>}
              </label>
              <input
                ref={altitudeRef}
                id="altitude"
                type="number"
                value={altitude}
                onChange={handleAltitudeChange}
                className={`waypoint-input ${isUnderground ? 'validation-error' : ''}`}
                placeholder="Altitude in meters MSL"
                step="1"
                min="0"
                max="10000"
              />
              <div className="altitude-context">
                <small className="terrain-note">
                  Ground elevation: <strong>{groundElevation.toFixed(1)}m MSL</strong>
                  {terrainError && <span className="terrain-warning"> ({terrainError})</span>}
                </small>
                <small className="agl-note">
                  Above ground: <strong>{aglAltitude.toFixed(1)}m AGL</strong>
                </small>
                {previousWaypoint && (
                  <small className="altitude-source">
                    Pre-filled from previous waypoint ({previousWaypoint.altitude.toFixed(1)}m MSL)
                  </small>
                )}
              </div>
              {isUnderground && (
                <div className="validation-message error">
                  ⚠️ Altitude is below ground level! Minimum: {groundElevation.toFixed(1)}m MSL
                </div>
              )}
            </div>
          </div>

          <div className="time-input-group">
            <label htmlFor="timeFromStart" className="input-label">⏱️ Time from Start</label>
            <input
              id="timeFromStart"
              type="number"
              value={timeFromStart}
              onChange={handleTimeChange}
              className="waypoint-input"
              placeholder="Seconds from mission start"
              step="1"
              min="0"
            />
            {previousWaypoint && (
              <small className="time-calculation">
                Calculated based on distance and {waypointIndex === 2 ? 'moderate speed (8 m/s)' : 'previous leg speed'}
              </small>
            )}
          </div>

          <div className="heading-section">
            <div className="heading-input-group">
              <label htmlFor="heading" className="input-label">
                🧭 Heading
                <span className="heading-display">({formatHeading(heading)})</span>
              </label>
              
              <div className="heading-mode-selector">
                <div className="radio-group">
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="headingMode"
                      checked={headingMode === YAW_CONSTANTS.AUTO}
                      onChange={() => handleHeadingModeChange(YAW_CONSTANTS.AUTO)}
                    />
                    <span className="radio-label">
                      Auto (to next waypoint)
                      {previousWaypoint && <span className="auto-heading-value"> - {formatHeading(calculatedHeading)}</span>}
                    </span>
                  </label>
                  <label className="radio-option">
                    <input
                      type="radio"
                      name="headingMode"
                      checked={headingMode === YAW_CONSTANTS.MANUAL}
                      onChange={() => handleHeadingModeChange(YAW_CONSTANTS.MANUAL)}
                    />
                    <span className="radio-label">Manual</span>
                  </label>
                </div>
              </div>

              <input
                id="heading"
                type="number"
                value={heading}
                onChange={handleHeadingChange}
                className={`waypoint-input ${headingMode === YAW_CONSTANTS.AUTO ? 'disabled-input' : ''}`}
                placeholder="Heading in degrees (0-360)"
                step="0.1"
                min="0"
                max="360"
                disabled={headingMode === YAW_CONSTANTS.AUTO}
              />
              
              <div className="heading-context">
                <small className="heading-note">
                  Aviation Standard: 000° = North, 090° = East, 180° = South, 270° = West
                </small>
                {headingMode === YAW_CONSTANTS.AUTO && previousWaypoint && (
                  <small className="auto-heading-note">
                    Auto mode: Points toward next waypoint ({formatHeading(calculatedHeading)})
                  </small>
                )}
                {headingMode === YAW_CONSTANTS.MANUAL && (
                  <small className="manual-heading-note">
                    Manual mode: Custom heading ({formatHeading(heading)})
                  </small>
                )}
                {!previousWaypoint && (
                  <small className="first-waypoint-note">
                    First waypoint: Set initial drone heading
                  </small>
                )}
              </div>
            </div>
          </div>

          {previousWaypoint && (
            <div className="speed-section">
              <div className="speed-display" style={getSpeedStatusStyle(speedStatus)}>
                <div className="speed-header">
                  <span className="speed-label">Required Speed</span>
                  <span className="speed-value">{estimatedSpeed.toFixed(1)} m/s</span>
                  <span className="speed-kmh">({(estimatedSpeed * 3.6).toFixed(1)} km/h)</span>
                </div>
                {speedStatus !== 'feasible' && (
                  <div className="speed-warning">
                    {speedStatus === 'marginal' ? '⚠️ High speed - use caution' : '🚨 Very high speed - review timing'}
                  </div>
                )}
                <small className="speed-note">
                  From waypoint {waypointIndex - 1} to waypoint {waypointIndex}
                </small>
              </div>
            </div>
          )}

          {validationMessage && (
            <div className={`validation-message ${validationMessage.tone || 'warning'}`} aria-live="polite">
              {validationMessage.text}
            </div>
          )}
        </div>

        <div className="waypoint-modal-footer">
          <button
            onClick={handleCancel}
            className="modal-btn secondary"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            className="modal-btn primary"
            title="Add waypoint (Ctrl+Enter)"
          >
            Add Waypoint
          </button>
        </div>
      </div>
    </div>
  );
};

WaypointModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
  position: PropTypes.shape({
    latitude: PropTypes.number.isRequired,
    longitude: PropTypes.number.isRequired,
  }),
  previousWaypoint: PropTypes.object,
  waypointIndex: PropTypes.number,
  // mapRef: PropTypes.object.isRequired, // Remove if not used elsewhere
};

export default WaypointModal;
