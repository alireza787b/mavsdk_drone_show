// src/components/trajectory/WaypointModal.js

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import {
  MdCalendarToday,
  MdExplore,
  MdPlace,
  MdTerrain,
  MdTimer,
  MdWarningAmber,
} from 'react-icons/md';
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
import { resolveMissionTrajectoryTerrain } from '../../utilities/trajectoryTerrainContext';
import TrajectoryDialogPortal from './TrajectoryDialogPortal';
import '../../styles/WaypointModal.css';

const formatFieldNumber = (value) => Number.isFinite(value) ? value.toFixed(1) : '—';

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
  const [groundElevation, setGroundElevation] = useState(null);
  const [terrainResolved, setTerrainResolved] = useState(false);
  const [isLoadingTerrain, setIsLoadingTerrain] = useState(false);
  const [terrainError, setTerrainError] = useState(null);
  const [terrainElapsed, setTerrainElapsed] = useState(0);
  const [terrainSource, setTerrainSource] = useState('');
  const [terrainConfidence, setTerrainConfidence] = useState('');
  const [terrainSampleTime, setTerrainSampleTime] = useState(null);
  const [terrainRetry, setTerrainRetry] = useState(0);
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
      let defaultAltitudeReference = String(previousWaypoint?.altitudeReference || '').toLowerCase() === ALTITUDE_REFERENCE.AGL
        ? ALTITUDE_REFERENCE.AGL : ALTITUDE_REFERENCE.MSL;
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
    if (!previousWaypoint || !position || timingMode !== TIMING_MODES.AUTO_SPEED
        || !Number.isFinite(preferredSpeed) || !Number.isFinite(altitude)) {
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
    if (altitudeReference !== ALTITUDE_REFERENCE.AGL || !terrainResolved || !Number.isFinite(groundElevation) || !Number.isFinite(targetAgl)) {
      return;
    }

    const derivedAltitude = groundElevation + targetAgl;
    setAltitude((current) => (current === derivedAltitude ? current : derivedAltitude));
  }, [altitudeReference, groundElevation, targetAgl, terrainResolved]);

  useEffect(() => {
    if (altitudeReference !== ALTITUDE_REFERENCE.MSL || !terrainResolved || !Number.isFinite(groundElevation) || !Number.isFinite(altitude)) {
      return;
    }

    const derivedAgl = Math.max(0, altitude - groundElevation);
    setTargetAgl((current) => (current === derivedAgl ? current : derivedAgl));
  }, [altitude, altitudeReference, groundElevation, terrainResolved]);

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
        setGroundElevation(null);
        setTerrainSource('backend');
        setTerrainConfidence('');
        setTerrainSampleTime(null);

        const result = await resolveMissionTrajectoryTerrain(latitude, longitude);

        // Check if aborted during fetch
        if (abortController.signal.aborted) return;

        setTerrainSource(result.source);
        setTerrainConfidence(result.confidence);
        setTerrainSampleTime(result.sample_time);
        if (result.verified === true && Number.isFinite(result.elevation) && !result.error) {
          setGroundElevation(result.elevation);
          setTerrainResolved(true);
        } else {
          setTerrainError(result.error || 'Terrain elevation unavailable.');
        }
      } catch (error) {
        if (abortController.signal.aborted) return;
        setTerrainError(error?.message || 'Terrain elevation unavailable.');
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
  }, [isOpen, position, terrainRetry]);

  useEffect(() => {
    if (previousWaypoint && position && Number.isFinite(altitude) && Number.isFinite(timeFromStart) && timeFromStart > (previousWaypoint.timeFromStart ?? 0)) {
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

  const handleApplySafeTerrainSuggestion = () => {
    setValidationMessage(null);

    if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
      setTargetAgl(TRAJECTORY_TERRAIN_POLICY.DEFAULT_SAFE_CLEARANCE_M);
      return;
    }

    setAltitude(getSafeTerrainAdjustedAltitude(groundElevation));
  };

  const handleConfirm = () => {
    if (altitudeReference === ALTITUDE_REFERENCE.AGL && !terrainResolved) {
      setValidationMessage({
        tone: 'warning',
        text: 'AGL needs verified terrain. Retry the lookup or use MSL input.',
      });
      return;
    }

    if (!Number.isFinite(altitude) || altitude < TRAJECTORY_ALTITUDE_POLICY.MIN_MSL || altitude > TRAJECTORY_ALTITUDE_POLICY.MAX_MSL) {
      setValidationMessage({ tone: 'error', text: `Enter altitude between ${TRAJECTORY_ALTITUDE_POLICY.MIN_MSL} and ${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL.` });
      return;
    }
    if (!Number.isFinite(timeFromStart) || timeFromStart < 0) {
      setValidationMessage({ tone: 'error', text: 'Enter a mission time of zero seconds or greater.' });
      return;
    }
    if (previousWaypoint && timingMode === TIMING_MODES.AUTO_SPEED && (!Number.isFinite(preferredSpeed)
        || preferredSpeed < TRAJECTORY_SPEED_POLICY.MIN_PREFERRED || preferredSpeed > TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX)) {
      setValidationMessage({ tone: 'error', text: `Enter speed between ${TRAJECTORY_SPEED_POLICY.MIN_PREFERRED} and ${TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX} m/s.` });
      return;
    }
    if (!Number.isFinite(heading)) {
      setValidationMessage({ tone: 'error', text: 'Enter a heading between 0° and 360°.' });
      return;
    }

    if (previousWaypoint && timeFromStart <= previousTime) {
      setValidationMessage({
        tone: 'error',
        text: `Waypoint arrival time must be later than the previous waypoint (${previousTime.toFixed(1)}s).`,
      });
      return;
    }

    const isUnderground = terrainResolved && altitude < groundElevation;

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
      terrainSource,
      terrainConfidence,
      terrainSampleTime,
      terrainError: terrainError || (isLoadingTerrain ? 'Terrain lookup pending.' : ''),
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
    const newAltitudeValue = e.target.value === '' ? '' : Number(e.target.value);
    setValidationMessage(null);
    if (altitudeReference === ALTITUDE_REFERENCE.AGL) {
      setTargetAgl(newAltitudeValue);
      if (terrainResolved && Number.isFinite(newAltitudeValue)) setAltitude(groundElevation + newAltitudeValue);
      else if (newAltitudeValue === '') setAltitude('');
      return;
    }
    setAltitude(newAltitudeValue);
  };

  const handleTimeChange = (e) => {
    const newTime = e.target.value === '' ? '' : Number(e.target.value);
    setValidationMessage(null);
    setTimeFromStart(newTime);
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
    const nextSpeed = e.target.value === '' ? '' : Number(e.target.value);
    setValidationMessage(null);
    setPreferredSpeed(nextSpeed);
  };

  const handleAltitudeReferenceChange = (newReference) => {
    setValidationMessage(null);
    if (newReference === ALTITUDE_REFERENCE.AGL && terrainResolved) {
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
    const newHeading = e.target.value === '' ? '' : Number(e.target.value);
    const normalizedHeading = newHeading === '' ? '' : normalizeHeading(newHeading);
    setValidationMessage(null);
    setHeading(normalizedHeading);
    
    // Switch to manual mode when user enters custom heading
    if (headingMode === YAW_CONSTANTS.AUTO) {
      setHeadingMode(YAW_CONSTANTS.MANUAL);
    }
  };

  const isUnderground = terrainResolved && Number.isFinite(altitude) && altitude < groundElevation;
  const aglAltitude = terrainResolved && Number.isFinite(altitude) ? Math.max(0, altitude - groundElevation) : targetAgl;
  const needsTerrainReview = terrainResolved && Number.isFinite(altitude) && needsTerrainSafetyAdjustment(altitude, groundElevation);
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
    <TrajectoryDialogPortal>
    <div className="waypoint-modal-overlay" onClick={handleCancel}>
      <div className="waypoint-modal" role="dialog" aria-modal="true" aria-labelledby="waypoint-modal-title" onClick={(e) => e.stopPropagation()}>
        <div className="waypoint-modal-header">
          <h3 id="waypoint-modal-title">Add Waypoint {waypointIndex}</h3>
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
              <label className="input-label--with-icon">
                <MdPlace aria-hidden="true" />
                <span>Coordinates</span>
              </label>
              <span>{position?.latitude?.toFixed(6)}, {position?.longitude?.toFixed(6)}</span>
            </div>
            
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
                </div>
              </div>
            )}

            {!isLoadingTerrain && terrainError && (
              <div className="wm-terrain-fallback-msg" role="status">
                <div>Terrain unavailable. MSL input remains available.</div>
                <button type="button" className="wm-terrain-skip-btn" onClick={() => setTerrainRetry((value) => value + 1)}>Retry terrain</button>
                {altitudeReference === ALTITUDE_REFERENCE.AGL && (
                  <button type="button" className="wm-terrain-skip-btn" onClick={() => handleAltitudeReferenceChange(ALTITUDE_REFERENCE.MSL)}>Use MSL input</button>
                )}
              </div>
            )}

            <div className="timing-mode-selector">
              <label className="input-label input-label--with-icon">
                <MdTerrain aria-hidden="true" />
                <span>Altitude Entry</span>
              </label>
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
              <label htmlFor="altitude" className="input-label input-label--with-icon">
                <MdTerrain aria-hidden="true" />
                <span>{altitudeReference === ALTITUDE_REFERENCE.AGL ? 'Target Clearance (AGL)' : 'Altitude (MSL)'}</span>
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
                  Ground elevation: <strong>{terrainResolved ? `${groundElevation.toFixed(1)}m MSL` : isLoadingTerrain ? 'resolving...' : 'unavailable'}</strong>
                </small>
                <small className="agl-note">
                  Above ground: <strong>{terrainResolved ? `${formatFieldNumber(aglAltitude)}m AGL` : 'unverified'}</strong>
                </small>
                <small className="agl-note">
                  Mission stores altitude as <strong>{altitudeReference === ALTITUDE_REFERENCE.AGL && !terrainResolved ? 'pending terrain' : `${formatFieldNumber(altitude)}m MSL`}</strong>
                </small>
                {!terrainResolved && altitudeReference === ALTITUDE_REFERENCE.AGL && (
                  <small className="terrain-warning">
                    AGL needs verified terrain. Use MSL input to continue without terrain.
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
                <label className="input-label input-label--with-icon">
                  <MdCalendarToday aria-hidden="true" />
                  <span>Leg Planning</span>
                </label>
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
              </div>
            )}

            <label htmlFor="timeFromStart" className="input-label input-label--with-icon">
              <MdTimer aria-hidden="true" />
              <span>
                {getTrajectoryDisplayedTimeFieldLabel({
                  isMissionAnchor: !previousWaypoint,
                  timingMode,
                })}
              </span>
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
              <div className="timing-summary" aria-label="Timing summary">
                <small className="time-calculation">
                  Leg duration: <strong>{legDuration.toFixed(1)}s</strong>
                </small>
              </div>
            )}
            {!previousWaypoint && (
              <div className="timing-summary" aria-label="Timing summary">
                <small className="time-calculation">Route entry at <strong>+{formatFieldNumber(timeFromStart)}s</strong></small>
              </div>
            )}
          </div>

          <div className="heading-section">
            <div className="heading-input-group">
              <label htmlFor="heading" className="input-label input-label--with-icon">
                <MdExplore aria-hidden="true" />
                <span>
                  {getTrajectoryDisplayedHeadingFieldLabel({
                    isMissionAnchor: !previousWaypoint,
                    headingMode,
                  })}
                </span>
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
              
            </div>
          </div>

          {previousWaypoint && (
            <div className="speed-section">
              <div className={`speed-display speed-display--${speedStatus || 'unknown'}`}>
                <div className="speed-header">
                  <span className="speed-label">
                    {timingMode === TIMING_MODES.AUTO_SPEED
                      ? getTrajectoryLegSpeedReviewLabel()
                      : getTrajectoryRequiredSpeedLabel()}
                  </span>
                  <span className="speed-value">{estimatedSpeed.toFixed(1)} m/s</span>
                </div>
                {['marginal', 'impossible'].includes(speedStatus) && (
                  <div className={`speed-warning speed-warning--${speedStatus}`}>
                    <MdWarningAmber aria-hidden="true" />
                    <span>{speedStatus === 'marginal' ? 'High speed - use caution' : 'Very high speed - review timing'}</span>
                  </div>
                )}
                <small className="speed-note">
                  From waypoint {waypointIndex - 1} to waypoint {waypointIndex}
                </small>
              </div>
            </div>
          )}

          <details className="waypoint-extra-details"><summary>Details</summary>
          <div className="waypoint-authoring-brief" aria-label="Waypoint authoring brief">
            {authoringCards.map((card) => (
              <div key={card.key} className={`waypoint-authoring-card waypoint-authoring-card--${card.tone}`}>
                <span className="waypoint-authoring-card__label">{card.label}</span>
                <strong className="waypoint-authoring-card__value">{card.value}</strong>
                <span className="waypoint-authoring-card__detail">{card.detail}</span>
              </div>
            ))}
          </div>
          </details>

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
            disabled={altitudeReference === ALTITUDE_REFERENCE.AGL && !terrainResolved}
          >
            Add Waypoint
          </button>
        </div>
      </div>
    </div>
    </TrajectoryDialogPortal>
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
