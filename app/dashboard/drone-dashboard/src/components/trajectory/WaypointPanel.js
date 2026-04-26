// src/components/trajectory/WaypointPanel.js

import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import {
  MdCheck,
  MdClose,
  MdDelete,
  MdExpandMore,
  MdLightbulb,
  MdList,
  MdLocationOn,
  MdWarningAmber,
} from 'react-icons/md';
import { 
  ALTITUDE_REFERENCE,
  getSpeedStatus, 
  suggestOptimalTime,
  TIMING_MODES,
  YAW_CONSTANTS,
  normalizeHeading,
  formatHeading 
} from '../../utilities/SpeedCalculator';
import {
  TRAJECTORY_ALTITUDE_POLICY,
  TRAJECTORY_SPEED_POLICY,
  TRAJECTORY_TIMING_POLICY,
  clampPreferredLegSpeed,
  getNominalPreferredLegSpeed,
} from '../../constants/trajectoryMissionPolicy';
import {
  buildTrajectoryCompactWaypointSummary,
  buildTrajectoryWaypointAuthoringCards,
  getTrajectoryAltitudeReferenceLabel,
  getTrajectoryAltitudeReferenceDescription,
  getTrajectoryDisplayedHeadingFieldDescription,
  getTrajectoryDisplayedHeadingFieldLabel,
  getTrajectoryLegSpeedReviewLabel,
  getTrajectoryDisplayedTimeFieldLabel,
  getTrajectoryHeadingModeDescription,
  getTrajectoryHeadingModeLabel,
  getTrajectoryMissionAnchorDescription,
  getTrajectoryMissionAnchorLabel,
  getTrajectoryPreferredSpeedLabel,
  getTrajectoryStoredAltitudeFieldDescription,
  getTrajectoryTerrainConfidenceDescription,
  getTrajectoryTerrainConfidenceLabel,
  getTrajectoryTimingModeDescription,
  getTrajectoryTimingModeLabel,
} from '../../utilities/trajectoryAuthoringGuidance';
import {
  formatTrajectoryDuration,
  getWaypointMissionClockSeconds,
  getWaypointRouteEntryDelaySeconds,
  getWaypointRouteMotionSeconds,
} from '../../utilities/trajectoryTimingPresentation';

