// app/dashboard/drone-dashboard/src/components/MapSelector.js

import React, { useState } from 'react';
import '../styles/MapSelector.css';
import { MapContainer, TileLayer, Marker, useMapEvents } from 'react-leaflet';
import L from 'leaflet';
import MapLayerSwitcher from './MapLayerSwitcher'; // Import the MapLayerSwitcher

// Fix the default icon issue in Leaflet
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl:
    'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png',
  iconUrl:
    'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png',
  shadowUrl:
    'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png',
});

const MapSelector = ({ onSelect }) => {
  const [position, setPosition] = useState(null);
  const [selectedLayer, setSelectedLayer] = useState('OpenStreetMap');

  const layerUrls = {
    OpenStreetMap: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    Satellite: 'https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
    Terrain: 'https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
    // Add more layers as needed
  };

  const layerAttributions = {
    OpenStreetMap: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    Satellite: 'Map data &copy; <a href="https://www.google.com/intl/en-US_US/help/terms_maps.html">Google</a>',
    Terrain: '&copy; <a href="https://opentopomap.org/">OpenTopoMap</a> contributors',
    // Add more attributions as needed
  };

  const handleLayerChange = (layer) => {
    setSelectedLayer(layer);
  };

  const MapClickHandler = () => {
    useMapEvents({
      click(e) {
        setPosition(e.latlng);
        onSelect(e.latlng.lat, e.latlng.lng);
      },
    });
    return null;
  };

  return (
    <div className="map-container">
      <MapLayerSwitcher selectedLayer={selectedLayer} onLayerChange={handleLayerChange} />
      <MapContainer center={[35.6892, 51.3890]} zoom={6} maxZoom={30} style={{ height: '400px' }}>
        <TileLayer
          url={layerUrls[selectedLayer]}
          subdomains={selectedLayer === 'Satellite' ? ['mt0', 'mt1', 'mt2', 'mt3'] : undefined}
          attribution={layerAttributions[selectedLayer]}
        />
        <MapClickHandler />
        {position && <Marker position={position} />}
      </MapContainer>
    </div>
  );
};

export default MapSelector;
