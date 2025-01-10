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
 * - "Drone" tab: user picks a drone. The system automatically computes 
 *   once on selection (only if no prior success). If it fails, show Retry.
 */
const OriginModal = ({
  isOpen,
  onClose,
  onSubmit,
  telemetryData,
  configData,
  currentOrigin,
}) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');

  const { origin, error, loading, computeOrigin } = useComputeOrigin();

  /**
   * 1. If user picks a drone, automatically compute origin 
   *    (only if we haven't got a successful result yet).
   * 2. If already successful, we won't re-run unless user clicks "Retry".
   */
  const autoComputeIfNeeded = useCallback(
    (droneId) => {
      if (!droneId) return;
      // If there's no successful origin from computeOrigin yet, do one-time compute
      if (!origin && !loading) {
        const selectedDrone = configData.find((d) => d.hw_id === droneId);
        if (!selectedDrone) {
          toast.error('Selected drone not found.');
          return;
        }
        const { current_lat, current_lon, intended_east, intended_north } =
          extractDroneParameters(selectedDrone);
        computeOrigin({ current_lat, current_lon, intended_east, intended_north });
      }
    },
    [origin, loading, configData, computeOrigin]
  );

  // On open or change, sync the coordinate input if we have a current origin
  useEffect(() => {
    if (isOpen && currentOrigin.lat && currentOrigin.lon) {
      setCoordinateInput(`${currentOrigin.lat}, ${currentOrigin.lon}`);
      setSelectedLatLon({ lat: currentOrigin.lat, lon: currentOrigin.lon });
      setOriginMethod('manual');
    } else if (isOpen) {
      // If user is opening fresh
      setCoordinateInput('');
      setSelectedLatLon(null);
    }
    setErrors({});
    setSelectedDroneId('');
  }, [isOpen, currentOrigin]);

  // If user picks a lat/lon from map, sync that into text input
  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  // If user selects a drone, automatically compute once
  useEffect(() => {
    if (originMethod === 'drone' && selectedDroneId) {
      autoComputeIfNeeded(selectedDroneId);
    }
  }, [originMethod, selectedDroneId, autoComputeIfNeeded]);

  // If we get a new computed origin from the hook, finish up
  useEffect(() => {
    if (origin) {
      onSubmit(origin);
      toast.success('Origin computed and set successfully.');
      onClose();
    }
    if (error) {
      toast.error(`Origin computation failed: ${error}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [origin, error]);

  // Helpers
  const handleInputChange = (e) => {
    setCoordinateInput(e.target.value);
    setSelectedLatLon(null);
    setErrors({});
  };

  // Validate manual input
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

  // Called when user clicks "Set Origin"
  const handleSubmit = () => {
    if (originMethod === 'manual') {
      if (selectedLatLon) {
        onSubmit({ lat: selectedLatLon.lat, lon: selectedLatLon.lon });
        toast.success('Origin set successfully.');
        onClose();
      } else {
        const validated = validateManualInput();
        if (validated) {
          onSubmit(validated);
          toast.success('Origin set successfully.');
          onClose();
        }
      }
    } else {
      // Drone-based; if we already have a successful origin, we're done
      // If not, user can click Retry
      if (!selectedDroneId) {
        setErrors({ drone: 'Please select a drone to compute origin.' });
        return;
      }
      if (!origin && !loading) {
        // Attempt one last time
        handleRetryCompute();
      } else if (origin) {
        // Already have origin
        toast.success('Origin set successfully.');
        onClose();
      }
    }
  };

  // Retry button for drone-based origin
  const handleRetryCompute = () => {
    if (!selectedDroneId) {
      toast.error('No drone selected.');
      return;
    }
    const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
    if (!selectedDrone) {
      toast.error('Selected drone not found.');
      return;
    }
    const { current_lat, current_lon, intended_east, intended_north } = extractDroneParameters(selectedDrone);
    computeOrigin({ current_lat, current_lon, intended_east, intended_north });
  };

  // Pull relevant data from telemetry
  const extractDroneParameters = (drone) => {
    const current_lat = telemetryData[drone.hw_id]?.lat || 0;
    const current_lon = telemetryData[drone.hw_id]?.lon || 0;
    const intended_east = parseFloat(drone.x) || 0;
    const intended_north = parseFloat(drone.y) || 0;
    return { current_lat, current_lon, intended_east, intended_north };
  };

  if (!isOpen) return null;

  return (
    <div className="origin-modal-overlay" onClick={onClose}>
      <div
        className="origin-modal"
        onClick={(e) => {
          e.stopPropagation(); // prevent closing when clicking inside
        }}
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
            {/* Map Selector for manual click */}
            <MapSelector
              onSelect={setSelectedLatLon}
              initialPosition={
                selectedLatLon ? { lat: selectedLatLon.lat, lon: selectedLatLon.lon } : null
              }
            />
          </div>
        )}

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

            {/* If we have an origin, show it */}
            {origin && (
              <div className="computed-origin">
                <p>
                  <strong>Computed Origin:</strong>
                </p>
                <p>Latitude: {origin.lat.toFixed(8)}</p>
                <p>Longitude: {origin.lon.toFixed(8)}</p>
              </div>
            )}

            {/* If there's an error, show Retry button */}
            {error && !origin && (
              <button className="retry-button" onClick={handleRetryCompute} disabled={loading}>
                <FontAwesomeIcon icon={faSyncAlt} />
                Retry
              </button>
            )}
          </div>
        )}

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
