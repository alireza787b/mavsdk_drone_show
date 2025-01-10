import React, { useEffect, useState } from 'react';
import '../styles/DronePositionMap.css';
import { MapContainer, TileLayer, Marker, Popup, LayersControl } from 'react-leaflet';
import L from 'leaflet';
import LatLon from 'geodesy/latlon-spherical';

const { BaseLayer } = LayersControl;

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

const DronePositionMap = ({ originLat, originLon, drones }) => {
  const [dronePositions, setDronePositions] = useState([]);

  useEffect(() => {
    // Helper function to check if a value is a valid number
    const isValidNumber = (value) => !isNaN(value) && isFinite(value);

    if (originLat && originLon && drones.length > 0) {
      const parsedOriginLat = parseFloat(originLat);
      const parsedOriginLon = parseFloat(originLon);

      if (!isValidNumber(parsedOriginLat) || !isValidNumber(parsedOriginLon)) {
        console.error('Invalid origin coordinates:', { originLat, originLon });
        return;
      }

      const origin = new LatLon(parsedOriginLat, parsedOriginLon);

      const positions = drones.map((drone) => {
        const x = parseFloat(drone.x);
        const y = parseFloat(drone.y);

        if (!isValidNumber(x) || !isValidNumber(y)) {
          console.error(`Invalid drone coordinates for drone ${drone.hw_id}:`, { x, y });
          return null; // Skip this drone
        }

        const distance = Math.sqrt(x * x + y * y); // Ensure distance is in meters
        const bearing = (Math.atan2(y, x) * 180) / Math.PI;

        // Validate distance and bearing
        if (!isValidNumber(distance) || !isValidNumber(bearing)) {
          console.error(`Invalid distance or bearing for drone ${drone.hw_id}:`, { distance, bearing });
          return null; // Skip this drone
        }

        let destination;
        try {
          destination = origin.destinationPoint(distance, bearing);
        } catch (error) {
          console.error(`Error calculating destination for drone ${drone.hw_id}:`, error);
          return null; // Skip this drone
        }

        if (!destination || !isValidNumber(destination.lat) || !isValidNumber(destination.lon)) {
          console.error(`Invalid destination coordinates for drone ${drone.hw_id}:`, destination);
          return null; // Skip this drone
        }

        return {
          hw_id: drone.hw_id,
          pos_id: drone.pos_id,
          lat: destination.lat,
          lon: destination.lon,
        };
      }).filter(position => position !== null); // Remove any null entries

      setDronePositions(positions);
    }
  }, [originLat, originLon, drones]);

  if (!originLat || !originLon) {
    return <p>Please set the origin coordinates to view the drone positions on the map.</p>;
  }

  if (dronePositions.length === 0) {
    return <p>No drone positions available to display on the map.</p>;
  }

  const avgLat =
    dronePositions.reduce((sum, drone) => sum + drone.lat, 0) / dronePositions.length;
  const avgLon =
    dronePositions.reduce((sum, drone) => sum + drone.lon, 0) / dronePositions.length;

  const createCustomIcon = (pos_id) => {
    return L.divIcon({
      html: `<div class="custom-marker">${pos_id}</div>`,
      className: 'custom-icon',
      iconSize: [20, 20],
      iconAnchor: [10, 10],
    });
  };

  return (
    <div className="drone-position-map">
      <h3>Drone Positions on Map</h3>
      <MapContainer center={[avgLat, avgLon]} zoom={16} maxZoom={22} style={{ height: '400px' }}>

        <LayersControl position="topright">
          <LayersControl.BaseLayer name="OpenStreetMap">
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
          <LayersControl.BaseLayer checked name="Satellite (gdal2tiles)">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="&copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
            />
          </LayersControl.BaseLayer>
          <BaseLayer name="Google Satellite" checked>
            <TileLayer
              url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
              subdomains={['mt0', 'mt1', 'mt2', 'mt3']}
              attribution="Map data &copy; Google"
            />
          </BaseLayer>
        </LayersControl>

        {dronePositions.map((drone) => (
          <Marker
            key={drone.hw_id}
            position={[drone.lat, drone.lon]}
            icon={createCustomIcon(drone.pos_id)}
          >
            <Popup>
              <strong>Hardware ID:</strong> {drone.hw_id}
              <br />
              <strong>Position ID:</strong> {drone.pos_id}
              <br />
              <strong>Latitude:</strong> {drone.lat.toFixed(6)}
              <br />
              <strong>Longitude:</strong> {drone.lon.toFixed(6)}
            </Popup>
          </Marker>
        ))}
      </MapContainer>
    </div>
  );
};

export default DronePositionMap;
