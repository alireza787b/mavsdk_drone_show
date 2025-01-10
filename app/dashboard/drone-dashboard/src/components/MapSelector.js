import React from 'react';
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
  shadowUrl: iconShadow,
});

const { BaseLayer } = LayersControl;

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
    <MapContainer center={[0, 0]} zoom={5} scrollWheelZoom={true} className="map-selector-container">
      <LayersControl position="topright">
        <BaseLayer checked name="Default">
          <TileLayer
            attribution='&copy; <a href="http://osm.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
        </BaseLayer>
        <BaseLayer name="Satellite">
          <TileLayer
            attribution='&copy; <a href="https://www.mapbox.com/">Mapbox</a>'
            url="https://api.mapbox.com/styles/v1/mapbox/satellite-v9/tiles/{z}/{x}/{y}?access_token=YOUR_MAPBOX_ACCESS_TOKEN"
          />
        </BaseLayer>
      </LayersControl>
      <LocationMarker />
    </MapContainer>
  );
};

MapSelector.propTypes = {
  onSelect: PropTypes.func.isRequired,
};

export default MapSelector;
