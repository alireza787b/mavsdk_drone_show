// src/components/map/MapProviderToggle.js
// Provider toggle — only visible when both providers are available

import React from 'react';
import { useMapContext } from '../../contexts/MapContext';
import { MAP_PROVIDERS } from '../../config/mapConfig';

const MapProviderToggle = () => {
  const { provider, setProvider, isMapboxAvailable, mapboxToken } = useMapContext();

  // Only show toggle when both providers are actually available
  if (!isMapboxAvailable || !mapboxToken) return null;

  return (
    <div className="mds-provider-toggle">
      <span>Map:</span>
      <select
        value={provider}
        onChange={(e) => setProvider(e.target.value)}
      >
        <option value={MAP_PROVIDERS.MAPBOX}>Mapbox</option>
        <option value={MAP_PROVIDERS.LEAFLET}>Leaflet Tiles</option>
      </select>
    </div>
  );
};

export default MapProviderToggle;
