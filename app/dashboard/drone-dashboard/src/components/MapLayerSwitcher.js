// app/dashboard/drone-dashboard/src/components/MapLayerSwitcher.js

import React from 'react';
import PropTypes from 'prop-types';
import '../styles/MapLayerSwitcher.css';

const MapLayerSwitcher = ({ selectedLayer, onLayerChange }) => {
  return (
    <div className="map-layer-switcher">
      <label htmlFor="mapLayerSelect" className="layer-label">
        Map Layer:
      </label>
      <select
        id="mapLayerSelect"
        value={selectedLayer}
        onChange={(e) => onLayerChange(e.target.value)}
        className="layer-select"
      >
        <option value="OpenStreetMap">OpenStreetMap</option>
        <option value="Satellite">Satellite</option>
        <option value="Terrain">Terrain</option>
        {/* Add more layers as needed */}
      </select>
    </div>
  );
};

MapLayerSwitcher.propTypes = {
  selectedLayer: PropTypes.string.isRequired,
  onLayerChange: PropTypes.func.isRequired,
};

export default MapLayerSwitcher;