const WaypointPanel = ({
  waypoints,
  selectedWaypointId,
  onSelectWaypoint,
  onUpdateWaypoint,
  onDeleteWaypoint,
  onMoveWaypoint,
  onFlyTo
}) => {
  // ENHANCED: Inline editing + panel collapse state management
  const [editingWaypointId, setEditingWaypointId] = useState(null);
  const [editValues, setEditValues] = useState({});
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const [editFeedback, setEditFeedback] = useState(null);
  const [isApplyingEdit, setIsApplyingEdit] = useState(false);
  const editInputRef = useRef(null);

  // Auto-focus when entering edit mode
  useEffect(() => {
    if (editingWaypointId && editInputRef.current) {
      editInputRef.current.focus();
      if (typeof editInputRef.current.select === 'function') {
        editInputRef.current.select();
      }
    }
  }, [editingWaypointId]);

  // Handle window resize for responsive behavior
  useEffect(() => {
    const handleResize = () => {
      const newIsMobile = window.innerWidth <= 768;
      setIsMobile(newIsMobile);
      
      // Auto-collapse on mobile if there are many waypoints
      if (newIsMobile && waypoints.length > 3) {
        setIsCollapsed(true);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [waypoints.length]);

  // Auto-collapse on mobile when waypoints increase
  useEffect(() => {
    if (isMobile && waypoints.length > 5) {
      setIsCollapsed(true);
    }
  }, [waypoints.length, isMobile]);

  if (!waypoints || waypoints.length === 0) {
    return (
      <div className="waypoint-panel">
        <div className="waypoint-panel-header">
          <h3>Waypoints</h3>
        </div>
        <p>No waypoints yet. Click on the map to add waypoints with custom altitude and timing.</p>
      </div>
    );
  }

  const handleEditStart = (waypoint, field) => {
    setEditFeedback(null);
    setEditingWaypointId(waypoint.id);
    setEditValues({
      field,
      latitude: waypoint.latitude,
      longitude: waypoint.longitude,
      altitude: waypoint.altitude,
      altitudeReference: waypoint.altitudeReference || ALTITUDE_REFERENCE.MSL,
      targetAgl: Number.isFinite(waypoint.targetAgl) && waypoint.targetAgl >= 0
        ? waypoint.targetAgl
        : (Number.isFinite(waypoint.groundElevation) ? Math.max(0, waypoint.altitude - waypoint.groundElevation) : 0),
      timeFromStart: waypoint.timeFromStart || waypoint.time || 0,
      timingMode: waypoint.timingMode || TIMING_MODES.MANUAL_TIME,
      preferredSpeed: waypoint.preferredSpeed || waypoint.estimatedSpeed || TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED,
      heading: waypoint.heading || waypoint.yaw || 0,
      headingMode: waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO
    });
  };

  const clearActiveEdit = () => {
    setEditingWaypointId(null);
    setEditValues({});
    setEditFeedback(null);
  };

  const isPromiseLike = (value) =>
    Boolean(value) && typeof value.then === 'function';

  const handleEditSave = async () => {
    if (!editingWaypointId || isApplyingEdit) return;

    const updates = {};
    const { field } = editValues;
    const waypointIndex = waypoints.findIndex((wp) => wp.id === editingWaypointId);
    const currentWaypoint = waypointIndex >= 0 ? waypoints[waypointIndex] : null;
    const prevWaypoint = waypointIndex > 0 ? waypoints[waypointIndex - 1] : null;
    const nextWaypoint = waypointIndex < waypoints.length - 1 ? waypoints[waypointIndex + 1] : null;

    // Validate and apply changes based on field type
    switch (field) {
      case 'coordinates':
        const lat = parseFloat(editValues.latitude);
        const lng = parseFloat(editValues.longitude);
        if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
          updates.latitude = lat;
          updates.longitude = lng;
        } else {
          setEditFeedback({
            tone: 'error',
            text: 'Coordinates must stay within valid latitude and longitude ranges.',
          });
          return;
        }
        break;
      
      case 'altitude':
        const alt = parseFloat(editValues.altitude);
        if (!isNaN(alt) && alt >= TRAJECTORY_ALTITUDE_POLICY.MIN_MSL && alt <= TRAJECTORY_ALTITUDE_POLICY.MAX_MSL) {
          updates.altitude = alt;
          if (
            currentWaypoint?.altitudeReference === ALTITUDE_REFERENCE.AGL &&
            Number.isFinite(currentWaypoint.groundElevation)
          ) {
            updates.targetAgl = Math.max(0, alt - currentWaypoint.groundElevation);
          }
        } else {
          setEditFeedback({
            tone: 'error',
            text: `Altitude must stay between ${TRAJECTORY_ALTITUDE_POLICY.MIN_MSL} m and ${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL.`,
          });
          return;
        }
        break;

      case 'altitudeReference':
        if (editValues.altitudeReference === ALTITUDE_REFERENCE.AGL) {
          if (!currentWaypoint || !Number.isFinite(currentWaypoint.groundElevation)) {
            setEditFeedback({
              tone: 'error',
              text: 'Terrain data is required before switching this waypoint to Target AGL.',
            });
            return;
          }

          updates.altitudeReference = ALTITUDE_REFERENCE.AGL;
          updates.targetAgl = Math.max(0, currentWaypoint.altitude - currentWaypoint.groundElevation);
        } else {
          updates.altitudeReference = ALTITUDE_REFERENCE.MSL;
          updates.targetAgl = 0;
        }
        break;

      case 'targetAgl': {
        if (!currentWaypoint || !Number.isFinite(currentWaypoint.groundElevation)) {
          setEditFeedback({
            tone: 'error',
            text: 'Terrain data is required before editing Target AGL for this waypoint.',
          });
          return;
        }

        const targetAgl = parseFloat(editValues.targetAgl);
        const derivedAltitude = currentWaypoint.groundElevation + targetAgl;

        if (!Number.isFinite(targetAgl) || targetAgl < 0) {
          setEditFeedback({
            tone: 'error',
            text: 'Target AGL must be zero or greater.',
          });
          return;
        }

        if (
          derivedAltitude < TRAJECTORY_ALTITUDE_POLICY.MIN_MSL ||
          derivedAltitude > TRAJECTORY_ALTITUDE_POLICY.MAX_MSL
        ) {
          setEditFeedback({
            tone: 'error',
            text: `Target AGL results in an altitude outside the ${TRAJECTORY_ALTITUDE_POLICY.MIN_MSL}-${TRAJECTORY_ALTITUDE_POLICY.MAX_MSL.toLocaleString()} m MSL envelope.`,
          });
          return;
        }

        updates.altitudeReference = ALTITUDE_REFERENCE.AGL;
        updates.targetAgl = targetAgl;
        updates.altitude = derivedAltitude;
        break;
      }
      
      case 'time':
        const time = parseFloat(editValues.timeFromStart);
        
        if ((currentWaypoint?.timingMode || TIMING_MODES.MANUAL_TIME) === TIMING_MODES.AUTO_SPEED) {
          setEditFeedback({
            tone: 'warning',
            text: 'This waypoint arrival time is derived from the preferred leg speed. Switch Timing Mode to Time-driven speed if you want to type a time.',
          });
          return;
        }

        if (!isNaN(time) && time >= 0) {
          // Validate time constraints
          if (prevWaypoint && time <= (prevWaypoint.timeFromStart || 0)) {
            setEditFeedback({
              tone: 'error',
              text: `Time must stay after waypoint ${waypointIndex} at ${(prevWaypoint.timeFromStart || 0)}s.`,
            });
            return;
          }
          if (nextWaypoint && time >= (nextWaypoint.timeFromStart || 0)) {
            setEditFeedback({
              tone: 'error',
              text: `Time must stay before waypoint ${waypointIndex + 2} at ${(nextWaypoint.timeFromStart || 0)}s.`,
            });
            return;
          }
          updates.timeFromStart = time;
          updates.time = time; // Export/storage alias for trajectory interchange.
        } else {
          setEditFeedback({
            tone: 'error',
            text: 'Time from start must be zero or greater.',
          });
          return;
        }
        break;

      case 'timingMode':
        const nextTimingMode = editValues.timingMode || TIMING_MODES.MANUAL_TIME;
        updates.timingMode = nextTimingMode;

        if (nextTimingMode === TIMING_MODES.AUTO_SPEED) {
          const legSpeed = Number.parseFloat(editValues.preferredSpeed);
          const normalizedSpeed = Number.isFinite(legSpeed)
            ? clampPreferredLegSpeed(legSpeed)
            : TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED;
          updates.preferredSpeed = normalizedSpeed;

          if (prevWaypoint && currentWaypoint) {
            const suggestedTime = suggestOptimalTime(
              prevWaypoint,
              currentWaypoint,
              normalizedSpeed,
              currentWaypoint.altitude
            );
            updates.timeFromStart = suggestedTime;
            updates.time = suggestedTime;
          }
        }
        break;

      case 'preferredSpeed':
        const preferredSpeed = Number.parseFloat(editValues.preferredSpeed);

        if (
          !Number.isFinite(preferredSpeed) ||
          preferredSpeed < TRAJECTORY_SPEED_POLICY.MIN_PREFERRED ||
          preferredSpeed > TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX
        ) {
          setEditFeedback({
            tone: 'error',
            text: `Preferred leg speed must stay between ${TRAJECTORY_SPEED_POLICY.MIN_PREFERRED} m/s and ${TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX} m/s.`,
          });
          return;
        }

        updates.preferredSpeed = preferredSpeed;
        updates.timingMode = TIMING_MODES.AUTO_SPEED;

        if (prevWaypoint && currentWaypoint) {
          const suggestedTime = suggestOptimalTime(
            prevWaypoint,
            currentWaypoint,
            preferredSpeed,
            currentWaypoint.altitude
          );
          updates.timeFromStart = suggestedTime;
          updates.time = suggestedTime;
        }
        break;
      
      case 'heading':
        const heading = parseFloat(editValues.heading);
        if (!isNaN(heading)) {
          const normalizedHeading = normalizeHeading(heading);
          updates.heading = normalizedHeading;
          // Switch to manual mode when heading is manually edited
          updates.headingMode = YAW_CONSTANTS.MANUAL;
        } else {
          setEditFeedback({
            tone: 'error',
            text: 'Heading must be a valid 0° to 360° value.',
          });
          return;
        }
        break;
      
      case 'headingMode':
        const newHeadingMode = editValues.headingMode;
        updates.headingMode = newHeadingMode;
        
        if (newHeadingMode === YAW_CONSTANTS.AUTO) {
          // When switching to auto, recalculate heading based on trajectory
          // This will be handled by the speed recalculation in the parent component
        }
        break;
      default:
        break;
    }

    if (field === 'coordinates') {
      setEditFeedback({
        tone: 'info',
        text: 'Refreshing terrain and clearance at the new coordinates...',
      });
    }

    const updateResult = onUpdateWaypoint(editingWaypointId, updates);

    if (!isPromiseLike(updateResult)) {
      clearActiveEdit();
      return;
    }

    try {
      setIsApplyingEdit(true);
      await updateResult;
      clearActiveEdit();
    } catch (error) {
      setEditFeedback({
        tone: 'error',
        text: error?.message || 'Unable to apply waypoint edit.',
      });
    } finally {
      setIsApplyingEdit(false);
    }
  };

  const handleEditCancel = () => {
    if (isApplyingEdit) {
      return;
    }
    clearActiveEdit();
  };

  const handleEditKeyPress = (e) => {
    if (isApplyingEdit) {
      return;
    }
    if (e.key === 'Enter') {
      handleEditSave();
    } else if (e.key === 'Escape') {
      handleEditCancel();
    }
  };

  // Get speed status indicator
  const getSpeedIndicator = (waypoint, index) => {
    if (index === 0) return null; // First waypoint has no speed requirement
    
    const speed = waypoint.estimatedSpeed || 0;
    const status = getSpeedStatus(speed);
    
    switch (status) {
      case 'feasible':
        return <MdCheck className="speed-indicator speed-feasible" data-help="Optimal speed" aria-hidden="true" />;
      case 'marginal':
        return <MdWarningAmber className="speed-indicator speed-marginal" data-help="High speed - use caution" aria-hidden="true" />;
      case 'impossible':
        return <MdWarningAmber className="speed-indicator speed-impossible" data-help="Speed too high for safe operation" aria-hidden="true" />;
      default:
        return null;
    }
  };

  // Format speed display
  const formatSpeed = (speed) => {
    if (!speed || speed === 0) return '0.0';
    return speed.toFixed(1);
  };

  // Format time display
  const formatTime = (timeFromStart) => (
    Number(timeFromStart || 0) < 60
      ? `${Number(timeFromStart || 0).toFixed(1)}s`
      : formatTrajectoryDuration(timeFromStart)
  );

  const missionClockSeconds = getWaypointMissionClockSeconds(waypoints);
  const routeEntryDelaySeconds = getWaypointRouteEntryDelaySeconds(waypoints);
  const routeMotionSeconds = getWaypointRouteMotionSeconds(waypoints);

  const getTimingMode = (waypoint) => waypoint.timingMode || TIMING_MODES.MANUAL_TIME;

  const getAltitudeReference = (waypoint) => waypoint.altitudeReference || ALTITUDE_REFERENCE.MSL;

  const hasGroundReference = (waypoint) => Number.isFinite(waypoint.groundElevation);

  const getTargetAgl = (waypoint) => {
    if (Number.isFinite(waypoint.targetAgl) && waypoint.targetAgl >= 0) {
      return waypoint.targetAgl;
    }
    if (hasGroundReference(waypoint)) {
      return Math.max(0, waypoint.altitude - waypoint.groundElevation);
    }
    return 0;
  };

  const getPreferredSpeed = (waypoint) => {
    if (Number.isFinite(waypoint.preferredSpeed) && waypoint.preferredSpeed > 0) {
      return waypoint.preferredSpeed;
    }
    if (Number.isFinite(waypoint.estimatedSpeed) && waypoint.estimatedSpeed > 0) {
      return waypoint.estimatedSpeed;
    }
    return getNominalPreferredLegSpeed(TRAJECTORY_SPEED_POLICY.DEFAULT_PREFERRED);
  };

  const buildIntentTags = (waypoint, index) => {
    const tags = [];
    tags.push({
      tone: getAltitudeReference(waypoint) === ALTITUDE_REFERENCE.AGL ? 'info' : 'neutral',
      text: getAltitudeReference(waypoint) === ALTITUDE_REFERENCE.AGL ? 'Target AGL' : 'MSL input',
      title: getTrajectoryAltitudeReferenceDescription(getAltitudeReference(waypoint)),
    });

    if (index > 0) {
      tags.push({
        tone: getTimingMode(waypoint) === TIMING_MODES.AUTO_SPEED ? 'info' : 'neutral',
        text: getTrajectoryTimingModeLabel(getTimingMode(waypoint)),
        title: getTrajectoryTimingModeDescription(getTimingMode(waypoint)),
      });
    } else {
      tags.push({
        tone: 'neutral',
        text: getTrajectoryMissionAnchorLabel(index),
        title: getTrajectoryMissionAnchorDescription(index),
      });
    }

    tags.push({
      tone: (waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO) === YAW_CONSTANTS.AUTO ? 'info' : 'neutral',
      text: getTrajectoryHeadingModeLabel(waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO),
      title: getTrajectoryHeadingModeDescription(
        waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO,
        { isMissionAnchor: index === 0 }
      ),
    });

    if (hasGroundReference(waypoint)) {
      tags.push({
        tone: waypoint.terrainAccurate === false ? 'warning' : 'success',
        text: getTrajectoryTerrainConfidenceLabel({
          terrainResolved: true,
          terrainAccurate: waypoint.terrainAccurate !== false,
        }),
        title: getTrajectoryTerrainConfidenceDescription({
          terrainResolved: true,
          terrainAccurate: waypoint.terrainAccurate !== false,
          groundElevation: waypoint.groundElevation,
        }),
      });
    }

    return tags;
  };

  const formatTimingMode = (waypoint) =>
    getTrajectoryTimingModeLabel(getTimingMode(waypoint));

  const showDerivedFieldNotice = (text) => {
    setEditFeedback({
      tone: 'info',
      text,
    });
  };

  const buildCompactWaypointSummary = (waypoint, index) => {
    return buildTrajectoryCompactWaypointSummary({
      altitudeReference: getAltitudeReference(waypoint),
      altitude: waypoint.altitude,
      targetAgl: getTargetAgl(waypoint),
      groundElevation: waypoint.groundElevation,
      terrainAccurate: waypoint.terrainAccurate !== false,
      isMissionAnchor: index === 0,
      timingMode: getTimingMode(waypoint),
      timeFromStart: waypoint.timeFromStart || waypoint.time || 0,
      preferredSpeed: getPreferredSpeed(waypoint),
      requiredSpeed: waypoint.estimatedSpeed || 0,
      headingMode:
        waypoint.headingMode || waypoint.yawMode || (index === 0 ? YAW_CONSTANTS.MANUAL : YAW_CONSTANTS.AUTO),
      heading: waypoint.heading || waypoint.yaw || 0,
      calculatedHeading: waypoint.calculatedHeading || waypoint.heading || waypoint.yaw || 0,
    });
  };

  const getWaypointAuthoringCards = (waypoint, index) =>
    buildTrajectoryWaypointAuthoringCards({
      altitudeReference: getAltitudeReference(waypoint),
      altitude: waypoint.altitude,
      targetAgl: getTargetAgl(waypoint),
      groundElevation: waypoint.groundElevation,
      isMissionAnchor: index === 0,
      timingMode: getTimingMode(waypoint),
      timeFromStart: waypoint.timeFromStart || waypoint.time || 0,
      preferredSpeed: getPreferredSpeed(waypoint),
      requiredSpeed: waypoint.estimatedSpeed || 0,
      speedStatus: getSpeedStatus(waypoint.estimatedSpeed || 0),
      headingMode:
        waypoint.headingMode || waypoint.yawMode || (index === 0 ? YAW_CONSTANTS.MANUAL : YAW_CONSTANTS.AUTO),
      heading: waypoint.heading || waypoint.yaw || 0,
      calculatedHeading: waypoint.calculatedHeading || waypoint.heading || waypoint.yaw || 0,
      includeTerrain: false,
    });

  const renderEditableField = (waypoint, field, value, displayValue) => {
    const isEditing = editingWaypointId === waypoint.id && editValues.field === field;
    const isMissionAnchor = waypoints[0]?.id === waypoint.id;
    
    if (isEditing) {
      if (field === 'coordinates') {
        return (
          <div className="edit-coordinates">
            <input
              ref={editInputRef}
              type="number"
              step="any"
              value={editValues.latitude}
              onChange={(e) => setEditValues(prev => ({ ...prev, latitude: e.target.value }))}
              onKeyDown={handleEditKeyPress}
              className="edit-input edit-input-small"
              placeholder="Latitude"
              disabled={isApplyingEdit}
            />
            <input
              type="number"
              step="any"
              value={editValues.longitude}
              onChange={(e) => setEditValues(prev => ({ ...prev, longitude: e.target.value }))}
              onKeyDown={handleEditKeyPress}
              className="edit-input edit-input-small"
              placeholder="Longitude"
              disabled={isApplyingEdit}
            />
            <div className="edit-buttons">
              <button onClick={handleEditSave} className="edit-btn save-btn" data-help="Save (Enter)" aria-label="Save edit" disabled={isApplyingEdit}><MdCheck aria-hidden="true" /></button>
              <button onClick={handleEditCancel} className="edit-btn cancel-btn" data-help="Cancel (Esc)" aria-label="Cancel edit" disabled={isApplyingEdit}><MdClose aria-hidden="true" /></button>
            </div>
          </div>
        );
      } else {
        if (field === 'headingMode' || field === 'timingMode' || field === 'altitudeReference') {
          return (
            <div className="edit-heading-mode">
              <select
                ref={editInputRef}
                value={
                  field === 'headingMode'
                    ? editValues.headingMode
                    : field === 'timingMode'
                      ? editValues.timingMode
                      : editValues.altitudeReference
                }
                onChange={(e) => setEditValues(prev => ({
                  ...prev,
                  [field === 'headingMode'
                    ? 'headingMode'
                    : field === 'timingMode'
                      ? 'timingMode'
                      : 'altitudeReference']: e.target.value
                }))}
                onKeyDown={handleEditKeyPress}
                className="edit-input edit-select"
                disabled={isApplyingEdit}
              >
                {field === 'headingMode' ? (
                  <>
                    <option value={YAW_CONSTANTS.AUTO}>Auto (arrival leg)</option>
                    <option value={YAW_CONSTANTS.MANUAL}>Manual</option>
                  </>
                ) : field === 'timingMode' ? (
                  <>
                    <option value={TIMING_MODES.AUTO_SPEED}>{getTrajectoryTimingModeLabel(TIMING_MODES.AUTO_SPEED)}</option>
                    <option value={TIMING_MODES.MANUAL_TIME}>{getTrajectoryTimingModeLabel(TIMING_MODES.MANUAL_TIME)}</option>
                  </>
                ) : (
                  <>
                    <option value={ALTITUDE_REFERENCE.MSL}>{getTrajectoryAltitudeReferenceLabel(ALTITUDE_REFERENCE.MSL)}</option>
                    <option value={ALTITUDE_REFERENCE.AGL}>{getTrajectoryAltitudeReferenceLabel(ALTITUDE_REFERENCE.AGL)}</option>
                  </>
                )}
              </select>
              <div className="edit-buttons">
                <button onClick={handleEditSave} className="edit-btn save-btn" data-help="Save (Enter)" aria-label="Save edit" disabled={isApplyingEdit}><MdCheck aria-hidden="true" /></button>
                <button onClick={handleEditCancel} className="edit-btn cancel-btn" data-help="Cancel (Esc)" aria-label="Cancel edit" disabled={isApplyingEdit}><MdClose aria-hidden="true" /></button>
              </div>
            </div>
          );
        } else {
          return (
            <div className="edit-single">
              <input
                ref={editInputRef}
                type="number"
                step={field === 'time' ? String(TRAJECTORY_TIMING_POLICY.DERIVED_TIME_STEP_S) : field === 'altitude' ? '1' : field === 'heading' ? '0.1' : field === 'preferredSpeed' ? String(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED) : field === 'targetAgl' ? '1' : 'any'}
                min={field === 'preferredSpeed' ? String(TRAJECTORY_SPEED_POLICY.MIN_PREFERRED) : field === 'heading' ? '0' : field === 'targetAgl' ? '0' : undefined}
                max={field === 'preferredSpeed' ? String(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX) : field === 'heading' ? '360' : undefined}
                value={editValues[
                  field === 'altitude'
                    ? 'altitude'
                    : field === 'time'
                      ? 'timeFromStart'
                      : field === 'heading'
                        ? 'heading'
                        : field === 'targetAgl'
                          ? 'targetAgl'
                          : field === 'preferredSpeed'
                          ? 'preferredSpeed'
                          : 'value'
                ]}
                onChange={(e) => setEditValues(prev => ({
                  ...prev,
                  [field === 'altitude'
                    ? 'altitude'
                    : field === 'time'
                      ? 'timeFromStart'
                      : field === 'heading'
                        ? 'heading'
                      : field === 'targetAgl'
                        ? 'targetAgl'
                      : field === 'preferredSpeed'
                          ? 'preferredSpeed'
                          : 'value']: e.target.value
                }))}
                onKeyDown={handleEditKeyPress}
                className="edit-input"
                disabled={isApplyingEdit}
                placeholder={
                  field === 'altitude' ? 'Altitude MSL (m)' : 
                  field === 'targetAgl' ? 'Target clearance AGL (m)' :
                  field === 'time' ? (isMissionAnchor ? 'Delay after mission start (s)' : 'Arrival time (s)') :
                  field === 'heading' ? 'Heading (0-360°)' :
                  field === 'preferredSpeed' ? 'Preferred speed (m/s)' : ''
                }
              />
              <div className="edit-buttons">
                <button onClick={handleEditSave} className="edit-btn save-btn" data-help="Save (Enter)" aria-label="Save edit" disabled={isApplyingEdit}><MdCheck aria-hidden="true" /></button>
                <button onClick={handleEditCancel} className="edit-btn cancel-btn" data-help="Cancel (Esc)" aria-label="Cancel edit" disabled={isApplyingEdit}><MdClose aria-hidden="true" /></button>
              </div>
            </div>
          );
        }
      }
    }

    return (
      <span 
        className="detail-value editable" 
        onClick={() => handleEditStart(waypoint, field)}
        data-help={field === 'coordinates' ? 'Click to edit. Coordinate changes refresh terrain and clearance.' : 'Click to edit'}
      >
        {displayValue}
      </span>
    );
  };

  return (
    <div className={`waypoint-panel ${isCollapsed ? 'collapsed' : 'expanded'} ${isMobile ? 'mobile' : 'desktop'}`}>
      <div className="waypoint-panel-header">
        <div className="header-title-section">
          <h3>Waypoints ({waypoints.length})</h3>
          {waypoints.some((wp) => wp.estimatedSpeed > TRAJECTORY_SPEED_POLICY.MARGINAL_MAX) && (
            <div className="speed-warning-summary">
              <MdWarningAmber className="speed-indicator speed-impossible" aria-hidden="true" />
              {!isCollapsed && <span className="warning-text">High speed detected</span>}
            </div>
          )}
        </div>
        <div className="panel-controls">
          <button
            className={`collapse-toggle ${isCollapsed ? 'collapsed' : 'expanded'}`}
            onClick={() => setIsCollapsed(!isCollapsed)}
            data-help={isCollapsed ? 'Expand waypoint panel' : 'Collapse waypoint panel'}
            aria-label={isCollapsed ? 'Expand waypoint panel' : 'Collapse waypoint panel'}
          >
            {isCollapsed ? <MdList aria-hidden="true" /> : <MdExpandMore aria-hidden="true" />}
          </button>
        </div>
      </div>
      
      {!isCollapsed && (
        <div className="waypoint-list">
          {editFeedback && (
            <div className={`waypoint-panel-feedback ${editFeedback.tone || 'info'}`} aria-live="polite">
              {editFeedback.text}
            </div>
          )}
          {waypoints.map((waypoint, index) => {
            const authoringCards = getWaypointAuthoringCards(waypoint, index);
            const isFocusedWaypoint = selectedWaypointId === waypoint.id || editingWaypointId === waypoint.id;

            return (
          <div 
            key={waypoint.id}
            className={`waypoint-item ${selectedWaypointId === waypoint.id ? 'selected' : ''} ${
              index > 0 && !waypoint.speedFeasible ? 'speed-warning' : ''
            } ${editingWaypointId === waypoint.id ? 'editing' : ''}`}
            onClick={() => editingWaypointId !== waypoint.id && onSelectWaypoint(waypoint.id)}
          >
            <div className="waypoint-header">
              <div className="waypoint-name-section">
                <strong>{waypoint.name}</strong>
                {index > 0 && getSpeedIndicator(waypoint, index)}
              </div>
              <div className="waypoint-actions">
                <button 
                  onClick={(e) => { e.stopPropagation(); onFlyTo(waypoint); }}
                  data-help="Fly to waypoint"
                  className="action-btn fly-btn"
                  disabled={editingWaypointId === waypoint.id}
                  aria-label={`Fly to ${waypoint.name}`}
                >
                  <MdLocationOn aria-hidden="true" />
                </button>
                <button 
                  onClick={(e) => { 
                    e.stopPropagation(); 
                    if (editingWaypointId === waypoint.id) {
                      handleEditCancel();
                    } else {
                      onDeleteWaypoint(waypoint.id); 
                    }
                  }}
                  data-help={editingWaypointId === waypoint.id ? "Cancel edit" : "Delete waypoint"}
                  className="action-btn delete-btn"
                  aria-label={editingWaypointId === waypoint.id ? `Cancel editing ${waypoint.name}` : `Delete ${waypoint.name}`}
                >
                  {editingWaypointId === waypoint.id ? <MdClose aria-hidden="true" /> : <MdDelete aria-hidden="true" />}
                </button>
              </div>
            </div>

            <div className="waypoint-intent-tags">
              {buildIntentTags(waypoint, index).map((tag) => (
                <span
                  key={`${waypoint.id}-${tag.text}`}
                  className={`waypoint-intent-tag waypoint-intent-tag--${tag.tone}`}
                  data-help={tag.title || tag.text}
                >
                  {tag.text}
                </span>
              ))}
            </div>

            {!isFocusedWaypoint ? (
              <div className="waypoint-compact-summary">
                <span className="waypoint-compact-summary__primary">
                  {buildCompactWaypointSummary(waypoint, index)}
                </span>
                <span className="waypoint-compact-summary__hint">
                  Select this waypoint to review or edit the full authoring details.
                </span>
              </div>
            ) : (
            <div className="waypoint-details">
              <div className="detail-row">
                <span className="detail-label">Position:</span>
                {renderEditableField(
                  waypoint, 
                  'coordinates', 
                  { lat: waypoint.latitude, lng: waypoint.longitude },
                  `${waypoint.latitude.toFixed(6)}, ${waypoint.longitude.toFixed(6)}`
                )}
              </div>
              
              <div className="detail-row">
                <span
                  className="detail-label"
                  data-help={getTrajectoryStoredAltitudeFieldDescription({
                    altitudeReference: getAltitudeReference(waypoint),
                  })}
                >
                  Stored Altitude (MSL):
                </span>
                {getAltitudeReference(waypoint) === ALTITUDE_REFERENCE.AGL ? (
                  <span
                    className="detail-value derived-value"
                    data-help={getTrajectoryStoredAltitudeFieldDescription({
                      altitudeReference: getAltitudeReference(waypoint),
                    })}
                    onClick={() => showDerivedFieldNotice(
                      getTrajectoryStoredAltitudeFieldDescription({
                        altitudeReference: getAltitudeReference(waypoint),
                      })
                    )}
                  >
                    {`${waypoint.altitude.toFixed(1)}m`}
                  </span>
                ) : renderEditableField(
                  waypoint,
                  'altitude',
                  waypoint.altitude,
                  `${waypoint.altitude.toFixed(1)}m`
                )}
              </div>

              <div className="detail-row timing-row">
                <span
                  className="detail-label"
                  data-help={getTrajectoryAltitudeReferenceDescription(getAltitudeReference(waypoint))}
                >
                  Altitude Entry:
                </span>
                {renderEditableField(
                  waypoint,
                  'altitudeReference',
                  getAltitudeReference(waypoint),
                  getTrajectoryAltitudeReferenceLabel(getAltitudeReference(waypoint))
                )}
              </div>

              {hasGroundReference(waypoint) || getTargetAgl(waypoint) > 0 ? (
                <>
                  {hasGroundReference(waypoint) && (
                    <div className="detail-row timing-row">
                      <span
                        className="detail-label"
                        data-help={getTrajectoryTerrainConfidenceDescription({
                          terrainResolved: true,
                          terrainAccurate: waypoint.terrainAccurate !== false,
                          groundElevation: waypoint.groundElevation,
                        })}
                      >
                        Terrain:
                      </span>
                      <span className="detail-value">
                        {`${getTrajectoryTerrainConfidenceLabel({
                          terrainResolved: true,
                          terrainAccurate: waypoint.terrainAccurate !== false,
                        })} • ${waypoint.groundElevation.toFixed(1)}m MSL`}
                      </span>
                    </div>
                  )}
                  <div className="detail-row timing-row">
                    <span className="detail-label">Clearance AGL:</span>
                    {getAltitudeReference(waypoint) === ALTITUDE_REFERENCE.AGL && hasGroundReference(waypoint) ? (
                      renderEditableField(
                        waypoint,
                        'targetAgl',
                        getTargetAgl(waypoint),
                        `${getTargetAgl(waypoint).toFixed(1)}m`
                      )
                    ) : (
                      <span className="detail-value">
                        {getTargetAgl(waypoint).toFixed(1)}m
                      </span>
                    )}
                  </div>
                </>
              ) : null}

              <div className="detail-row">
                <span
                  className="detail-label"
                  data-help={index === 0
                    ? getTrajectoryMissionAnchorDescription(index)
                    : getTrajectoryTimingModeDescription(getTimingMode(waypoint))}
                >
                  {`${getTrajectoryDisplayedTimeFieldLabel({
                    isMissionAnchor: index === 0,
                    timingMode: getTimingMode(waypoint),
                  })}:`}
                </span>
                {getTimingMode(waypoint) === TIMING_MODES.AUTO_SPEED ? (
                  <span
                    className="detail-value derived-value"
                    data-help="Derived from the leg speed target. Edit Timing Mode or Preferred Leg Speed to change it."
                    onClick={() => showDerivedFieldNotice(
                      'Waypoint arrival time is derived from the preferred leg speed in Speed-driven ETA mode. Switch Timing Mode to Time-driven speed if you want to type an arrival time directly.'
                    )}
                  >
                    {formatTime(waypoint.timeFromStart || waypoint.time || 0)}
                  </span>
                ) : (
                  renderEditableField(
                    waypoint,
                    'time',
                    waypoint.timeFromStart || waypoint.time || 0,
                    formatTime(waypoint.timeFromStart || waypoint.time || 0)
                  )
                )}
              </div>

              {index > 0 && (
                <div className="detail-row timing-row">
                  <span
                    className="detail-label"
                    data-help={getTrajectoryTimingModeDescription(getTimingMode(waypoint))}
                  >
                    Leg Planning:
                  </span>
                  <div className="timing-display">
                    {renderEditableField(
                      waypoint,
                      'timingMode',
                      getTimingMode(waypoint),
                      formatTimingMode(waypoint)
                    )}
                  </div>
                </div>
              )}

              {index === 0 && (
                <div className="detail-row start-point">
                  <span className="detail-label">Route Role:</span>
                  <span
                    className="detail-value start-indicator"
                    data-help={getTrajectoryMissionAnchorDescription(index)}
                  >
                    {getTrajectoryMissionAnchorLabel(index)}
                  </span>
                </div>
              )}

              {index > 0 && getTimingMode(waypoint) === TIMING_MODES.AUTO_SPEED && (
                <div className="detail-row timing-row">
                  <span className="detail-label">{`${getTrajectoryPreferredSpeedLabel()}:`}</span>
                  {renderEditableField(
                    waypoint,
                    'preferredSpeed',
                    getPreferredSpeed(waypoint),
                    `${getPreferredSpeed(waypoint).toFixed(1)}m/s`
                  )}
                </div>
              )}
              
              {index > 0 && (
                <div className="detail-row speed-row">
                  <span className="detail-label">{`${getTrajectoryLegSpeedReviewLabel()}:`}</span>
                  <div className="speed-display">
                    <span className={`detail-value speed-value speed-${getSpeedStatus(waypoint.estimatedSpeed || 0)}`}>
                      {formatSpeed(waypoint.estimatedSpeed)}m/s
                    </span>
                    {waypoint.estimatedSpeed > TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX && (
                      <span className="speed-warning-text">
                        ({(waypoint.estimatedSpeed * 3.6).toFixed(1)} km/h)
                      </span>
                    )}
                  </div>
                </div>
              )}

              {index > 0 && getSpeedStatus(waypoint.estimatedSpeed || 0) !== 'feasible' ? (
                <div className="detail-row timing-row">
                  <span className="detail-label">Leg Review:</span>
                  <span className={`detail-value speed-review speed-review--${getSpeedStatus(waypoint.estimatedSpeed || 0)}`}>
                    {getSpeedStatus(waypoint.estimatedSpeed || 0) === 'marginal'
                      ? 'Review timing or spacing before launch'
                      : 'Outside nominal envelope; adjust timing before launch'}
                  </span>
                </div>
              ) : null}
              
              <div className="detail-row heading-row">
                <span
                  className="detail-label"
                  data-help={getTrajectoryHeadingModeDescription(
                    index === 0
                      ? YAW_CONSTANTS.MANUAL
                      : waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO,
                    { isMissionAnchor: index === 0 }
                  )}
                >
                  {`${getTrajectoryDisplayedHeadingFieldLabel({
                    isMissionAnchor: index === 0,
                    headingMode: index === 0
                      ? YAW_CONSTANTS.MANUAL
                      : waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO,
                  })}:`}
                </span>
                <div className="heading-display">
                  {index > 0 && (waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO) === YAW_CONSTANTS.AUTO ? (
                    <span
                      className="detail-value derived-value"
                      data-help={getTrajectoryDisplayedHeadingFieldDescription({
                        isMissionAnchor: false,
                        headingMode: YAW_CONSTANTS.AUTO,
                      })}
                      onClick={() => showDerivedFieldNotice(
                        getTrajectoryDisplayedHeadingFieldDescription({
                          isMissionAnchor: false,
                          headingMode: YAW_CONSTANTS.AUTO,
                        })
                      )}
                    >
                      {formatHeading(waypoint.heading || waypoint.yaw || 0)}
                    </span>
                  ) : renderEditableField(
                    waypoint,
                    'heading',
                    waypoint.heading || waypoint.yaw || 0,
                    formatHeading(waypoint.heading || waypoint.yaw || 0)
                  )}
                  <span
                    className="heading-mode-indicator"
                    data-help={getTrajectoryHeadingModeDescription(
                      index === 0
                        ? YAW_CONSTANTS.MANUAL
                        : waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO,
                      { isMissionAnchor: index === 0 }
                    )}
                  >
                    ({index === 0
                      ? getTrajectoryHeadingModeLabel(YAW_CONSTANTS.MANUAL)
                      : renderEditableField(
                        waypoint,
                        'headingMode',
                        waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO,
                        getTrajectoryHeadingModeLabel(waypoint.headingMode || waypoint.yawMode || YAW_CONSTANTS.AUTO)
                    )})
                  </span>
                </div>
              </div>

              {index === waypoints.length - 1 && waypoints.length > 1 && (
                <div className="detail-row end-point">
                  <span className="detail-label">Type:</span>
                  <span className="detail-value end-indicator">End Point</span>
                </div>
              )}

              <div className="waypoint-brief-grid" aria-label={`${waypoint.name} operator brief`}>
                {authoringCards.map((card) => (
                  <div
                    key={`${waypoint.id}-${card.key}`}
                    className={`waypoint-brief-card waypoint-brief-card--${card.tone}`}
                    data-help={card.detail}
                  >
                    <span className="waypoint-brief-card__label">{card.label}</span>
                    <strong className="waypoint-brief-card__value">{card.value}</strong>
                    <span className="waypoint-brief-card__detail">{card.detail}</span>
                  </div>
                ))}
              </div>
            </div>
            )}
            
            {/* Speed warning for high-speed segments */}
            {index > 0 && waypoint.estimatedSpeed > TRAJECTORY_SPEED_POLICY.MARGINAL_MAX && (
              <div className="waypoint-speed-warning">
                <MdWarningAmber aria-hidden="true" />
                <small>High speed segment - verify drone capabilities</small>
              </div>
            )}

            {editingWaypointId === waypoint.id && (
              <div className="edit-help">
                <small>Press Enter to save, Escape to cancel</small>
              </div>
            )}
          </div>
            );
          })}
        </div>
      )}
      
      {/* Summary statistics - always show for quick reference */}
      {waypoints.length > 1 && (
        <div className={`waypoint-summary ${isCollapsed ? 'collapsed' : 'expanded'}`}>
          <div className="summary-item">
            <span className="summary-label">{isCollapsed ? 'Pts:' : 'Total Points:'}</span>
            <span className="summary-value">{waypoints.length}</span>
          </div>
          
          <div className="summary-item">
            <span className="summary-label">{isCollapsed ? 'Clock:' : 'Mission clock:'}</span>
            <span className="summary-value">
              {formatTime(missionClockSeconds)}
            </span>
          </div>
          
          {!isCollapsed && (
            <>
              <div className="summary-item">
                <span className="summary-label">Route entry:</span>
                <span className="summary-value">
                  {formatTime(routeEntryDelaySeconds)}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Route motion:</span>
                <span className="summary-value">
                  {formatTime(routeMotionSeconds)}
                </span>
              </div>

              <div className="summary-item">
                <span className="summary-label">Max Speed:</span>
                <span className="summary-value">
                  {Math.max(...waypoints.slice(1).map(wp => wp.estimatedSpeed || 0)).toFixed(1)}m/s
                </span>
              </div>
              
              <div className="summary-item">
                <span className="summary-label">Max Alt MSL:</span>
                <span className="summary-value">
                  {Math.max(...waypoints.map(wp => wp.altitude)).toFixed(1)}m
                </span>
              </div>
            </>
          )}
        </div>
      )}

      {/* Enhanced instructions - responsive */}
      {waypoints.length > 0 && !editingWaypointId && !isCollapsed && (
        <div className="edit-instructions">
          <small>
            <MdLightbulb aria-hidden="true" />
            <span>{isMobile ? 'Tap editable values to change operator-owned inputs' : 'Click editable values to change operator-owned inputs inline'}.</span>
            {' '}Derived timing and speed checks stay locked so the panel always shows what the planner is calculating.
            {!isMobile && ' Drag waypoints on map to reposition.'}
          </small>
        </div>
      )}
    </div>
  );
};

WaypointPanel.propTypes = {
  waypoints: PropTypes.array.isRequired,
  selectedWaypointId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onSelectWaypoint: PropTypes.func.isRequired,
  onUpdateWaypoint: PropTypes.func.isRequired,
  onDeleteWaypoint: PropTypes.func.isRequired,
  onMoveWaypoint: PropTypes.func.isRequired,
  onFlyTo: PropTypes.func.isRequired,
};

export default WaypointPanel;
