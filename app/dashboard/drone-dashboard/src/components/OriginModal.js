// app/dashboard/drone-dashboard/src/components/OriginModal.js

import React, { useState } from 'react';

const OriginModal = ({ isOpen, onClose, onSubmit }) => {
  const [localOriginLat, setLocalOriginLat] = useState('');
  const [localOriginLon, setLocalOriginLon] = useState('');

  const handleSubmit = () => {
    if (isNaN(localOriginLat) || isNaN(localOriginLon)) {
      alert('Origin latitude and longitude must be valid numbers.');
      return;
    }
    onSubmit(localOriginLat, localOriginLon);
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
        </label>
        <label>
          Origin Longitude:
          <input
            type="text"
            value={localOriginLon}
            onChange={(e) => setLocalOriginLon(e.target.value)}
            placeholder="Enter Origin Longitude"
          />
        </label>
        <div className="modal-buttons">
          <button onClick={handleSubmit}>OK</button>
          <button onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
};

export default OriginModal;
