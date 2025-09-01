// src/components/trajectory/WaypointModal.js
// PHASE 3.1 FIX: Simplified, clean altitude interface - MSL only

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { calculateSpeed, getSpeedStatus } from '../../utilities/SpeedCalculator';
import '../../styles/WaypointModal.css';

/**
 * PHASE 3.1: Simplified elevation estimation
 */
const estimateGroundElevation = (latitude, longitude) => {
  // Mountain ranges
  const mountainRanges = [
    { lat: [25, 50], lng: [-125, -100], elevation: 1500 }, // Rocky Mountains
    { lat: [35, 70], lng: [60, 150], elevation: 2000 },    // Asian mountains  
    { lat: [40, 50], lng: [-10, 50], elevation: 800 },     // European mountains
    { lat: [25, 45], lng: [35, 60], elevation: 1200 },     // Middle East mountains
  ];

  for (const range of mountainRanges) {
    if (latitude >= range.lat[0] && latitude <= range.lat[1] &&
        longitude >= range.lng[0] && longitude <= range.lng[1]) {
      return range.elevation;
    }
  }

  if (latitude > 60 || latitude < -60) return 200; // Polar regions
  if (Math.abs(latitude) < 30) return 50; // Tropical regions
  
  const coastalProximity = Math.min(Math.abs(longitude % 180), Math.abs(latitude % 90));
  if (coastalProximity < 5) return 10; // Coastal areas

  return 150; // Default continental elevation
};

const WaypointModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  position,
  previousWaypoint,
  waypointIndex 
}) => {
  // PHASE 3.1: Simplified state - clean and focused
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [isUnderground, setIsUnderground] = useState(false);
  
  const altitudeRef = useRef(null);
  const modalRef = useRef(null);

  // Auto-focus altitude input when modal opens
  useEffect(() => {
    if (isOpen && altitudeRef.current) {
      altitudeRef.current.focus();
      altitudeRef.current.select();
    }
  }, [isOpen]);

  // Calculate default time
  useEffect(() => {
    if (isOpen) {
      const defaultTime = previousWaypoint ? (previousWaypoint.timeFromStart || 0) + 10 : 10;
      setTimeFromStart(defaultTime);
    }
  }, [isOpen, previousWaypoint]);

  // PHASE 3.1: Simplified auto-altitude calculation
  useEffect(() => {
    if (isOpen && position) {
      const estimatedGround = estimateGroundElevation(position.latitude, position.longitude);
      setGroundElevation(estimatedGround);
      
      // PHASE 3.1 FIX: Smart altitude defaults
      let suggestedAltitude;
      if (waypointIndex === 0) {
        // First waypoint: ground + 100m
        suggestedAltitude = estimatedGround + 100;
      } else if (previousWaypoint) {
        // Subsequent waypoints: use last waypoint altitude as starting point
        suggestedAltitude = previousWaypoint.altitude;
      } else {
        // Fallback
        suggestedAltitude = estimatedGround + 100;
      }
      
      setAltitude(suggestedAltitude);
    }
  }, [isOpen, position, waypointIndex, previousWaypoint]);

  // PHASE 3.1: Check if altitude is underground
  useEffect(() => {
    const underground = altitude < groundElevation;
    setIsUnderground(underground);
  }, [altitude, groundElevation]);

  // Real-time speed calculation (for next waypoint)
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

  // Handle keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!isOpen) return;
      
      if (e.key === 'Escape') {
        handleCancel();
      } else if (e.key === 'Enter' && e.ctrlKey) {
        handleConfirm();
      }
    };

    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, altitude, timeFromStart]);

  const handleConfirm = () => {
    // Basic validation only
    if (altitude < 0) {
      alert('MSL altitude cannot be negative');
      return;
    }

    if (altitude > 10000) {
      alert('MSL altitude exceeds reasonable flight ceiling (10km)');
      return;
    }

    if (previousWaypoint && timeFromStart <= (previousWaypoint.timeFromStart || 0)) {
      alert('Time must be greater than previous waypoint time');
      return;
    }

    // Show speed warnings but don't block
    if (estimatedSpeed > 20) {
      const proceed = window.confirm(
        `High Speed Warning: ${estimatedSpeed.toFixed(1)} m/s (${(estimatedSpeed * 3.6).toFixed(1)} km/h)\n\n` +
        `This may exceed typical drone capabilities.\n` +
        `Consider increasing flight time for safety.\n\n` +
        `Continue anyway?`
      );
      if (!proceed) return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed: estimatedSpeed,
      speedFeasible: true,
      terrainInfo: {
        groundElevation: groundElevation,
        estimatedTerrain: true,
        altitudeAGL: Math.max(0, altitude - groundElevation)
      }
    };

    onConfirm(waypointData);
    handleReset();
  };

  const handleCancel = () => {
    onClose();
    handleReset();
  };

  const handleReset = () => {
    setAltitude(100);
    setTimeFromStart(0);
    setEstimatedSpeed(0);
    setSpeedStatus('unknown');
    setGroundElevation(0);
    setIsUnderground(false);
  };

  // Handle backdrop click
  const handleBackdropClick = (e) => {
    if (e.target === modalRef.current) {
      handleCancel();
    }
  };

  if (!isOpen) return null;

  const getSpeedIndicatorClass = () => {
    switch (speedStatus) {
      case 'feasible': return 'speed-indicator-green';
      case 'marginal': return 'speed-indicator-yellow';
      case 'impossible': return 'speed-indicator-red';
      default: return 'speed-indicator-gray';
    }
  };

  const getSpeedMessage = () => {
    switch (speedStatus) {
      case 'feasible': return 'Good speed';
      case 'marginal': return 'High speed - caution';
      case 'impossible': return 'Very high speed - verify capabilities';
      default: return 'Calculating...';
    }
  };

  return (
    <div 
      className="waypoint-modal-overlay" 
      ref={modalRef}
      onClick={handleBackdropClick}
    >
      <div className="waypoint-modal">
        <div className="waypoint-modal-header">
          <h3>Add Waypoint {waypointIndex + 1}</h3>
          <button 
            className="waypoint-modal-close"
            onClick={handleCancel}
            aria-label="Close"
          >
            ×
          </button>
        </div>

        <div className="waypoint-modal-body">
          {/* PHASE 3.1: Clean location display */}
          <div className="waypoint-location-info">
            <div className="location-item">
              <label>Location</label>
              <span>{position?.latitude?.toFixed(4)}, {position?.longitude?.toFixed(4)}</span>
            </div>
          </div>

          {/* PHASE 3.1: Simplified altitude input */}
          <div className="waypoint-input-group">
            <label htmlFor="altitude">Altitude MSL (meters)</label>
            <div className="altitude-input-container">
              <input
                id="altitude"
                ref={altitudeRef}
                type="number"
                min="0"
                max="10000"
                step="1"
                value={altitude}
                onChange={(e) => setAltitude(parseFloat(e.target.value) || 0)}
                className={`waypoint-input ${isUnderground ? 'underground-warning' : ''}`}
                placeholder="Enter MSL altitude"
              />
              
              {/* PHASE 3.1: Simple elevation info near field */}
              <div className="elevation-info-inline">
                Ground: {groundElevation}m MSL
                {isUnderground && (
                  <span className="underground-alert">
                    ⚠ Underground - altitude below estimated ground level
                  </span>
                )}
              </div>
            </div>

            {/* PHASE 3.1: Clean guidance */}
            <div className="input-hint">
              MSL = Mean Sea Level. Current altitude above ground: {Math.max(0, altitude - groundElevation)}m
            </div>

            {/* PHASE 3.1: Underground warning */}
            {isUnderground && (
              <div className="underground-guidance">
                <strong>⚠ Warning:</strong> This altitude is below estimated ground level.
                <br />Consider increasing altitude for safe terrain clearance.
              </div>
            )}
          </div>

          {/* Time input */}
          <div className="waypoint-input-group">
            <label htmlFor="time">
              Time from start (seconds)
              {previousWaypoint && (
                <span className="time-constraint">
                  &gt; {(previousWaypoint.timeFromStart || 0).toFixed(1)}s
                </span>
              )}
            </label>
            <input
              id="time"
              type="number"
              min={previousWaypoint ? (previousWaypoint.timeFromStart || 0) + 0.1 : 0.1}
              max="3600"
              step="0.1"
              value={timeFromStart}
              onChange={(e) => setTimeFromStart(parseFloat(e.target.value) || 0)}
              className="waypoint-input"
              placeholder="Mission time"
            />
          </div>

          {/* PHASE 3.1: Simplified speed display */}
          {estimatedSpeed > 0 && (
            <div className="speed-calculation-simple">
              <div className="speed-display-simple">
                <label>Speed to this waypoint:</label>
                <span className={`speed-value ${getSpeedIndicatorClass()}`}>
                  {estimatedSpeed.toFixed(1)} m/s
                </span>
                <span className="speed-status-simple">({getSpeedMessage()})</span>
              </div>
              
              {estimatedSpeed > 15 && (
                <div className="speed-note">
                  ≈ {(estimatedSpeed * 3.6).toFixed(1)} km/h
                  {estimatedSpeed > 20 && <span className="high-speed-note"> - High speed, verify drone limits</span>}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="waypoint-modal-footer">
          <button 
            className="modal-btn modal-btn-cancel"
            onClick={handleCancel}
          >
            Cancel
          </button>
          <button 
            className="modal-btn modal-btn-confirm"
            onClick={handleConfirm}
            disabled={
              altitude < 0 || 
              altitude > 10000 || 
              (previousWaypoint && timeFromStart <= (previousWaypoint.timeFromStart || 0))
            }
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
    longitude: PropTypes.number.isRequired
  }),
  previousWaypoint: PropTypes.object,
  waypointIndex: PropTypes.number.isRequired
};

export default WaypointModal;