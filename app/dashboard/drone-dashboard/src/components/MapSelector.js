// src/components/MapSelector.js

import React, { useEffect, useState } from 'react';
import { useMapEvents, Marker, Popup } from 'react-leaflet';
import '../styles/MapSelector.css';
import PropTypes from 'prop-types';
import L from 'leaflet';
import icon from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';
import LeafletMapBase from './map/LeafletMapBase';

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

function MapEvents({ onSelect, initialPosition, hasInteracted, onFirstInteraction }) {
  const map = useMapEvents({
    click(e) {
      const { lat, lng } = e.latlng;
      onSelect({ lat, lon: lng });
    },
    moveend() {
      if (!hasInteracted) {
        onFirstInteraction();
      }
    },
  });

  useEffect(() => {
    if (initialPosition && !hasInteracted) {
      map.setView([initialPosition.lat, initialPosition.lon], map.getZoom(), {
        animate: true,
      });
    }
  }, [hasInteracted, initialPosition, map]);

  return null;
}

const MapSelector = ({ onSelect, initialPosition }) => {
  // Default center: e.g., somewhere visible (Tokyo).
  const [mapCenter] = useState({
    lat: initialPosition ? initialPosition.lat : 35.6895,
    lon: initialPosition ? initialPosition.lon : 139.6917,
  });

  // Prevent continuous recenter if user moves the map
  const [hasInteracted, setHasInteracted] = useState(false);

  return (
    <div className="map-selector">
      <LeafletMapBase
        center={[mapCenter.lat, mapCenter.lon]}
        zoom={13}
        className="map-selector-leaflet"
      >
        <MapEvents
          onSelect={onSelect}
          initialPosition={initialPosition}
          hasInteracted={hasInteracted}
          onFirstInteraction={() => setHasInteracted(true)}
        />

        {initialPosition && (
          <Marker position={[initialPosition.lat, initialPosition.lon]}>
            <Popup>Selected Location</Popup>
          </Marker>
        )}
      </LeafletMapBase>
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
