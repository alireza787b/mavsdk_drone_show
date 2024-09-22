// app/dashboard/drone-dashboard/src/components/OriginModal.js

import React, { useState } from 'react';
import '../styles/OriginModal.css';

const OriginModal = ({ isOpen, onClose, onSubmit }) => {
  const [localOriginLat, setLocalOriginLat] = useState('');
  const [localOriginLon, setLocalOriginLon] = useState('');
  const [errors, setErrors] = useState({});

  const validateInput = () => {
    const errors = {};
    if (isNaN(localOriginLat) || localOriginLat === '') {
      errors.lat = 'Please enter a valid latitude.';
    }
    if (isNaN(localOriginLon) || localOriginLon === '') {
      errors.lon = 'Please enter a valid longitude.';
    }
    setErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = () => {
    if (validateInput()) {
      onSubmit(localOriginLat, localOriginLon);
    }
  };

  if (!isOpen) return null;

  return (
    <div className="modal-overlay">
      <div className="modal">
        <h3>Enter Origin Coordinates</h3>
        <label>
          Origin Latitude:
          <input
            type="text"
            value={localOriginLat}
            onChange={(e) => setLocalOriginLat(e.target.value)}
            placeholder="Enter Origin Latitude"
          />
          {errors.lat && <span className="error-message">{errors.lat}</span>}
        </label>
        <label>
          Origin Longitude:
          <input
            type="text"
            value={localOriginLon}
            onChange={(e) => setLocalOriginLon(e.target.value)}
            placeholder="Enter Origin Longitude"
          />
          {errors.lon && <span className="error-message">{errors.lon}</span>}
        </label>
        <div className="modal-buttons">
          <button onClick={handleSubmit} className="ok-button">OK</button>
          <button onClick={onClose} className="cancel-button">Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default OriginModal;
