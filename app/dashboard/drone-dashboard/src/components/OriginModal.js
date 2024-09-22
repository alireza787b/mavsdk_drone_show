// app/dashboard/drone-dashboard/src/components/OriginModal.js

import React, { useState } from 'react';
import '../styles/OriginModal.css';
import CoordinateParser from 'coordinate-parser';
import MapSelector from './MapSelector';

const OriginModal = ({ isOpen, onClose, onSubmit }) => {
  const [coordinateInput, setCoordinateInput] = useState('');
  const [errors, setErrors] = useState({});
  const [selectedLatLon, setSelectedLatLon] = useState(null);

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
    let result;
    if (selectedLatLon) {
      result = selectedLatLon;
    } else {
      result = validateInput();
    }
    if (result) {
      onSubmit(result.lat, result.lon);
    }
  };

  const handleMapSelect = (lat, lon) => {
    setSelectedLatLon({ lat, lon });
    setCoordinateInput(`${lat}, ${lon}`);
    setErrors({});
  };

  const getCurrentLocation = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const lat = position.coords.latitude;
          const lon = position.coords.longitude;
          setSelectedLatLon({ lat, lon });
          setCoordinateInput(`${lat}, ${lon}`);
          setErrors({});
        },
        (error) => {
          setErrors({ input: 'Unable to retrieve your location.' });
        }
      );
    } else {
      setErrors({ input: 'Geolocation is not supported by this browser.' });
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Select Origin Coordinates</h3>
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
          <button onClick={getCurrentLocation}>Use Current Location</button>
        </div>
        <MapSelector onSelect={handleMapSelect} />
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
