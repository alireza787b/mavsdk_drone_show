//app/dashboard/drone-dashboard/src/components/OriginModal.js
import React, { useState, useEffect } from 'react';
import '../styles/OriginModal.css';
import MapSelector from './MapSelector';
import { toast } from 'react-toastify';
import useComputeOrigin from '../hooks/useComputeOrigin';
import PropTypes from 'prop-types';

const OriginModal = ({ isOpen, onClose, onSubmit, telemetryData, configData, origin }) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(origin ? { lat: origin.lat, lon: origin.lon } : null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');
  const [hasError, setHasError] = useState(false);

  const [computeParams, setComputeParams] = useState(null);
  const { origin: computedOrigin, error: computeError, loading: computeLoading } = useComputeOrigin(computeParams);

  // Update coordinateInput when a point is selected on the map
  useEffect(() => {
    if (selectedLatLon) {
      setCoordinateInput(`${selectedLatLon.lat}, ${selectedLatLon.lon}`);
    }
  }, [selectedLatLon]);

  // Show error once
  useEffect(() => {
    if (computeError && !hasError) {
      toast.error(computeError);
      setHasError(true);
    }
  }, [computeError, hasError]);

  // Reset hasError when originMethod changes
  useEffect(() => {
    setHasError(false);
  }, [originMethod]);

  // Initialize coordinateInput with the current origin if available
  useEffect(() => {
    if (origin && origin.lat && origin.lon) {
      setCoordinateInput(`${origin.lat}, ${origin.lon}`);
      setSelectedLatLon({ lat: origin.lat, lon: origin.lon });
    }
  }, [origin]);

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
      if (computedOrigin) {
        onSubmit(computedOrigin);
        toast.success('Origin computed and set successfully.');
      } else {
        toast.error('Origin computation failed. Please try again.');
      }
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
            onClick={() => {
              setOriginMethod('manual');
              setErrors({});
              setSelectedDroneId('');
              setComputeParams(null);
            }}
          >
            Enter Coordinates Manually
          </button>
          <button
            className={`method-button ${originMethod === 'drone' ? 'active' : ''}`}
            onClick={() => {
              setOriginMethod('drone');
              setCoordinateInput('');
              setSelectedLatLon(null);
              setErrors({});
            }}
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
                onChange={(e) => {
                  setCoordinateInput(e.target.value);
                  setSelectedLatLon(null); // Reset map selection
                  setErrors({});
                }}
                placeholder='e.g., "35.4079, 50.1649"'
              />
            </label>
            {errors.input && <span className="error-message">{errors.input}</span>}
            <p className="or-text">OR</p>
            <MapSelector onSelect={setSelectedLatLon} initialPosition={selectedLatLon} />
          </div>
        )}

        {/* Drone Reference */}
        {originMethod === 'drone' && (
          <div className="drone-reference">
            <label>
              Select Drone:
              <select
                value={selectedDroneId}
                onChange={(e) => setSelectedDroneId(e.target.value)}
              >
                <option value="">-- Select Drone --</option>
                {configData.map((drone) => (
                  <option key={drone.hw_id} value={drone.hw_id}>
                    Drone {drone.hw_id}
                  </option>
                ))}
              </select>
            </label>
            {computeLoading && <p className="loading-text">Computing origin...</p>}
            {computedOrigin && (
              <div className="computed-origin">
                <strong>Computed Origin:</strong>
                <p>Lat: {computedOrigin.lat}, Lon: {computedOrigin.lon}</p>
              </div>
            )}
          </div>
        )}

        {/* Submit & Close Buttons */}
        <div className="modal-actions">
          <button className="cancel-btn" onClick={onClose}>Cancel</button>
          <button className="submit-btn" onClick={handleSubmit}>Set Origin</button>
        </div>
      </div>
    </div>
  );
};

OriginModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onSubmit: PropTypes.func.isRequired,
  telemetryData: PropTypes.array,
  configData: PropTypes.array.isRequired,
  origin: PropTypes.shape({
    lat: PropTypes.number,
    lon: PropTypes.number,
  }),
};

export default OriginModal;

