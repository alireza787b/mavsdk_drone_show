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

const MapSelector = ({ onSelect, initialPosition }) => {
  // Initialize position to [0, 0] if not provided
  const [position, setPosition] = React.useState(initialPosition ? [initialPosition.lat, initialPosition.lon] : [0, 0]);

  // Update position only if initialPosition changes and is different from current position
  React.useEffect(() => {
    if (initialPosition && (position[0] !== initialPosition.lat || position[1] !== initialPosition.lon)) {
      setPosition([initialPosition.lat, initialPosition.lon]);
      onSelect(initialPosition); // Only call onSelect if the position is actually updated
    }
  }, [initialPosition, position, onSelect]);

  const LocationMarker = () => {
    const map = useMapEvents({
      click(e) {
        const { lat, lng } = e.latlng;
        setPosition([lat, lng]);
        onSelect({ lat, lon: lng });
      },
    });

    // Adjust the map's center to the marker's position when the position changes
    React.useEffect(() => {
      if (map && position) {
        map.setView(position, map.getZoom(), {
          animate: true,
        });
      }
    }, [position, map]);

    return position === null ? null : (
      <Marker position={position}>
        <Popup>
          Selected Origin: <br /> Lat: {position[0].toFixed(6)}, Lon: {position[1].toFixed(6)}
        </Popup>
      </Marker>
    );
  };

  return (
    <MapContainer 
      center={position} // Dynamically set the center to position
      zoom={5} 
      scrollWheelZoom={true} 
      className="map-selector-container"
    >
      <LayersControl position="topright">
        <BaseLayer name="Google Satellite" checked>
          <TileLayer
            url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
            subdomains={['mt0', 'mt1', 'mt2', 'mt3']}
            attribution="Map data &copy; Google"
          />
        </BaseLayer>
        <BaseLayer name="OpenStreetMap">
          <TileLayer
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            attribution="Map data &copy; OpenStreetMap contributors"
            maxZoom={18}
          />
        </BaseLayer>
      </LayersControl>
      <LocationMarker />
    </MapContainer>
  );
};

MapSelector.propTypes = {
  onSelect: PropTypes.func.isRequired,
  initialPosition: PropTypes.shape({ 
    lat: PropTypes.number,
    lon: PropTypes.number,
  }),
};

export default MapSelector;
