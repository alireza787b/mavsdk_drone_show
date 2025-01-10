// src/components/OriginModal.js

import React, { useState, useEffect } from 'react';
import '../styles/OriginModal.css';
import MapSelector from './MapSelector';
import { toast } from 'react-toastify';
import useComputeOrigin from '../hooks/useComputeOrigin';
import PropTypes from 'prop-types';

/**
 * OriginModal
 *
 * Props:
 * - isOpen (bool): Whether the modal is open.
 * - onClose (func): Function to close the modal.
 * - onSubmit (func): Function to handle origin submission.
 * - telemetryData (object): Telemetry data for drones.
 * - configData (array): Configuration data for drones.
 */
const OriginModal = ({ isOpen, onClose, onSubmit, telemetryData, configData }) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');

  const [computeParams, setComputeParams] = useState(null);
  const { origin: computedOrigin, error: computeError, loading: computeLoading } = useComputeOrigin(computeParams);

  // Validate and parse manual coordinate input
  const validateManualInput = () => {
    // Simple regex to validate decimal degrees (DD) format
    const ddRegex = /^-?\d+(\.\d+)?\s*,\s*-?\d+(\.\d+)?$/;
    if (ddRegex.test(coordinateInput.trim())) {
      const [lat, lon] = coordinateInput.trim().split(',').map(Number);
      return { lat, lon };
    }
    // If not DD, attempt to parse DMS or other formats using external libraries if needed
    // For simplicity, only DD is handled here
    setErrors({ input: 'Invalid coordinate format. Please enter as "lat, lon" in decimal degrees.' });
    return null;
  };

  // Handle origin submission
  const handleSubmit = () => {
    if (originMethod === 'manual') {
      if (selectedLatLon) {
        onSubmit(selectedLatLon.lat, selectedLatLon.lon);
        toast.success('Origin set successfully.');
      } else {
        const validated = validateManualInput();
        if (validated) {
          onSubmit(validated.lat, validated.lon);
          toast.success('Origin set successfully.');
        }
      }
    } else if (originMethod === 'drone') {
      if (computedOrigin) {
        onSubmit(computedOrigin.lat, computedOrigin.lon);
        toast.success('Origin computed and set successfully.');
      } else {
        toast.error('Origin computation failed. Please try again.');
      }
    }
  };

  // Handle drone selection and set compute parameters
  useEffect(() => {
    if (originMethod === 'drone' && selectedDroneId) {
      const droneConfig = configData.find((drone) => drone.hw_id === selectedDroneId);
      const droneTelemetry = telemetryData[selectedDroneId];
      if (droneConfig && droneTelemetry) {
        const { x: intended_east, y: intended_north } = droneConfig;
        const { Position_Lat: current_lat, Position_Long: current_lon } = droneTelemetry;
        if (current_lat && current_lon && intended_east && intended_north) {
          setComputeParams({
            current_lat: parseFloat(current_lat),
            current_lon: parseFloat(current_lon),
            intended_east: parseFloat(intended_east),
            intended_north: parseFloat(intended_north),
          });
        } else {
          toast.error('Incomplete telemetry or configuration data for the selected drone.');
        }
      } else {
        toast.error('Selected drone configuration or telemetry data not found.');
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originMethod, selectedDroneId, configData, telemetryData]);

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
            <MapSelector onSelect={setSelectedLatLon} />
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
            {computeError && <span className="error-message">{computeError}</span>}
            {computedOrigin && (
              <div className="computed-origin">
                <p><strong>Computed Origin:</strong></p>
                <p>Latitude: {computedOrigin.lat.toFixed(8)}</p>
                <p>Longitude: {computedOrigin.lon.toFixed(8)}</p>
              </div>
            )}
          </div>
        )}

        {/* Modal Actions */}
        <div className="modal-actions">
          <button onClick={handleSubmit} className="ok-button" disabled={computeLoading}>
            Set Origin
          </button>
          <button onClick={onClose} className="cancel-button" disabled={computeLoading}>
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
};

export default OriginModal;
