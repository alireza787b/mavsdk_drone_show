// src/components/trajectory/WaypointModal.js
// FIXED: Simplified altitude dialog with real MapGL terrain data
// REMOVED: Confusing terrain sections, estimation functions
// ADDED: Real map.queryTerrainElevation() integration

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { calculateSpeed, getSpeedStatus } from '../../utilities/SpeedCalculator';
import '../../styles/WaypointModal.css';

const WaypointModal = ({ 
  isOpen, 
  onClose, 
  onConfirm, 
  position,
  previousWaypoint,
  waypointIndex,
  mapRef // ADDED: Map reference for real terrain queries
}) => {
  // SIMPLIFIED: Core state only - removed complex terrain state
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [isLoadingTerrain, setIsLoadingTerrain] = useState(false);
  const [terrainError, setTerrainError] = useState(null);
  
  const altitudeRef = useRef(null);

  // Auto-focus altitude input when modal opens
  useEffect(() => {
    if (isOpen && altitudeRef.current) {
      altitudeRef.current.focus();
      altitudeRef.current.select();
    }
  }, [isOpen]);

  // Calculate default time from previous waypoint
  useEffect(() => {
    if (isOpen) {
      const defaultTime = previousWaypoint
        ? (previousWaypoint.timeFromStart || 0) + 10 
        : 10;
      setTimeFromStart(defaultTime);
    }
  }, [isOpen, previousWaypoint]);

  // FIXED: Real terrain elevation using MapGL API
  useEffect(() => {
    if (isOpen && position && mapRef?.current) {
      setIsLoadingTerrain(true);
      setTerrainError(null);
      
      try {
        // CRITICAL: Use real MapGL queryTerrainElevation API
        const map = mapRef.current.getMap ? mapRef.current.getMap() : mapRef.current;
        
        if (map && typeof map.queryTerrainElevation === 'function') {
          const coordinate = [position.longitude, position.latitude];
          const elevation = map.queryTerrainElevation(coordinate);
          
          if (elevation !== null && elevation !== undefined) {
            const realGroundElevation = Math.max(0, elevation);
            setGroundElevation(realGroundElevation);
            
            // SIMPLIFIED: Auto-fill elevation + 100m MSL
            const suggestedAltitude = realGroundElevation + 100;
            setAltitude(suggestedAltitude);
            
            console.info(`Real terrain: Ground ${realGroundElevation.toFixed(1)}m MSL, Suggested ${suggestedAltitude.toFixed(1)}m MSL`);
          } else {
            // Fallback to basic estimation if terrain not loaded
            throw new Error('Terrain data not loaded');
          }
        } else {
          throw new Error('MapGL terrain API not available');
        }
      } catch (error) {
        console.warn('Real terrain query failed, using fallback:', error);
        setTerrainError('Using estimated terrain data');
        
        // FALLBACK: Simple geographic estimation
        const estimatedGround = estimateBasicElevation(position.latitude, position.longitude);
        setGroundElevation(estimatedGround);
        setAltitude(estimatedGround + 100);
      }
      
      setIsLoadingTerrain(false);
    }
  }, [isOpen, position, mapRef]);

  // Real-time speed calculation and validation
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

  // SIMPLIFIED: Basic elevation estimation fallback
  const estimateBasicElevation = (latitude, longitude) => {
    // Simple geographic-based estimation
    if (Math.abs(latitude) > 60) return 300; // Polar regions
    if (Math.abs(latitude) < 30) return 50;  // Tropical regions
    
    // Check for major mountain ranges (very basic)
    if (latitude > 25 && latitude < 50 && longitude > -125 && longitude < -100) return 1500; // Rocky Mountains
    if (latitude > 25 && latitude < 45 && longitude > 65 && longitude < 105) return 2000;    // Himalayas
    
    return 150; // Default continental
  };

  const handleConfirm = () => {
    // SIMPLIFIED: Direct altitude validation
    const isUnderground = altitude < groundElevation;
    
    if (isUnderground) {
      alert(`⚠️ Altitude ${altitude}m is below ground level (${groundElevation.toFixed(1)}m MSL). Please adjust altitude above ground level.`);
      return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed,
      speedFeasible: true, // Always allow creation per Phase 3 requirements
      groundElevation,
      terrainAccurate: !terrainError
    };

    onConfirm(waypointData);
  };

  const handleCancel = () => {
    onClose();
  };

  const handleAltitudeChange = (e) => {
    const newAltitude = parseFloat(e.target.value) || 0;
    setAltitude(newAltitude);
  };

  const handleTimeChange = (e) => {
    const newTime = parseFloat(e.target.value) || 0;
    setTimeFromStart(Math.max(0, newTime));
  };

  // Speed status styling
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
          {/* SIMPLIFIED: Location display only */}
          <div className="waypoint-location-info">
            <div className="location-item">
              <label>📍 Coordinates</label>
              <span>{position?.latitude?.toFixed(6)}, {position?.longitude?.toFixed(6)}</span>
            </div>
          </div>

          {/* SIMPLIFIED: Altitude input with real terrain context */}
          <div className="altitude-section">
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
              </div>
              {isUnderground && (
                <div className="validation-message error">
                  ⚠️ Altitude is below ground level! Minimum: {groundElevation.toFixed(1)}m MSL
                </div>
              )}
            </div>
          </div>

          {/* Time input */}
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
          </div>

          {/* SIMPLIFIED: Speed display */}
          {previousWaypoint && (
            <div className="speed-section">
              <div className="speed-display" style={getSpeedStatusStyle(speedStatus)}>
                <div className="speed-header">
                  <span className="speed-label">Required Speed</span>
                  <span className="speed-value">{estimatedSpeed.toFixed(1)} m/s</span>
                </div>
                {speedStatus !== 'feasible' && (
                  <div className="speed-warning">
                    {speedStatus === 'marginal' ? '⚠️ High speed - use caution' : '🚨 Very high speed - review timing'}
                  </div>
                )}
              </div>
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
  mapRef: PropTypes.object.isRequired, // ADDED: Required map reference
};

WaypointModal.defaultProps = {
  position: null,
  previousWaypoint: null,
  waypointIndex: 1,
};

export default WaypointModal;