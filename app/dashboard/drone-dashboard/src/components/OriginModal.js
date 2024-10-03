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
  const [isComputing, setIsComputing] = useState(false);

  const validateInput = () => {
    try {
      const parsedCoord = new CoordinateParser(coordinateInput);
      const lat = parsedCoord.latitude;
      const lon = parsedCoord.longitude;

      if (isNaN(lat) || isNaN(lon)) {
        throw new Error('Parsed coordinates are NaN.');
      }

      setErrors({});
      console.log(`Validated manual input coordinates: lat=${lat}, lon=${lon}`);
      return { lat, lon };
    } catch (error) {
      console.error('Coordinate validation error:', error);
      setErrors({ input: 'Invalid coordinate format.' });
      return null;
    }
  };

  const handleSubmit = () => {
    console.log('Handle submit called. Origin method:', originMethod);

    if (originMethod === 'manual') {
      let result;
      if (selectedLatLon) {
        result = selectedLatLon;
        console.log('Using selected coordinates from map:', result);
      } else {
        result = validateInput();
      }

      if (result) {
        console.log('Submitting manual origin:', result);
        onSubmit(result.lat, result.lon);
      }
    } else if (originMethod === 'drone') {
      if (computedOrigin) {
        console.log('Submitting computed origin from drone:', computedOrigin);
        onSubmit(computedOrigin.lat, computedOrigin.lon);
      } else {
        setDroneError('Cannot set origin. Computed origin is not available.');
        console.warn('Computed origin is not available.');
      }
    }
  };

  const handleMapSelect = (lat, lon) => {
    console.log(`Map selection: lat=${lat}, lon=${lon}`);
    setSelectedLatLon({ lat, lon });
    setCoordinateInput(`${lat.toFixed(8)}, ${lon.toFixed(8)}`);
    setErrors({});
  };

  // Effect to compute origin when a drone is selected
  useEffect(() => {
    const computeOrigin = async () => {
      if (originMethod !== 'drone' || !selectedDroneId) {
        console.log('Origin method is not drone or no drone selected. Skipping computation.');
        return;
      }

      console.log(`Computing origin for drone ID: ${selectedDroneId}`);
      setIsComputing(true);
      setDroneError('');
      setComputedOrigin(null);

      // Find the selected drone in configData and telemetryData
      const droneConfig = configData.find((drone) => drone.hw_id === selectedDroneId);
      const droneTelemetry = telemetryData[selectedDroneId];

      if (!droneTelemetry || !droneTelemetry.Position_Lat || !droneTelemetry.Position_Long) {
        const errorMsg = 'Selected drone position is not available.';
        console.error(errorMsg);
        setDroneError(errorMsg);
        setIsComputing(false);
        return;
      }

      if (!droneConfig) {
        const errorMsg = 'Drone configuration not found.';
        console.error(errorMsg);
        setDroneError(errorMsg);
        setIsComputing(false);
        return;
      }

      // Get current position
      const currentLat = parseFloat(droneTelemetry.Position_Lat);
      const currentLon = parseFloat(droneTelemetry.Position_Long);

      if (isNaN(currentLat) || isNaN(currentLon)) {
        const errorMsg = 'Invalid drone telemetry data.';
        console.error(errorMsg);
        setDroneError(errorMsg);
        setIsComputing(false);
        return;
      }

      // Get intended N, E positions
      const intendedEast = parseFloat(droneConfig.x);
      const intendedNorth = parseFloat(droneConfig.y);

      if (isNaN(intendedEast) || isNaN(intendedNorth)) {
        const errorMsg = 'Invalid drone configuration data.';
        console.error(errorMsg);
        setDroneError(errorMsg);
        setIsComputing(false);
        return;
      }

      console.log(`Drone ${selectedDroneId} telemetry: currentLat=${currentLat}, currentLon=${currentLon}`);
      console.log(`Drone ${selectedDroneId} configuration: intendedNorth=${intendedNorth}, intendedEast=${intendedEast}`);

      // Make an API call to the backend to compute the origin
      const backendURL = getBackendURL(process.env.REACT_APP_FLASK_PORT || '5000');

      const requestData = {
        current_lat: currentLat,
        current_lon: currentLon,
        intended_east: intendedEast,
        intended_north: intendedNorth,
      };

      console.log('Sending /compute-origin request with data:', requestData);

      try {
        const response = await axios.post(`${backendURL}/compute-origin`, requestData);
        console.log('Received /compute-origin response:', response.data);

        if (response.data && typeof response.data.lat === 'number' && typeof response.data.lon === 'number') {
          setComputedOrigin({ lat: response.data.lat, lon: response.data.lon });
          setDroneError('');
          console.log('Computed origin set successfully:', response.data);
        } else if (response.data && response.data.error) {
          setDroneError(`Error from backend: ${response.data.error}`);
          console.error('Backend error:', response.data.error);
        } else {
          setDroneError('Error computing origin from backend.');
          console.error('Unexpected backend response:', response.data);
        }
      } catch (error) {
        console.error('Error computing origin from backend:', error);
        if (error.response && error.response.data && error.response.data.error) {
          setDroneError(`Error from backend: ${error.response.data.error}`);
        } else {
          setDroneError('Error computing origin from backend.');
        }
      } finally {
        setIsComputing(false);
      }
    };

    computeOrigin();
  }, [originMethod, selectedDroneId, configData, telemetryData]);

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Select Origin Coordinates</h3>
        <div className="origin-method-selection">
          <button
            className={`method-button ${originMethod === 'manual' ? 'active' : ''}`}
            onClick={() => {
              console.log('Switching origin method to manual.');
              setOriginMethod('manual');
              setErrors({});
              setSelectedDroneId('');
              setComputedOrigin(null);
              setDroneError('');
            }}
          >
            Enter Coordinates Manually
          </button>
          <button
            className={`method-button ${originMethod === 'drone' ? 'active' : ''}`}
            onClick={() => {
              console.log('Switching origin method to drone.');
              setOriginMethod('drone');
              setCoordinateInput('');
              setSelectedLatLon(null);
              setErrors({});
            }}
          >
            Use Drone as Reference
          </button>
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
                    console.log('Manual coordinate input changed:', e.target.value);
                    setCoordinateInput(e.target.value);
                    setSelectedLatLon(null); // Reset map selection
                  }}
                  placeholder='e.g., "35°24&#39;28.0&quot;N 50°09&#39;53.6&quot;E" or "35.4079, 50.1649"'                />
                {errors.input && <span className="error-message">{errors.input}</span>}
              </label>
            </div>
            <p className="or-text">OR</p>
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
                  console.log('Drone selection changed:', e.target.value);
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
            {isComputing && <p className="computing-message">Computing origin...</p>}
            {computedOrigin && (
              <div className="computed-origin">
                <p>Computed Origin:</p>
                <p>Latitude: {computedOrigin.lat.toFixed(8)}</p>
                <p>Longitude: {computedOrigin.lon.toFixed(8)}</p>
              </div>
            )}
          </div>
        )}

        <div className="modal-buttons">
          <button onClick={handleSubmit} className="ok-button" disabled={isComputing}>
            Set Origin
          </button>
          <button onClick={onClose} className="cancel-button" disabled={isComputing}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
};

export default OriginModal;
