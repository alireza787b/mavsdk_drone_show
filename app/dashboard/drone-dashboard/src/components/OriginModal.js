// src/components/OriginModal.js

import React, { useState, useEffect } from 'react';
import '../styles/OriginModal.css';
import MapSelector from './MapSelector';
import { toast } from 'react-toastify';
import useComputeOrigin from '../hooks/useComputeOrigin';
import PropTypes from 'prop-types';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSyncAlt } from '@fortawesome/free-solid-svg-icons';

/**
 * OriginModal
 *
 * Workflow:
 * 1. "Manual" tab: user enters lat/lon or picks from map, then clicks "Set Origin".
 * 2. "Drone" tab: user picks a drone. The system attempts auto-compute once, storing success or error in the hook.
 *    - We show the "Retry" button at all times if a drone is selected.
 *    - The user must explicitly click "Set Origin" to finalize the computed origin if it is successful.
 */
const OriginModal = ({
  isOpen,
  onClose,
  onSubmit,
  telemetryData,
  configData,
  currentOrigin,
}) => {
  // ------------------------------------------
  // Local States
  // ------------------------------------------
  const [coordinateInput, setCoordinateInput] = useState('');
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');
  const [errors, setErrors] = useState({});

  // Altitude support (optional)
  const [altitude, setAltitude] = useState('');
  const [altitudeSource, setAltitudeSource] = useState('manual');

  // A flag to ensure we auto-compute only once when a drone is first picked.
  const [hasAutoComputed, setHasAutoComputed] = useState(false);

  // The custom hook to compute origin
  const { origin, error, loading, computeOrigin } = useComputeOrigin();

  // ------------------------------------------
  // 1. Initialize or reset modal
  // ------------------------------------------
  useEffect(() => {
    if (isOpen) {
      // If there's a known current origin, load it into the manual tab.
      if (currentOrigin?.lat && currentOrigin?.lon) {
        setCoordinateInput(`${currentOrigin.lat}, ${currentOrigin.lon}`);
        setSelectedLatLon({ lat: currentOrigin.lat, lon: currentOrigin.lon });
        setOriginMethod('manual');
        // Load altitude if available
        if (currentOrigin.alt !== undefined && currentOrigin.alt !== null) {
          setAltitude(currentOrigin.alt.toString());
          setAltitudeSource(currentOrigin.alt_source || 'manual');
        }
      } else {
        setCoordinateInput('');
        setSelectedLatLon(null);
        setAltitude('');
        setAltitudeSource('manual');
      }

      // Reset states
      setErrors({});
      setSelectedDroneId('');
      setHasAutoComputed(false);
    }
  }, [isOpen, currentOrigin]);

  // If user picks a lat/lon from the map in manual mode, reflect that in text input
  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  // ------------------------------------------
  // 2. Auto-compute once if Drone is selected
  // ------------------------------------------
  useEffect(() => {
    if (originMethod === 'drone' && selectedDroneId && !hasAutoComputed) {
      // Mark that we've done auto-compute attempt
      setHasAutoComputed(true);

      // Try to compute once (if valid lat/lon)
      const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
      if (!selectedDrone) {
        setErrors({ drone: 'Selected drone not found.' });
        return;
      }
      const {
        current_lat,
        current_lon,
        intended_east,
        intended_north,
        isValid,
      } = extractDroneParameters(selectedDrone);
      if (!isValid) {
        setErrors({ drone: 'No valid telemetry or lat/lon is (0,0). Drone not connected?' });
        return;
      }
      computeOrigin({ current_lat, current_lon, intended_east, intended_north });
    }
  }, [
    originMethod,
    selectedDroneId,
    hasAutoComputed,
    configData,
    computeOrigin,
  ]);

  // If the custom hook has an error, toast once
  useEffect(() => {
    if (error) {
      toast.error(`Origin computation failed: ${error}`);
    }
  }, [error]);

  // ------------------------------------------
  // Drone Parameter Extraction
  // ------------------------------------------
  const extractDroneParameters = (drone) => {
    const tData = telemetryData[drone.hw_id] || {};
    const lat = parseFloat(tData.lat || tData.Position_Lat || 0);
    const lon = parseFloat(tData.lon || tData.Position_Long || 0);

    // If lat/lon ~ zero or missing => invalid
    if (Math.abs(lat) < 0.0001 && Math.abs(lon) < 0.0001) {
      return {
        current_lat: 0,
        current_lon: 0,
        // CRITICAL FIX: x = North, y = East (matches config.csv schema)
        intended_north: parseFloat(drone.x) || 0,  // x is North
        intended_east: parseFloat(drone.y) || 0,   // y is East
        isValid: false,
      };
    }

    return {
      current_lat: lat,
      current_lon: lon,
      // CRITICAL FIX: x = North, y = East (matches config.csv schema)
      intended_north: parseFloat(drone.x) || 0,  // x is North
      intended_east: parseFloat(drone.y) || 0,   // y is East
      isValid: true,
    };
  };

  // ------------------------------------------
  // Manual Input Validation
  // ------------------------------------------
  const validateManualInput = () => {
    const ddRegex = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/;
    if (ddRegex.test(coordinateInput.trim())) {
      const [lat, lon] = coordinateInput.trim().split(',').map(Number);
      return { lat, lon };
    }
    setErrors({
      input: 'Invalid format. Please enter coordinates as "lat, lon" in decimal degrees.',
    });
    return null;
  };

  // ------------------------------------------
  // Retry button for Drone-based approach
  // Always visible if a drone is selected
  // ------------------------------------------
  const handleRetryCompute = () => {
    if (!selectedDroneId) {
      toast.error('No drone selected.');
      return;
    }
    const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
    if (!selectedDrone) {
      setErrors({ drone: 'Selected drone not found.' });
      return;
    }
    const {
      current_lat,
      current_lon,
      intended_east,
      intended_north,
      isValid,
    } = extractDroneParameters(selectedDrone);

    if (!isValid) {
      setErrors({ drone: 'No valid telemetry or lat/lon is (0,0). Drone not connected?' });
      return;
    }
    // Attempt re-compute
    computeOrigin({ current_lat, current_lon, intended_east, intended_north });
  };

  // ------------------------------------------
  // Handler: "Set Origin"
  // ------------------------------------------
  const handleSubmit = () => {
    if (originMethod === 'manual') {
      let originData;

      if (selectedLatLon) {
        originData = {
          lat: selectedLatLon.lat,
          lon: selectedLatLon.lon
        };
      } else {
        const validated = validateManualInput();
        if (!validated) return;
        originData = validated;
      }

      // Add altitude if provided
      if (altitude && altitude.trim() !== '') {
        originData.alt = parseFloat(altitude);
        originData.alt_source = 'manual';
      }

      onSubmit(originData);
      toast.success('Origin set successfully.');
      onClose();

    } else {
      // Drone-based
      if (!selectedDroneId) {
        setErrors({ drone: 'Please select a drone to compute origin.' });
        return;
      }
      if (origin) {
        // We have a computed origin => finalize
        // Add altitude from drone telemetry if available
        const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
        const tData = telemetryData[selectedDrone?.hw_id] || {};
        const droneAlt = tData.absolute_altitude_m || tData.Position_Alt;

        const originData = { ...origin };
        if (droneAlt && !isNaN(parseFloat(droneAlt))) {
          originData.alt = parseFloat(droneAlt);
          originData.alt_source = 'drone';
        }

        onSubmit(originData);
        toast.success('Origin set successfully.');
        onClose();
      } else {
        // No success yet => attempt one more time
        handleRetryCompute();
      }
    }
  };

  const handleInputChange = (e) => {
    setCoordinateInput(e.target.value);
    setSelectedLatLon(null);
    setErrors({});
  };

  if (!isOpen) return null;

  return (
    <div className="origin-modal-overlay" onClick={onClose}>
      <div className="origin-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Set Origin Coordinates</h3>

        {/* Tab Buttons */}
        <div className="origin-method-selection">
          <button
            className={`method-button ${originMethod === 'manual' ? 'active' : ''}`}
            onClick={() => {
              setOriginMethod('manual');
              setErrors({});
            }}
          >
            Enter Coordinates Manually
          </button>
          <button
            className={`method-button ${originMethod === 'drone' ? 'active' : ''}`}
            onClick={() => {
              setOriginMethod('drone');
              setErrors({});
            }}
          >
            Use Drone as Reference
          </button>
        </div>

        {/* Manual Section */}
        {originMethod === 'manual' && (
          <div className="manual-entry">
            <label>
              Coordinates (lat, lon):
              <input
                type="text"
                value={coordinateInput}
                onChange={handleInputChange}
                placeholder='e.g., "35.4079, 50.1649"'
              />
            </label>
            {errors.input && <span className="error-message">{errors.input}</span>}

            <label style={{marginTop: '1rem'}}>
              Altitude MSL (optional, meters):
              <input
                type="number"
                step="0.1"
                value={altitude}
                onChange={(e) => setAltitude(e.target.value)}
                placeholder="Ground level (default: 0m)"
              />
            </label>
            <small className="help-text" style={{display: 'block', marginTop: '0.25rem', color: '#666'}}>
              Mean Sea Level altitude in meters. Leave blank for ground level (0m).
            </small>

            <p className="or-text">OR</p>
            <MapSelector
              onSelect={setSelectedLatLon}
              initialPosition={
                selectedLatLon
                  ? { lat: selectedLatLon.lat, lon: selectedLatLon.lon }
                  : null
              }
            />
          </div>
        )}

        {/* Drone Section */}
        {originMethod === 'drone' && (
          <div className="drone-reference">
            <label>
              Select Drone:
              <select
                value={selectedDroneId}
                onChange={(e) => {
                  setSelectedDroneId(e.target.value);
                  setErrors({});
                  setHasAutoComputed(false); // So we can auto-compute again on new selection
                }}
              >
                <option value="">-- Select Drone --</option>
                {configData.map((drone) => (
                  <option key={drone.hw_id} value={drone.hw_id}>
                    Drone {drone.hw_id}
                  </option>
                ))}
              </select>
            </label>
            {errors.drone && <span className="error-message">{errors.drone}</span>}

            {loading && <p className="loading-text">Computing origin...</p>}

            {/* If computed successfully */}
            {origin && (
              <div className="computed-origin">
                <p><strong>Computed Origin:</strong></p>
                <p>Latitude: {origin.lat.toFixed(8)}</p>
                <p>Longitude: {origin.lon.toFixed(8)}</p>
                {selectedDroneId && (() => {
                  const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
                  const tData = telemetryData[selectedDrone?.hw_id] || {};
                  const droneAlt = tData.absolute_altitude_m || tData.Position_Alt;
                  return droneAlt && !isNaN(parseFloat(droneAlt)) ? (
                    <p>Altitude: {parseFloat(droneAlt).toFixed(1)}m MSL (from drone)</p>
                  ) : null;
                })()}
              </div>
            )}

            {/* Always show the Retry button if a drone is selected */}
            {selectedDroneId && (
              <button
                className="retry-button"
                onClick={handleRetryCompute}
                disabled={loading}
              >
                <FontAwesomeIcon icon={faSyncAlt} />
                Retry
              </button>
            )}
          </div>
        )}

        {/* Modal Actions */}
        <div className="modal-actions">
          <button onClick={handleSubmit} className="ok-button" disabled={loading}>
            Set Origin
          </button>
          <button onClick={onClose} className="cancel-button" disabled={loading}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

OriginModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  telemetryData: PropTypes.object.isRequired,
  configData: PropTypes.array.isRequired,
  currentOrigin: PropTypes.shape({
    lat: PropTypes.number,
    lon: PropTypes.number,
  }),
};

export default OriginModal;
