// src/components/OriginModal.js

import React, { useState, useEffect } from 'react';
import '../styles/OriginModal.css';
import MapSelector from './MapSelector';
import { toast } from 'react-toastify';
import useComputeOrigin from '../hooks/useComputeOrigin';
import PropTypes from 'prop-types';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faSyncAlt } from '@fortawesome/free-solid-svg-icons';

const OriginModal = ({ isOpen, onClose, onSubmit, telemetryData, configData, currentOrigin }) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');

  const { origin, error, loading, computeOrigin } = useComputeOrigin();

  // Initialize modal state with currentOrigin when opened
  useEffect(() => {
    if (isOpen && currentOrigin.lat && currentOrigin.lon) {
      setCoordinateInput(`${currentOrigin.lat}, ${currentOrigin.lon}`);
      setSelectedLatLon({ lat: currentOrigin.lat, lon: currentOrigin.lon });
      setOriginMethod('manual');
    } else {
      setCoordinateInput('');
      setSelectedLatLon(null);
    }
    setErrors({});
    setSelectedDroneId('');
  }, [isOpen, currentOrigin]);

  // Update coordinateInput when a point is selected on the map
  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  // Validate and parse manual coordinate input
  const validateManualInput = () => {
    const ddRegex = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/;
    if (ddRegex.test(coordinateInput.trim())) {
      const [lat, lon] = coordinateInput.trim().split(',').map(Number);
      return { lat, lon };
    }
    setErrors({ input: 'Invalid coordinate format. Please enter as "lat, lon" in decimal degrees.' });
    return null;
  };

  const handleInputChange = (e) => {
    setCoordinateInput(e.target.value);
    setSelectedLatLon(null); // Reset map selection
    setErrors({});
  };

  // Handle origin submission
  const handleSubmit = () => {
    if (originMethod === 'manual') {
      if (selectedLatLon) {
        onSubmit({ lat: selectedLatLon.lat, lon: selectedLatLon.lon });
        toast.success('Origin set successfully.');
      } else {
        const validated = validateManualInput();
        if (validated) {
          onSubmit(validated);
          toast.success('Origin set successfully.');
        }
      }
    } else if (originMethod === 'drone') {
      if (selectedDroneId) {
        const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
        if (!selectedDrone) {
          toast.error('Selected drone not found.');
          return;
        }
        const { current_lat, current_lon, intended_east, intended_north } = extractDroneParameters(selectedDrone);
        computeOrigin({ current_lat, current_lon, intended_east, intended_north });
      } else {
        setErrors({ drone: 'Please select a drone to compute origin.' });
      }
    }
  };

  // Handle computation result
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

  // Extract necessary parameters from selected drone
  const extractDroneParameters = (drone) => {
    // Placeholder: Extract current_lat, current_lon, intended_east, intended_north from telemetryData or drone config
    // You need to replace this with actual data extraction logic based on your data structure
    const current_lat = telemetryData[drone.hw_id]?.lat || 0;
    const current_lon = telemetryData[drone.hw_id]?.lon || 0;
    const intended_east = parseFloat(drone.x) || 0;
    const intended_north = parseFloat(drone.y) || 0;

    return { current_lat, current_lon, intended_east, intended_north };
  };

  // Manual retry for drone-based origin computation
  const handleRetryCompute = () => {
    if (selectedDroneId) {
      const selectedDrone = configData.find((d) => d.hw_id === selectedDroneId);
      if (!selectedDrone) {
        toast.error('Selected drone not found.');
        return;
      }
      const { current_lat, current_lon, intended_east, intended_north } = extractDroneParameters(selectedDrone);
      computeOrigin({ current_lat, current_lon, intended_east, intended_north });
    }
  };

  if (!isOpen) return null;

  return (
    <div className="origin-modal-overlay" onClick={onClose}>
      <div className="origin-modal" onClick={(e) => e.stopPropagation()}>
        <h3>Set Origin Coordinates</h3>

        {/* Origin Method Selection */}
        <div className="origin-method-selection">
          <button
            className={`method-button ${originMethod === 'manual' ? 'active' : ''}`}
            onClick={() => setOriginMethod('manual')}
          >
            Enter Coordinates Manually
          </button>
          <button
            className={`method-button ${originMethod === 'drone' ? 'active' : ''}`}
            onClick={() => setOriginMethod('drone')}
          >
            Use Drone as Reference
          </button>
        </div>

        {/* Manual Entry */}
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
              initialPosition={selectedLatLon ? { lat: selectedLatLon.lat, lon: selectedLatLon.lon } : null}
            />
          </div>
        )}

        {/* Drone Reference */}
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

            {/* Computation Feedback */}
            {loading && <p className="loading-text">Computing origin...</p>}
            {origin && (
              <div className="computed-origin">
                <p><strong>Computed Origin:</strong></p>
                <p>Latitude: {origin.lat.toFixed(8)}</p>
                <p>Longitude: {origin.lon.toFixed(8)}</p>
              </div>
            )}

            {/* Retry Button */}
            {error && (
              <button className="retry-button" onClick={handleRetryCompute} disabled={loading}>
                <FontAwesomeIcon icon={faSyncAlt} /> Retry
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
