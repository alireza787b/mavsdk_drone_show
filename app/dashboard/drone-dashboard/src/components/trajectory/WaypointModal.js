// src/components/trajectory/WaypointModal.js
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { calculateSpeed, validateSpeed, getSpeedStatus } from '../../utilities/SpeedCalculator';
import '../../styles/WaypointModal.css';

const WaypointModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  position,
  previousWaypoint,
  waypointIndex 
}) => {
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  
  const altitudeRef = useRef(null);
  const modalRef = useRef(null);

  // Auto-focus altitude input when modal opens
  useEffect(() => {
    if (isOpen && altitudeRef.current) {
      altitudeRef.current.focus();
      altitudeRef.current.select();
    }
  }, [isOpen]);

  // Calculate default time (10 seconds after previous waypoint or 10s for first)
  useEffect(() => {
    if (isOpen) {
      const defaultTime = previousWaypoint ? (previousWaypoint.timeFromStart || 0) + 10 : 10;
      setTimeFromStart(defaultTime);
    }
  }, [isOpen, previousWaypoint]);

  // Real-time speed calculation
  useEffect(() => {
    if (previousWaypoint && position && timeFromStart > (previousWaypoint.timeFromStart || 0)) {
      const speed = calculateSpeed(
        previousWaypoint,
        { ...position, timeFromStart },
        position
      );
      setEstimatedSpeed(speed);
      setSpeedStatus(getSpeedStatus(speed));
    } else {
      setEstimatedSpeed(0);
      setSpeedStatus('unknown');
    }
  }, [position, previousWaypoint, timeFromStart]);

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
    if (altitude < 1 || altitude > 500) {
      alert('Altitude must be between 1 and 500 meters');
      return;
    }

    if (previousWaypoint && timeFromStart <= (previousWaypoint.timeFromStart || 0)) {
      alert('Time must be greater than previous waypoint time');
      return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed: estimatedSpeed,
      speedFeasible: speedStatus === 'feasible'
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
      case 'marginal': return 'High speed - use caution';
      case 'impossible': return 'Speed too high for safe operation';
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
          <div className="waypoint-location-info">
            <div className="location-item">
              <label>Latitude:</label>
              <span>{position?.latitude.toFixed(6)}</span>
            </div>
            <div className="location-item">
              <label>Longitude:</label>
              <span>{position?.longitude.toFixed(6)}</span>
            </div>
          </div>

          <div className="waypoint-input-group">
            <label htmlFor="altitude-input">Altitude (m)</label>
            <input
              id="altitude-input"
              ref={altitudeRef}
              type="number"
              value={altitude}
              onChange={(e) => setAltitude(e.target.value)}
              min="1"
              max="500"
              step="1"
              className="waypoint-input"
              placeholder="Enter altitude in meters"
            />
            <div className="input-hint">Range: 1-500 meters</div>
          </div>

          <div className="waypoint-input-group">
            <label htmlFor="time-input">
              Time from start (s)
              {previousWaypoint && (
                <span className="time-constraint">
                  (must be greater than {previousWaypoint.timeFromStart || 0}s)
                </span>
              )}
            </label>
            <input
              id="time-input"
              type="number"
              value={timeFromStart}
              onChange={(e) => setTimeFromStart(e.target.value)}
              min={previousWaypoint ? (previousWaypoint.timeFromStart || 0) + 1 : 1}
              step="0.1"
              className="waypoint-input"
              placeholder="Enter time from mission start"
            />
          </div>

          {estimatedSpeed > 0 && (
            <div className="speed-calculation">
              <div className="speed-header">
                <label>Estimated Speed Required:</label>
                <div className={`speed-indicator ${getSpeedIndicatorClass()}`}>
                  {estimatedSpeed.toFixed(1)} m/s
                </div>
              </div>
              <div className={`speed-status ${speedStatus}`}>
                {getSpeedMessage()}
              </div>
              {speedStatus === 'impossible' && (
                <div className="speed-warning">
                  Consider increasing time or reducing distance to previous waypoint
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
            Cancel (Esc)
          </button>
          <button 
            className="modal-btn modal-btn-confirm"
            onClick={handleConfirm}
            disabled={altitude < 1 || altitude > 500 || (previousWaypoint && timeFromStart <= (previousWaypoint.timeFromStart || 0))}
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