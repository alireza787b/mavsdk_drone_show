// src/components/MapSelector.js

import React, { useEffect, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  useMapEvents,
  Marker,
  Popup,
  LayersControl,
} from 'react-leaflet';
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
  // Default center: e.g., somewhere visible (Tokyo).
  const [mapCenter, setMapCenter] = useState({
    lat: initialPosition ? initialPosition.lat : 35.6895,
    lon: initialPosition ? initialPosition.lon : 139.6917,
  });

  // Prevent continuous recenter if user moves the map
  const [hasInteracted, setHasInteracted] = useState(false);

  function MapEvents() {
    const map = useMapEvents({
      click(e) {
        const { lat, lng } = e.latlng;
        onSelect({ lat, lon: lng });
      },
      moveend() {
        if (!hasInteracted) {
          setHasInteracted(true);
        }
      },
    });

    // Recenter on initial pos if user hasn't interacted
    useEffect(() => {
      if (initialPosition && !hasInteracted) {
        map.setView([initialPosition.lat, initialPosition.lon], map.getZoom(), {
          animate: false,
        });
      }
    }, [initialPosition, map, hasInteracted]);

    return null;
  }

  return (
    <div className="map-selector">
      <MapContainer
        center={[mapCenter.lat, mapCenter.lon]}
        zoom={13}
        scrollWheelZoom
        style={{ height: '300px', width: '100%' }}
      >
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="OpenStreetMap">
            <TileLayer
              attribution='&copy; <a href="https://osm.org/copyright">OSM</a>'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
          </LayersControl.BaseLayer>

          <LayersControl.BaseLayer name="OpenTopoMap">
            <TileLayer
              url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
              attribution="&copy; OpenTopoMap"
            />
          </LayersControl.BaseLayer>

          {/*
            "Google Satellite" is tricky, as official direct tiles from Google 
            are behind paywalls or usage restrictions. We'll use a known 
            'gdal2tiles' style server or fallback to an alternative satellite provider.
          */}
          <LayersControl.BaseLayer name="Satellite (gdal2tiles)">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="&copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Google Satellite">
            <TileLayer
              url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
              subdomains={['mt0', 'mt1', 'mt2', 'mt3']}
              attribution="Map data &copy; Google"
            />
        </LayersControl.BaseLayer>
        </LayersControl>

        <MapEvents />

        {/* Marker if there's an initial position */}
        {initialPosition && (
          <Marker position={[initialPosition.lat, initialPosition.lon]}>
            <Popup>Selected Location</Popup>
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
