// src/components/trajectory/WaypointModal.js
// UPDATED: Use Mapbox Tilequery API for terrain elevation fetching
// REMOVED: queryTerrainElevation usage and mapRef dependency for terrain queries
// ADDED: Fetch elevation via HTTP with error handling and fallback

import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { calculateSpeed, getSpeedStatus } from '../../utilities/SpeedCalculator';
import '../../styles/WaypointModal.css';

const MAPBOX_ACCESS_TOKEN = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN;

const WaypointModal = ({
  isOpen,
  onClose,
  onConfirm,
  position,
  previousWaypoint,
  waypointIndex,
  // mapRef // no longer needed for elevation queries, keep if used elsewhere
}) => {
  const [altitude, setAltitude] = useState(100);
  const [timeFromStart, setTimeFromStart] = useState(0);
  const [estimatedSpeed, setEstimatedSpeed] = useState(0);
  const [speedStatus, setSpeedStatus] = useState('unknown');
  const [groundElevation, setGroundElevation] = useState(0);
  const [isLoadingTerrain, setIsLoadingTerrain] = useState(false);
  const [terrainError, setTerrainError] = useState(null);

  const altitudeRef = useRef(null);

  useEffect(() => {
    if (isOpen && altitudeRef.current) {
      altitudeRef.current.focus();
      altitudeRef.current.select();
    }
  }, [isOpen]);

  useEffect(() => {
    if (isOpen) {
      const defaultTime = previousWaypoint
        ? (previousWaypoint.timeFromStart || 0) + 10
        : 10;
      setTimeFromStart(defaultTime);
    }
  }, [isOpen, previousWaypoint]);

  useEffect(() => {
    const fetchElevationFromTilequery = async (latitude, longitude) => {
      if (!MAPBOX_ACCESS_TOKEN) {
        console.error('Mapbox access token is missing.');
        setTerrainError('Missing Mapbox access token');
        const estimatedGround = estimateBasicElevation(latitude, longitude);
        setGroundElevation(estimatedGround);
        setAltitude(estimatedGround + 100);
        setIsLoadingTerrain(false);
        return;
      }

      try {
        setIsLoadingTerrain(true);
        setTerrainError(null);

        const url = `https://api.mapbox.com/v4/mapbox.mapbox-terrain-v2/tilequery/${longitude},${latitude}.json?layers=contour&limit=50&access_token=${MAPBOX_ACCESS_TOKEN}`;

        const response = await fetch(url);
        if (!response.ok) throw new Error(`Tilequery API error: ${response.status}`);

        const data = await response.json();

        if (!data.features || data.features.length === 0) {
          throw new Error('No elevation data found');
        }

        const elevations = data.features
          .map(f => f.properties.ele)
          .filter(ele => typeof ele === 'number');

        if (elevations.length === 0) {
          throw new Error('Elevation property missing in features');
        }

        const maxElevation = Math.max(...elevations);
        setGroundElevation(maxElevation);
        setAltitude(maxElevation + 100);

        console.info(`✅ Tilequery terrain: Ground ${maxElevation.toFixed(1)}m MSL, Suggested ${maxElevation + 100}m MSL`);
      } catch (error) {
        console.error('❌ Elevation fetch failed:', error);
        setTerrainError('Query failed, using estimated data');
        const estimatedGround = estimateBasicElevation(latitude, longitude);
        setGroundElevation(estimatedGround);
        setAltitude(estimatedGround + 100);
      } finally {
        setIsLoadingTerrain(false);
      }
    };

    if (isOpen && position) {
      fetchElevationFromTilequery(position.latitude, position.longitude);
    }
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

  const estimateBasicElevation = (latitude, longitude) => {
    if (Math.abs(latitude) > 60) return 300; // Polar regions
    if (Math.abs(latitude) < 30) return 50;  // Tropical regions

    if (latitude > 25 && latitude < 50 && longitude > -125 && longitude < -100) return 1500; // Rocky Mountains
    if (latitude > 25 && latitude < 45 && longitude > 65 && longitude < 105) return 2000;   // Himalayas

    return 150; // Default continental
  };

  const handleConfirm = () => {
    const isUnderground = altitude < groundElevation;

    if (isUnderground) {
      alert(`⚠️ Altitude ${altitude}m is below ground level (${groundElevation.toFixed(1)}m MSL). Please adjust altitude above ground level.`);
      return;
    }

    const waypointData = {
      altitude: parseFloat(altitude),
      timeFromStart: parseFloat(timeFromStart),
      estimatedSpeed,
      speedFeasible: true,
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
          </div>

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
  // mapRef: PropTypes.object.isRequired, // Remove if not used elsewhere
};

WaypointModal.defaultProps = {
  position: null,
  previousWaypoint: null,
  waypointIndex: 1,
};

export default WaypointModal;
