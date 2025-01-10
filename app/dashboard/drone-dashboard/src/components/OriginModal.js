// src/components/OriginModal.js

import React, { useState, useEffect, useCallback } from 'react';
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
 * - "Manual" tab: user types in lat/long OR picks from the map.
 * - "Drone" tab: user picks a drone => auto-compute once => show result (success or error).
 *   The user can then click "Retry" if it failed or "Set Origin" to finalize if it succeeded.
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
  // Local state
  // ------------------------------------------
  const [coordinateInput, setCoordinateInput] = useState('');
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');

  // For error messages in the UI
  const [errors, setErrors] = useState({});

  // The custom hook to compute origin
  const { origin, error, loading, computeOrigin } = useComputeOrigin();

  // ------------------------------------------
  // Step 1: If user picks a drone, auto-compute once, 
  //         but only if we have valid lat/lon.
  // ------------------------------------------
  const autoComputeIfNeeded = useCallback(
    (droneId) => {
      if (!droneId) return; // no valid selection

      // If we already have a successful origin, do nothing
      if (origin) return;

      // We only re-run if no origin yet + not loading
      if (!origin && !loading) {
        const selectedDrone = configData.find((d) => d.hw_id === droneId);
        if (!selectedDrone) {
          setErrors({ drone: 'Selected drone not found.' });
          return;
        }
        // Extract lat/lon from telemetry. If invalid or zero => treat as error
        const { current_lat, current_lon, intended_east, intended_north, isValid } =
          extractDroneParameters(selectedDrone);
        if (!isValid) {
          setErrors({ drone: 'No valid telemetry or lat/lon is (0,0). Drone not connected?' });
          return;
        }

        // Attempt to compute origin
        computeOrigin({ current_lat, current_lon, intended_east, intended_north });
      }
    },
    [origin, loading, configData, computeOrigin]
  );

  // ------------------------------------------
  // Step 2: Modal initialization
  // ------------------------------------------
  useEffect(() => {
    if (isOpen) {
      // If there's a known current origin, set it in the text input
      if (currentOrigin?.lat && currentOrigin?.lon) {
        setCoordinateInput(`${currentOrigin.lat}, ${currentOrigin.lon}`);
        setSelectedLatLon({ lat: currentOrigin.lat, lon: currentOrigin.lon });
        setOriginMethod('manual');
      } else {
        // Fresh open with no known origin
        setCoordinateInput('');
        setSelectedLatLon(null);
      }
      setErrors({});
      setSelectedDroneId('');
    }
  }, [isOpen, currentOrigin]);

  // If user picks a lat/lon from the map in manual mode, reflect that in text input
  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  // Whenever user picks a drone, auto-compute once if no successful origin
  useEffect(() => {
    if (originMethod === 'drone' && selectedDroneId) {
      autoComputeIfNeeded(selectedDroneId);
    }
  }, [originMethod, selectedDroneId, autoComputeIfNeeded]);

  // ------------------------------------------
  // Step 3: Hook outcomes
  // If the hook got an error, we show it. 
  // If success, do NOT auto-close. The user must click "Set Origin".
  // ------------------------------------------
  useEffect(() => {
    if (error) {
      toast.error(`Origin computation failed: ${error}`);
    }
  }, [error]);

  // ------------------------------------------
  // Utility: Extract Drone parameters 
  // with validation for lat/lon != 0 or none
  // ------------------------------------------
  const extractDroneParameters = (drone) => {
    // Attempt to read the lat/lon from telemetry
    const tData = telemetryData[drone.hw_id] || {};
    const lat = parseFloat(tData.lat || tData.Position_Lat || 0);
    const lon = parseFloat(tData.lon || tData.Position_Long || 0);

    // If lat/lon are effectively zero or missing, treat as invalid
    if (Math.abs(lat) < 0.0001 && Math.abs(lon) < 0.0001) {
      return {
        current_lat: lat,
        current_lon: lon,
        intended_east: parseFloat(drone.x) || 0,
        intended_north: parseFloat(drone.y) || 0,
        isValid: false,
      };
    }

    return {
      current_lat: lat,
      current_lon: lon,
      intended_east: parseFloat(drone.x) || 0, // config file: x=East, y=North
      intended_north: parseFloat(drone.y) || 0,
      isValid: true,
    };
  };

  // ------------------------------------------
  // Utility: Validate manual text input
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
  // Handler: When user clicks "Set Origin"
  // ------------------------------------------
  const handleSubmit = () => {
    // If manual
    if (originMethod === 'manual') {
      // If user selected from map
      if (selectedLatLon) {
        onSubmit({ lat: selectedLatLon.lat, lon: selectedLatLon.lon });
        toast.success('Origin set successfully.');
        onClose();
        return;
      } else {
        // Else parse text input
        const validated = validateManualInput();
        if (validated) {
          onSubmit(validated);
          toast.success('Origin set successfully.');
          onClose();
        }
      }
    } else {
      // Drone-based
      if (!selectedDroneId) {
        setErrors({ drone: 'Please select a drone to compute origin.' });
        return;
      }
      // If we have a successful origin from the hook, finalize
      if (origin) {
        onSubmit(origin);
        toast.success('Origin set successfully.');
        onClose();
      } else {
        // No successful origin yet => attempt one more time
        handleRetryCompute();
      }
    }
  };

  // ------------------------------------------
  // Handler: Retry button
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
    const { current_lat, current_lon, intended_east, intended_north, isValid } =
      extractDroneParameters(selectedDrone);

    if (!isValid) {
      setErrors({ drone: 'No valid telemetry or lat/lon is (0,0). Drone not connected?' });
      return;
    }

    computeOrigin({ current_lat, current_lon, intended_east, intended_north });
  };

  // ------------------------------------------
  // Handler: Manual coordinate input changes
  // ------------------------------------------
  const handleInputChange = (e) => {
    setCoordinateInput(e.target.value);
    setSelectedLatLon(null);
    setErrors({});
  };

  // ------------------------------------------
  // Render
  // ------------------------------------------
  if (!isOpen) return null;

  return (
    <div className="origin-modal-overlay" onClick={onClose}>
      <div
        className="origin-modal"
        onClick={(e) => e.stopPropagation()} // prevent closing when clicking inside
      >
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

            {/* Show computed origin if success */}
            {origin && (
              <div className="computed-origin">
                <p>
                  <strong>Computed Origin:</strong>
                </p>
                <p>Latitude: {origin.lat.toFixed(8)}</p>
                <p>Longitude: {origin.lon.toFixed(8)}</p>
              </div>
            )}

            {/* If there's an error and no success, show Retry */}
            {error && !origin && (
              <button className="retry-button" onClick={handleRetryCompute} disabled={loading}>
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
