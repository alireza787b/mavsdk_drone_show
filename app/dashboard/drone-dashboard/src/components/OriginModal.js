// app/dashboard/drone-dashboard/src/components/OriginModal.js

import React, { useState, useEffect } from 'react';
import '../styles/OriginModal.css';
import CoordinateParser from 'coordinate-parser';
import MapSelector from './MapSelector';
import axios from 'axios';
import { getBackendURL } from '../utilities/utilities';

const OriginModal = ({ isOpen, onClose, onSubmit, telemetryData, configData }) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(null);
  const [originMethod, setOriginMethod] = useState('manual'); // 'manual' or 'drone'
  const [selectedDroneId, setSelectedDroneId] = useState('');
  const [computedOrigin, setComputedOrigin] = useState(null);
  const [droneError, setDroneError] = useState('');

  const validateInput = () => {
    try {
      const parsedCoord = new CoordinateParser(coordinateInput);
      const lat = parsedCoord.latitude;
      const lon = parsedCoord.longitude;
      setErrors({});
      return { lat, lon };
    } catch (error) {
      setErrors({ input: 'Invalid coordinate format.' });
      return null;
    }
  };

  const handleSubmit = () => {
    if (originMethod === 'manual') {
      let result;
      if (selectedLatLon) {
        result = selectedLatLon;
      } else {
        result = validateInput();
      }
      if (result) {
        onSubmit(result.lat, result.lon);
      }
    } else if (originMethod === 'drone') {
      if (computedOrigin) {
        onSubmit(computedOrigin.lat, computedOrigin.lon);
      } else {
        setDroneError('Cannot set origin. Computed origin is not available.');
      }
    }
  };

  const handleMapSelect = (lat, lon) => {
    setSelectedLatLon({ lat, lon });
    setCoordinateInput(`${lat}, ${lon}`);
    setErrors({});
  };

  // Effect to compute origin when a drone is selected
  useEffect(() => {
    if (originMethod !== 'drone' || !selectedDroneId) {
      return;
    }

    // Find the selected drone in configData and telemetryData
    const droneConfig = configData.find((drone) => drone.hw_id === selectedDroneId);
    const droneTelemetry = telemetryData[selectedDroneId];

    if (!droneTelemetry || !droneTelemetry.Position_Lat || !droneTelemetry.Position_Long) {
      setDroneError('Selected drone position is not available.');
      setComputedOrigin(null);
      return;
    }

    if (!droneConfig) {
      setDroneError('Drone configuration not found.');
      setComputedOrigin(null);
      return;
    }

    // Get current position
    const currentLat = parseFloat(droneTelemetry.Position_Lat);
    const currentLon = parseFloat(droneTelemetry.Position_Long);

    // Get intended N, E positions
    const intendedEast = parseFloat(droneConfig.x) || 0; // 'x' is East
    const intendedNorth = parseFloat(droneConfig.y) || 0; // 'y' is North

    // Make an API call to the backend to compute the origin
    const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

    const requestData = {
      current_lat: currentLat,
      current_lon: currentLon,
      intended_east: intendedEast,
      intended_north: intendedNorth,
    };

    axios
      .post(`${backendURL}/compute-origin`, requestData)
      .then((response) => {
        if (response.data && response.data.lat && response.data.lon) {
          setComputedOrigin({ lat: response.data.lat, lon: response.data.lon });
          setDroneError('');
        } else {
          setDroneError('Error computing origin from backend.');
          setComputedOrigin(null);
        }
      })
      .catch((error) => {
        console.error('Error computing origin from backend:', error);
        setDroneError('Error computing origin from backend.');
        setComputedOrigin(null);
      });
  }, [originMethod, selectedDroneId, configData, telemetryData]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Select Origin Coordinates</h3>
        <div className="origin-method-selection">
          <label>
            <input
              type="radio"
              value="manual"
              checked={originMethod === 'manual'}
              onChange={() => {
                setOriginMethod('manual');
                setErrors({});
                setSelectedDroneId('');
                setComputedOrigin(null);
                setDroneError('');
              }}
            />
            Enter Coordinates Manually
          </label>
          <label>
            <input
              type="radio"
              value="drone"
              checked={originMethod === 'drone'}
              onChange={() => {
                setOriginMethod('drone');
                setCoordinateInput('');
                setSelectedLatLon(null);
                setErrors({});
              }}
            />
            Use Drone as Reference
          </label>
        </div>

        {originMethod === 'manual' && (
          <>
            <div className="coordinate-input">
              <label>
                Coordinates:
                <input
                  type="text"
                  value={coordinateInput}
                  onChange={(e) => {
                    setCoordinateInput(e.target.value);
                    setSelectedLatLon(null); // Reset map selection
                  }}
                  placeholder='e.g., "35°24&#39;28.0&quot;N 50°09&#39;53.6&quot;E" or "35.4079, 50.1649"'
                  />
                {errors.input && <span className="error-message">{errors.input}</span>}
              </label>
            </div>
            <MapSelector onSelect={handleMapSelect} />
          </>
        )}

        {originMethod === 'drone' && (
          <div className="drone-selection">
            <label>
              Select Drone:
              <select
                value={selectedDroneId}
                onChange={(e) => {
                  setSelectedDroneId(e.target.value);
                  setDroneError('');
                  setComputedOrigin(null);
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
            {droneError && <span className="error-message">{droneError}</span>}
            {computedOrigin && (
              <div className="computed-origin">
                <p>Computed Origin:</p>
                <p>Latitude: {computedOrigin.lat}</p>
                <p>Longitude: {computedOrigin.lon}</p>
              </div>
            )}
          </div>
        )}

        <div className="modal-buttons">
          <button onClick={handleSubmit} className="ok-button">
            OK
          </button>
          <button onClick={onClose} className="cancel-button">
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default OriginModal;




