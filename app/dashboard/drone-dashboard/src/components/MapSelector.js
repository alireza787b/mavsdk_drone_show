// src/components/MapSelector.js

import React from 'react';
import { MapContainer, TileLayer, useMapEvents, Marker, Popup } from 'react-leaflet';
import '../styles/MapSelector.css';
import PropTypes from 'prop-types';

const MapSelector = ({ onSelect }) => {
  const [position, setPosition] = React.useState(null);

  const LocationMarker = () => {
    useMapEvents({
      click(e) {
        const { lat, lng } = e.latlng;
        setPosition([lat, lng]);
        onSelect({ lat, lon: lng });
      },
    });

    return position === null ? null : (
      <Marker position={position}>
        <Popup>
          Selected Origin: <br /> Lat: {position[0].toFixed(6)}, Lon: {position[1].toFixed(6)}
        </Popup>
      </Marker>
    );
  };

  return (
    <MapContainer center={[0, 0]} zoom={2} scrollWheelZoom={true} className="map-selector-container">
      <TileLayer
        attribution='&copy; <a href="http://osm.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <LocationMarker />
    </MapContainer>
  );
};

MapSelector.propTypes = {
  onSelect: PropTypes.func.isRequired,
};

export default MapSelector;
