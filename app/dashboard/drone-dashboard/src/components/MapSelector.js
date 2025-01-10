// app/dashboard/drone-dashboard/src/components/MapSelector.js
import React, { useEffect } from 'react';
import { MapContainer, TileLayer, useMapEvents, Marker, Popup, LayersControl } from 'react-leaflet';
import '../styles/MapSelector.css';
import PropTypes from 'prop-types';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

// Fix Leaflet's default icon paths
delete L.Icon.Default.prototype._getIconUrl;

L.Icon.Default.mergeOptions({
  iconUrl: icon,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowUrl: iconShadow,
  shadowSize: [41, 41],
});

const MapSelector = ({ onSelect, initialPosition }) => {
  const position = initialPosition || { lat: 35.6895, lon: 139.6917 }; // Default to Tokyo if no initial position

  // Flag to prevent map from continuously recentering once user has interacted
  const [hasInteracted, setHasInteracted] = React.useState(false);

  function MapEvents() {
    const map = useMapEvents({
      click(event) {
        const { lat, lng } = event.latlng;
        onSelect({ lat, lon: lng });
      },
      moveend() {
        if (!hasInteracted) {
          setHasInteracted(true); // User has interacted with the map
        }
      }
    });

    // Only recenter map if position is updated and no prior interaction occurred
    useEffect(() => {
      if (initialPosition && !hasInteracted) {
        map.setView([initialPosition.lat, initialPosition.lon], map.getZoom(), { animate: false });
      }
    }, [initialPosition, map, hasInteracted]);

    return null;
  }

  return (
    <div className="map-selector">
      <MapContainer
        center={[position.lat, position.lon]}
        zoom={13}
        scrollWheelZoom={true}  // Enable scroll zoom
        style={{ height: '300px', width: '100%' }}
      >
        {/* Layers Control (Satellite and Standard Map) */}
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Open Street Satellite">
            <TileLayer
              url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://opentopomap.org/copyright">OpenTopoMap</a>'
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Google Satellite">
            <TileLayer
              url="https://{s}.google.com/maps/vt?lyrs=s&x={x}&y={y}&z={z}"
              attribution='&copy; <a href="https://google.com">Google</a>'
            />
          </LayersControl.BaseLayer>
        </LayersControl>

        {/* Map Events */}
        <MapEvents />

        {/* Marker that reflects selected position */}
        {initialPosition && (
          <Marker position={[initialPosition.lat, initialPosition.lon]}>
            <Popup>
              <span>Selected Location</span>
            </Popup>
          </Marker>
        )}
      </MapContainer>
    </div>
  );
};

MapSelector.propTypes = {
  onSelect: PropTypes.func.isRequired,
  initialPosition: PropTypes.shape({
    lat: PropTypes.number.isRequired,
    lon: PropTypes.number.isRequired,
  }),
};

export default MapSelector;
