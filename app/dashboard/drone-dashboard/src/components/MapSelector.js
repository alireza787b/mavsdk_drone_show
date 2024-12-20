// app/dashboard/drone-dashboard/src/components/MapSelector.js

import React, { useState } from 'react';
import '../styles/MapSelector.css';
import { MapContainer, TileLayer, Marker, Popup, LayersControl, useMapEvents } from 'react-leaflet';
import L from 'leaflet';

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
  const [userPosition, setUserPosition] = useState(null);

  const getCurrentPosition = () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude } = position.coords;
          setUserPosition([latitude, longitude]);
          setPosition([latitude, longitude]);
        },
        (error) => {
          console.error("Error getting user location:", error);
        }
      );
    } else {
      alert("Geolocation is not supported by this browser.");
    }
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
      <button onClick={getCurrentPosition} style={{ marginBottom: '10px' }}>
        Show My Location
      </button>
      <MapContainer center={[35.6892, 51.3890]} zoom={6} maxZoom={22} style={{ height: '400px' }}>
        <LayersControl position="topright">
          <LayersControl.BaseLayer name="Google Satellite" checked>
            <TileLayer
              url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
              subdomains={['mt0', 'mt1', 'mt2', 'mt3']}
              attribution="Map data &copy; Google"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="OpenStreetMap">
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution="Map data &copy; OpenStreetMap contributors"
              maxZoom={18} // Set appropriate max zoom for OSM
            />
          </LayersControl.BaseLayer>
        </LayersControl>

        {userPosition && (
          <Marker position={userPosition}>
            <Popup>You are here!</Popup>
          </Marker>
        )}

        <MapClickHandler />
        
        {position && <Marker position={position} />}
      </MapContainer>
    </div>
  );
};

export default MapSelector;