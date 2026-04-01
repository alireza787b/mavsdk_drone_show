// src/components/trajectory/WaypointModal.js

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import {
  ALTITUDE_REFERENCE,
  calculateSpeed, 
  getSpeedStatus, 
  calculateHeadingForNewWaypoint, 
  suggestOptimalTime,
  TIMING_MODES,
  YAW_CONSTANTS,
  normalizeHeading,
  formatHeading
} from '../../utilities/SpeedCalculator';
import {
  buildTrajectoryWaypointAuthoringCards,
  getTrajectoryAltitudeReferenceDescription,
  getTrajectoryDisplayedHeadingFieldDescription,
  getTrajectoryDisplayedHeadingFieldLabel,
  getTrajectoryLegSpeedReviewLabel,
  getTrajectoryDisplayedTimeFieldLabel,
  getTrajectoryHeadingModeDescription,
  getTrajectoryPreferredSpeedLabel,
  getTrajectoryRequiredSpeedLabel,
  getTrajectoryTimingModeDescription,
  getTrajectoryTimingModeLabel,
} from '../../utilities/trajectoryAuthoringGuidance';
import {
  TRAJECTORY_ALTITUDE_POLICY,
  TRAJECTORY_SPEED_POLICY,
  TRAJECTORY_TERRAIN_POLICY,
  TRAJECTORY_TIMING_POLICY,
  clampPreferredLegSpeed,
  getNominalPreferredLegSpeed,
  getSafeTerrainAdjustedAltitude,
  needsTerrainSafetyAdjustment,
} from '../../constants/trajectoryMissionPolicy';
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
  const [altitude, setAltitude] = useState(TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL);
  const [altitudeReference, setAltitudeReference] = useState(ALTITUDE_REFERENCE.MSL);
  const [targetAgl, setTargetAgl] = useState(TRAJECTORY_ALTITUDE_POLICY.DEFAULT_TARGET_AGL);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [timingMode, setTimingMode] = useState(TIMING_MODES.MANUAL_TIME);
  const [preferredSpeed, setPreferredSpeed] = useState(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [terrainResolved, setTerrainResolved] = useState(false);
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
      let defaultAltitude = TRAJECTORY_ALTITUDE_POLICY.DEFAULT_MSL;
      let defaultAltitudeReference = previousWaypoint?.altitudeReference || ALTITUDE_REFERENCE.MSL;
      let defaultTargetAgl = TRAJECTORY_ALTITUDE_POLICY.DEFAULT_TARGET_AGL;
      
      if (previousWaypoint) {
        // Use previous waypoint's altitude as starting point
        defaultAltitude = previousWaypoint.altitude;
        defaultTargetAgl = previousWaypoint.targetAgl !== undefined
          ? previousWaypoint.targetAgl
          : Math.max(0, previousWaypoint.altitude - (previousWaypoint.groundElevation || 0));
      }
      
      // Initialize time based on distance and speed logic
      let defaultTime = TRAJECTORY_TIMING_POLICY.DEFAULT_ROUTE_ENTRY_DELAY_S;
      let recommendedSpeed = TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED;
      let nextTimingMode = previousWaypoint ? TIMING_MODES.AUTO_SPEED : TIMING_MODES.MANUAL_TIME;
      
      if (previousWaypoint) {
        recommendedSpeed = waypointIndex > 2 && previousWaypoint.estimatedSpeed > 0
          ? getNominalPreferredLegSpeed(previousWaypoint.preferredSpeed || previousWaypoint.estimatedSpeed)
          : TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED;
        defaultTime = suggestOptimalTime(previousWaypoint, position, recommendedSpeed, defaultAltitude);
      }
      
      setAltitude(defaultAltitude);
      setAltitudeReference(defaultAltitudeReference);
      setTargetAgl(defaultTargetAgl);
      setTimeFromStart(defaultTime);
      setPreferredSpeed(recommendedSpeed);
      setTimingMode(nextTimingMode);
      
      // The first waypoint is the mission-start anchor and must stay explicit/manual.
      const headingData = previousWaypoint
        ? calculateHeadingForNewWaypoint(
            position,
            { headingMode: YAW_CONSTANTS.AUTO },
            [previousWaypoint]
          )
        : {
            heading: 0,
            headingMode: YAW_CONSTANTS.MANUAL,
            calculatedHeading: 0,
          };
      setHeading(headingData.heading);
      setHeadingMode(headingData.headingMode);
      setCalculatedHeading(headingData.calculatedHeading);
    }
  }, [isOpen, previousWaypoint, position, waypointIndex]);

  useEffect(() => {
    if (!previousWaypoint || !position || timingMode !== TIMING_MODES.AUTO_SPEED) {
      return;
    }

    const suggestedTime = suggestOptimalTime(
      previousWaypoint,
      position,
      clampPreferredLegSpeed(preferredSpeed),
      altitude
    );

    setTimeFromStart((current) => (current === suggestedTime ? current : suggestedTime));
  }, [altitude, position, preferredSpeed, previousWaypoint, timingMode]);

  useEffect(() => {
    if (altitudeReference !== ALTITUDE_REFERENCE.AGL) {
      return;
    }

    const derivedAltitude = groundElevation + targetAgl;
    setAltitude((current) => (current === derivedAltitude ? current : derivedAltitude));
  }, [altitudeReference, groundElevation, targetAgl]);

  useEffect(() => {
    if (altitudeReference !== ALTITUDE_REFERENCE.MSL) {
      return;
    }

    const derivedAgl = Math.max(0, altitude - groundElevation);
    setTargetAgl((current) => (current === derivedAgl ? current : derivedAgl));
  }, [altitude, altitudeReference, groundElevation]);

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
        setTerrainResolved(false);
        setIsLoadingTerrain(true);
        setTerrainError(null);
        setTerrainFallbackMsg(null);
        setGroundElevation(0);

        const result = await getTerrainElevation(latitude, longitude);

        // Check if aborted during fetch
        if (abortController.signal.aborted) return;

        const elevation = result.elevation;

        if (elevation !== null && elevation !== undefined) {
          setGroundElevation(elevation);

          if (result.error) {
            setTerrainError(result.error);
            setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
          }

          setTerrainResolved(true);

        } else {
          setTerrainError('No elevation data available');
          const estimatedGround = estimateBasicElevation(latitude, longitude);
          setGroundElevation(estimatedGround);
          setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
          setTerrainResolved(true);
        }
      } catch (error) {
        if (abortController.signal.aborted) return;
        setTerrainError('Query failed, using estimated data');
        setTerrainFallbackMsg('Using estimated elevation (API unavailable)');
        const estimatedGround = estimateBasicElevation(latitude, longitude);
        setGroundElevation(estimatedGround);
        setTerrainResolved(true);
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
    setTerrainResolved(true);
  };

  const handleApplySafeTerrainSuggestion = () => {
    setValidationMessage(null);

    if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
      setTargetAgl(TRAJECTORY_TERRAIN_POLICY.DEFAULT_SAFE_CLEARANCE_M);
      return;
    }

    setAltitude(getSafeTerrainAdjustedAltitude(groundElevation));
  };

  const handleConfirm = () => {
    if (!terrainResolved) {
      setValidationMessage({
        tone: 'warning',
        text: 'Wait for terrain elevation to resolve or choose Use Estimate before adding this waypoint.',
      });
      return;
    }

    if (previousWaypoint && timeFromStart <= previousTime) {
      setValidationMessage({
        tone: 'error',
        text: `Waypoint arrival time must be later than the previous waypoint (${previousTime.toFixed(1)}s).`,
      });
      return;
    }

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
      altitudeReference,
      targetAgl: parseFloat(targetAgl),
      timeFromStart: parseFloat(timeFromStart),
      timingMode,
      preferredSpeed: parseFloat(preferredSpeed),
      estimatedSpeed,
      speedFeasible: true,
      groundElevation,
      terrainAccurate: terrainResolved && !terrainError,
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
    const newAltitudeValue = parseFloat(e.target.value) || 0;
    setValidationMessage(null);
    if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
      setTargetAgl(Math.max(0, newAltitudeValue));
      setAltitude(groundElevation + Math.max(0, newAltitudeValue));
      return;
    }
    setAltitude(newAltitudeValue);
  };

  const handleTimeChange = (e) => {
    const newTime = parseFloat(e.target.value) || 0;
    setValidationMessage(null);
    setTimeFromStart(Math.max(0, newTime));
  };

  const handleTimingModeChange = (newMode) => {
    setTimingMode(newMode);
    setValidationMessage(null);

    if (newMode === TIMING_MODES.AUTO_SPEED && previousWaypoint && position) {
      setTimeFromStart(
        suggestOptimalTime(
          previousWaypoint,
          position,
          clampPreferredLegSpeed(preferredSpeed),
          altitude
        )
      );
    }
  };

  const handlePreferredSpeedChange = (e) => {
    const nextSpeed = parseFloat(e.target.value);
    setValidationMessage(null);
    setPreferredSpeed(clampPreferredLegSpeed(nextSpeed, TRAJECTORY_SPEED_POLICY.MIN_PREFERRED));
  };

  const handleAltitudeReferenceChange = (newReference) => {
    setValidationMessage(null);
    if (newReference === ALTITUDE_REFERENCE.AGL) {
      setTargetAgl(Math.max(0, altitude - groundElevation));
    }
    setAltitudeReference(newReference);
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
  const needsTerrainReview = terrainResolved && needsTerrainSafetyAdjustment(altitude, groundElevation);
  const safeSuggestedAltitude = getSafeTerrainAdjustedAltitude(groundElevation);
  const previousTime = previousWaypoint?.timeFromStart || 0;
  const legDuration = Math.max(0, timeFromStart - previousTime);
  const authoringCards = buildTrajectoryWaypointAuthoringCards({
    altitudeReference,
    altitude,
    targetAgl: aglAltitude,
    groundElevation,
    terrainResolved,
    terrainAccurate: terrainResolved && !terrainError,
    isMissionAnchor: !previousWaypoint,
    timingMode,
    timeFromStart,
    preferredSpeed,
    requiredSpeed: estimatedSpeed,
    speedStatus,
    headingMode,
    heading,
    calculatedHeading,
  });

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
                  Smart defaults continue altitude from the previous waypoint and start the new leg in speed-driven ETA mode.
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

            <div className="timing-mode-selector">
              <label className="input-label">🏔️ Altitude Entry</label>
              <div className="radio-group">
                <label
                  className="radio-option"
                  title={getTrajectoryAltitudeReferenceDescription(ALTITUDE_REFERENCE.MSL)}
                >
                  <input
                    type="radio"
                    name="altitudeReference"
                    checked={altitudeReference === ALTITUDE_REFERENCE.MSL}
                    onChange={() => handleAltitudeReferenceChange(ALTITUDE_REFERENCE.MSL)}
                  />
                  <span className="radio-label">MSL input</span>
                </label>
                <label
                  className="radio-option"
                  title={getTrajectoryAltitudeReferenceDescription(ALTITUDE_REFERENCE.AGL)}
                >
                  <input
                    type="radio"
                    name="altitudeReference"
                    checked={altitudeReference === ALTITUDE_REFERENCE.AGL}
                    onChange={() => handleAltitudeReferenceChange(ALTITUDE_REFERENCE.AGL)}
                  />
                  <span className="radio-label">Target AGL</span>
                </label>
              </div>
            </div>

            <div className="altitude-input-group">
              <label htmlFor="altitude" className="input-label">
                {altitudeReference === ALTITUDE_REFERENCE.AGL ? '🏔️ Target Clearance (AGL)' : '🏔️ Altitude (MSL)'}
                {isLoadingTerrain && <span className="loading-indicator"> ⟳</span>}
              </label>
              <input
                ref={altitudeRef}
                id="altitude"
                type="number"
                value={altitudeReference === ALTITUDE_REFERENCE.AGL ? targetAgl : altitude}
                onChange={handleAltitudeChange}
                className={`waypoint-input ${isUnderground ? 'validation-error' : ''}`}
                placeholder={altitudeReference === ALTITUDE_REFERENCE.AGL ? 'Height above ground in meters' : 'Altitude in meters MSL'}
                step="1"
                min="0"
                max={String(TRAJECTORY_ALTITUDE_POLICY.MAX_MSL)}
              />
              <div className="altitude-context">
                <small className="terrain-note">
                  Ground elevation: <strong>{terrainResolved ? `${groundElevation.toFixed(1)}m MSL` : 'resolving...'}</strong>
                  {terrainError && <span className="terrain-warning"> ({terrainError})</span>}
                </small>
                <small className="agl-note">
                  Above ground: <strong>{aglAltitude.toFixed(1)}m AGL</strong>
                </small>
                <small className="agl-note">
                  Mission stores altitude as <strong>{altitude.toFixed(1)}m MSL</strong>
                </small>
                <small className="agl-note">
                  Planner envelope: <strong>{TRAJECTORY_ALTITUDE_POLICY.MIN_MSL}-{TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()}m MSL</strong>
                </small>
                {previousWaypoint && (
                  <small className="altitude-source">
                    Pre-filled from previous waypoint ({previousWaypoint.altitude.toFixed(1)}m MSL)
                  </small>
                )}
                {!terrainResolved && (
                  <small className="terrain-warning">
                    Waypoint confirmation stays locked until terrain resolves or you choose Use Estimate.
                  </small>
                )}
              </div>
              {needsTerrainReview && (
                <div className={`validation-message ${isUnderground ? 'error' : 'warning'}`}>
                  <div className="validation-message__body">
                    <span>
                      {isUnderground
                        ? `Stored altitude is below terrain here. Current clearance is ${aglAltitude.toFixed(1)}m AGL against ground at ${groundElevation.toFixed(1)}m MSL.`
                        : `Current clearance is ${aglAltitude.toFixed(1)}m AGL, below the ${TRAJECTORY_TERRAIN_POLICY.MIN_SAFE_CLEARANCE_M}m review floor.`}
                      {' '}
                      {altitudeReference === ALTITUDE_REFERENCE.AGL
                        ? `The mission still stores ${altitude.toFixed(1)}m MSL from your clearance target.`
                        : `Your stored MSL altitude remains ${altitude.toFixed(1)}m unless you change it.`}
                    </span>
                    <button
                      type="button"
                      className="validation-action-btn"
                      onClick={handleApplySafeTerrainSuggestion}
                    >
                      {altitudeReference === ALTITUDE_REFERENCE.AGL
                        ? `Use ${TRAJECTORY_TERRAIN_POLICY.DEFAULT_SAFE_CLEARANCE_M.toFixed(1)}m AGL`
                        : `Use ${safeSuggestedAltitude.toFixed(1)}m MSL`}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="time-input-group">
            {previousWaypoint && (
              <div className="timing-mode-selector">
                <label className="input-label">🗓️ Leg Planning</label>
                <div className="radio-group">
                  <label
                    className="radio-option"
                    title={getTrajectoryTimingModeDescription(TIMING_MODES.AUTO_SPEED)}
                  >
                    <input
                      type="radio"
                      name="timingMode"
                      checked={timingMode === TIMING_MODES.AUTO_SPEED}
                      onChange={() => handleTimingModeChange(TIMING_MODES.AUTO_SPEED)}
                    />
                    <span className="radio-label">{getTrajectoryTimingModeLabel(TIMING_MODES.AUTO_SPEED)}</span>
                  </label>
                  <label
                    className="radio-option"
                    title={getTrajectoryTimingModeDescription(TIMING_MODES.MANUAL_TIME)}
                  >
                    <input
                      type="radio"
                      name="timingMode"
                      checked={timingMode === TIMING_MODES.MANUAL_TIME}
                      onChange={() => handleTimingModeChange(TIMING_MODES.MANUAL_TIME)}
                    />
                    <span className="radio-label">{getTrajectoryTimingModeLabel(TIMING_MODES.MANUAL_TIME)}</span>
                  </label>
                </div>
              </div>
            )}

            {previousWaypoint && timingMode === TIMING_MODES.AUTO_SPEED && (
              <div className="preferred-speed-group">
                <label htmlFor="preferredSpeed" className="input-label">{getTrajectoryPreferredSpeedLabel()}</label>
                <input
                  id="preferredSpeed"
                  type="number"
                  value={preferredSpeed}
                  onChange={handlePreferredSpeedChange}
                  className="waypoint-input"
                  min={String(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED)}
                  max={String(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX)}
                  step={String(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED)}
                />
                <small className="time-calculation">
                  Auto mode derives waypoint arrival time from the inbound 3D leg distance and your preferred leg speed.
                </small>
                <small className="time-calculation">
                  Nominal envelope: {TRAJECTORY_SPEED_POLICY.MIN_PREFERRED}-{TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX} m/s.
                </small>
              </div>
            )}

            <label htmlFor="timeFromStart" className="input-label">
              {`⏱️ ${getTrajectoryDisplayedTimeFieldLabel({
                isMissionAnchor: !previousWaypoint,
                timingMode,
              })}`}
            </label>
            <input
              id="timeFromStart"
              type="number"
              value={timeFromStart}
              onChange={handleTimeChange}
              className={`waypoint-input ${timingMode === TIMING_MODES.AUTO_SPEED && previousWaypoint ? 'disabled-input' : ''}`}
              placeholder={previousWaypoint ? 'Seconds from mission start' : 'Seconds after mission start'}
              step={String(TRAJECTORY_TIMING_POLICY.DERIVED_TIME_STEP_S)}
              min="0"
              disabled={timingMode === TIMING_MODES.AUTO_SPEED && Boolean(previousWaypoint)}
            />
            {previousWaypoint && (
              <div className="timing-summary">
                <small className="time-calculation">
                  Leg duration: <strong>{legDuration.toFixed(1)}s</strong>
                </small>
                <small className="time-calculation">
                  Mode: <strong>{getTrajectoryTimingModeLabel(timingMode)}</strong>
                </small>
                {timingMode === TIMING_MODES.AUTO_SPEED ? (
                  <small className="time-calculation">
                    Arrival stays derived in this mode. Switch to Time-driven speed to pin the mission clock yourself.
                  </small>
                ) : (
                  <small className="time-calculation">
                    Required inbound-leg speed updates live from the arrival time you pin here.
                  </small>
                )}
              </div>
            )}
            {!previousWaypoint && (
              <div className="timing-summary">
                <small className="time-calculation">
                  This first waypoint anchors the route-entry delay after mission start.
                </small>
                <small className="time-calculation">
                  Default route-entry delay starts at {TRAJECTORY_TIMING_POLICY.DEFAULT_ROUTE_ENTRY_DELAY_S}s. Increase it if launch, form-up, or cluster spacing needs more time before the route begins.
                </small>
              </div>
            )}
          </div>

          <div className="heading-section">
            <div className="heading-input-group">
              <label htmlFor="heading" className="input-label">
                {`🧭 ${getTrajectoryDisplayedHeadingFieldLabel({
                  isMissionAnchor: !previousWaypoint,
                  headingMode,
                })}`}
                <span className="heading-display">({formatHeading(heading)})</span>
              </label>
              
              <div className="heading-mode-selector">
                <div className="radio-group">
                  {previousWaypoint && (
                    <label
                      className="radio-option"
                      title={getTrajectoryHeadingModeDescription(YAW_CONSTANTS.AUTO)}
                    >
                      <input
                        type="radio"
                        name="headingMode"
                        checked={headingMode === YAW_CONSTANTS.AUTO}
                        onChange={() => handleHeadingModeChange(YAW_CONSTANTS.AUTO)}
                      />
                      <span className="radio-label">
                        Auto (arrival leg)
                        <span className="auto-heading-value"> - {formatHeading(calculatedHeading)}</span>
                      </span>
                    </label>
                  )}
                  <label
                    className="radio-option"
                    title={getTrajectoryHeadingModeDescription(YAW_CONSTANTS.MANUAL, {
                      isMissionAnchor: !previousWaypoint,
                    })}
                  >
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
                    {getTrajectoryDisplayedHeadingFieldDescription({
                      isMissionAnchor: !previousWaypoint,
                      headingMode,
                    })} Current inbound-leg heading: {formatHeading(calculatedHeading)} from waypoint {waypointIndex - 1}.
                  </small>
                )}
                {headingMode === YAW_CONSTANTS.MANUAL && (
                  <small className="manual-heading-note">
                    Manual mode: Operator-locked heading ({formatHeading(heading)})
                  </small>
                )}
                {!previousWaypoint && (
                  <small className="first-waypoint-note">
                    First waypoint: Set the initial route-entry heading explicitly
                  </small>
                )}
              </div>
            </div>
          </div>

          {previousWaypoint && (
            <div className="speed-section">
              <div className="speed-display" style={getSpeedStatusStyle(speedStatus)}>
                <div className="speed-header">
                  <span className="speed-label">
                    {timingMode === TIMING_MODES.AUTO_SPEED
                      ? getTrajectoryLegSpeedReviewLabel()
                      : getTrajectoryRequiredSpeedLabel()}
                  </span>
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
                {timingMode === TIMING_MODES.AUTO_SPEED ? (
                  <small className="speed-note">
                    {getTrajectoryPreferredSpeedLabel()}: {preferredSpeed.toFixed(1)} m/s
                  </small>
                ) : (
                  <small className="speed-note">
                    Time-driven speed mode uses your chosen waypoint arrival time to derive the required leg speed.
                  </small>
                )}
              </div>
            </div>
          )}

          <div className="waypoint-authoring-brief" aria-label="Waypoint authoring brief">
            {authoringCards.map((card) => (
              <div key={card.key} className={`waypoint-authoring-card waypoint-authoring-card--${card.tone}`}>
                <span className="waypoint-authoring-card__label">{card.label}</span>
                <strong className="waypoint-authoring-card__value">{card.value}</strong>
                <span className="waypoint-authoring-card__detail">{card.detail}</span>
              </div>
            ))}
          </div>

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
            disabled={!terrainResolved}
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
