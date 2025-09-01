// src/components/trajectory/WaypointModal.js
// PHASE 3 ENHANCEMENTS: Auto-elevation estimation, speed as cautions only

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { calculateSpeed, validateSpeed, getSpeedStatus } from '../../utilities/SpeedCalculator';
import '../../styles/WaypointModal.css';

/**
 * PHASE 3: Basic elevation estimation matching main component
 */
const estimateGroundElevation = (latitude, longitude) => {
  // Mountain ranges (rough approximation)
  const mountainRanges = [
    { lat: [25, 50], lng: [-125, -100], elevation: 1500 }, // Rocky Mountains
    { lat: [35, 70], lng: [60, 150], elevation: 2000 },    // Asian mountains  
    { lat: [40, 50], lng: [-10, 50], elevation: 800 },     // European mountains
    { lat: [25, 45], lng: [35, 60], elevation: 1200 },     // Middle East mountains
  ];

  // Check if location is in a mountain range
  for (const range of mountainRanges) {
    if (latitude >= range.lat[0] && latitude <= range.lat[1] &&
        longitude >= range.lng[0] && longitude <= range.lng[1]) {
      return range.elevation;
    }
  }

  // Polar regions
  if (latitude > 60 || latitude < -60) {
    return 200;
  }
  
  // Tropical/equatorial regions
  if (Math.abs(latitude) < 30) {
    return 50;
  }

  // Coastal proximity detection
  const coastalProximity = Math.min(
    Math.abs(longitude % 180), 
    Math.abs(latitude % 90)
  );
  if (coastalProximity < 5) {
    return 10;
  }

  // Default continental elevation
  return 150;
};

const WaypointModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  position,
  previousWaypoint,
  waypointIndex 
}) => {
  // PHASE 3: Enhanced state management
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [showElevationInfo, setShowElevationInfo] = useState(false);
  
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

  // PHASE 3: Auto-estimate elevation when position changes
  useEffect(() => {
    if (isOpen && position) {
      const estimatedGround = estimateGroundElevation(position.latitude, position.longitude);
      setGroundElevation(estimatedGround);
      
      // Set altitude to ground + 100m MSL
      const suggestedAltitude = estimatedGround + 100;
      setAltitude(suggestedAltitude);
      
      console.info(`Auto-estimated: Ground ${estimatedGround}m MSL, Suggested altitude ${suggestedAltitude}m MSL`);
    }
  }, [isOpen, position]);

  // Real-time speed calculation
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
    // PHASE 3: Basic validation only - no blocking for speed
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

    // PHASE 3: Show speed warnings but don't block
    if (estimatedSpeed > 20) {
      const proceed = window.confirm(
        `⚠️ Speed Warning: ${estimatedSpeed.toFixed(1)} m/s (${(estimatedSpeed * 3.6).toFixed(1)} km/h)\n\n` +
        `This is a high speed that may exceed typical drone capabilities.\n` +
        `Consider increasing flight time for safety.\n\n` +
        `Proceed anyway?`
      );
      if (!proceed) return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed: estimatedSpeed,
      speedFeasible: true, // PHASE 3: Always true, speeds are cautions only
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
    setShowElevationInfo(false);
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
      case 'feasible': return 'Optimal speed range';
      case 'marginal': return 'High speed - caution advised';
      case 'impossible': return 'Very high speed - verify drone capabilities';
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
          {/* Location info with coordinates */}
          <div className="waypoint-location-info">
            <div className="location-item">
              <label>Latitude</label>
              <span>{position?.latitude?.toFixed(6) || 'N/A'}</span>
            </div>
            <div className="location-item">
              <label>Longitude</label>
              <span>{position?.longitude?.toFixed(6) || 'N/A'}</span>
            </div>
          </div>

          {/* PHASE 3: Enhanced altitude input with auto-estimation */}
          <div className="waypoint-input-group">
            <label htmlFor="altitude">
              Altitude MSL (meters above sea level)
              <button 
                type="button"
                className="info-toggle"
                onClick={() => setShowElevationInfo(!showElevationInfo)}
                title="Show elevation information"
              >
                ℹ️
              </button>
            </label>
            <input
              id="altitude"
              ref={altitudeRef}
              type="number"
              min="0"
              max="10000"
              step="1"
              value={altitude}
              onChange={(e) => setAltitude(parseFloat(e.target.value) || 0)}
              className="waypoint-input"
              placeholder="Enter MSL altitude"
            />
            
            {/* PHASE 3: Elevation information display */}
            {showElevationInfo && (
              <div className="elevation-info">
                <div className="elevation-item">
                  <label>Estimated Ground:</label>
                  <span>{groundElevation}m MSL</span>
                  <small className="estimate-badge">estimated</small>
                </div>
                <div className="elevation-item">
                  <label>Above Ground (AGL):</label>
                  <span>{Math.max(0, altitude - groundElevation)}m</span>
                </div>
                <div className="elevation-note">
                  <small>
                    💡 Auto-estimated to ground elevation + 100m for safety clearance.
                    Full terrain integration coming soon for precise AGL/MSL conversion.
                  </small>
                </div>
              </div>
            )}

            <div className="input-hint">
              MSL = Mean Sea Level (absolute altitude from sea level)
            </div>
          </div>

          {/* Time input */}
          <div className="waypoint-input-group">
            <label htmlFor="time">
              Time from mission start (seconds)
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
              placeholder="Enter time from mission start"
            />
            <div className="input-hint">
              Time when drone should reach this waypoint
            </div>
          </div>

          {/* PHASE 3: Speed calculation display - caution mode */}
          {estimatedSpeed > 0 && (
            <div className="speed-calculation">
              <div className="speed-header">
                <label>Estimated Speed Required:</label>
                <div className={`speed-indicator ${getSpeedIndicatorClass()}`}>
                  {estimatedSpeed.toFixed(1)} m/s
                </div>
              </div>
              <div className={`speed-status ${speedStatus} caution-mode`}>
                {getSpeedMessage()}
              </div>
              
              {/* PHASE 3: Speed guidance instead of blocking warnings */}
              {estimatedSpeed > 20 && (
                <div className="speed-guidance">
                  <div className="guidance-header">⚠️ High Speed Guidance:</div>
                  <ul className="guidance-list">
                    <li>Verify drone maximum speed capabilities</li>
                    <li>Consider increasing flight time for safety</li>
                    <li>Check regulatory speed limits for area</li>
                    <li>Ensure adequate battery capacity</li>
                  </ul>
                </div>
              )}

              {estimatedSpeed > 15 && (
                <div className="speed-conversion">
                  ≈ {(estimatedSpeed * 3.6).toFixed(1)} km/h 
                  {estimatedSpeed > 12 && <span className="caution-note">(Above typical cruise speed)</span>}
                </div>
              )}
            </div>
          )}

          {/* PHASE 3: Enhanced altitude guidance */}
          <div className="altitude-guidance">
            <h4>💡 Altitude Guidelines</h4>
            <div className="guidance-content">
              <div className="guidance-item">
                <span className="guidance-icon">📐</span>
                <div className="guidance-text">
                  <strong>MSL (Mean Sea Level)</strong>: Absolute altitude from sea level - used for navigation and air traffic
                </div>
              </div>
              <div className="guidance-item">
                <span className="guidance-icon">🏔️</span>
                <div className="guidance-text">
                  <strong>AGL (Above Ground)</strong>: Height relative to local terrain - used for obstacle clearance
                </div>
              </div>
              <div className="guidance-item">
                <span className="guidance-icon">🚧</span>
                <div className="guidance-text">
                  <strong>Coming Soon</strong>: Real terrain data for automatic AGL/MSL conversion
                </div>
              </div>
              <div className="guidance-item">
                <span className="guidance-icon">⚠️</span>
                <div className="guidance-text">
                  Always verify local regulations and ensure adequate terrain clearance
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="waypoint-modal-footer">
          <button 
            className="modal-btn modal-btn-cancel"
            onClick={handleCancel}
          >
            Cancel (Esc)
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
            Add Waypoint (Ctrl+Enter)
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