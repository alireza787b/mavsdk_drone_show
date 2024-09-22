// app/dashboard/drone-dashboard/src/components/DronePositionMap.js

import React, { useEffect, useState } from 'react';
import '../styles/DronePositionMap.css';
import { MapContainer, TileLayer, Marker, Popup } from 'react-leaflet';
import L from 'leaflet';
import LatLon from 'geodesy/latlon-spherical';

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
    if (originLat && originLon && drones.length > 0) {
      // Convert drones' x, y positions to latitude and longitude
      const origin = new LatLon(parseFloat(originLat), parseFloat(originLon));

      const positions = drones.map((drone) => {
        const x = parseFloat(drone.x); // Easting
        const y = parseFloat(drone.y); // Northing

        // Calculate the bearing and distance
        const distance = Math.sqrt(x * x + y * y);
        const bearing = (Math.atan2(x, y) * 180) / Math.PI; // Convert from radians to degrees

        // Destination point given distance and bearing from origin
        const destination = origin.destinationPoint(distance, bearing);

        return {
          hw_id: drone.hw_id,
          pos_id: drone.pos_id,
          lat: destination.lat,
          lon: destination.lon,
        };
      });

      setDronePositions(positions);
    }
  }, [originLat, originLon, drones]);

  if (!originLat || !originLon) {
    return <p>Please set the origin coordinates to view the drone positions on the map.</p>;
  }

  if (dronePositions.length === 0) {
    return <p>No drone positions available to display on the map.</p>;
  }

  // Calculate the map center as the average of drone positions
  const avgLat =
    dronePositions.reduce((sum, drone) => sum + drone.lat, 0) / dronePositions.length;
  const avgLon =
    dronePositions.reduce((sum, drone) => sum + drone.lon, 0) / dronePositions.length;

  return (
    <div className="drone-position-map">
      <h3>Drone Positions on Map</h3>
      <MapContainer center={[avgLat, avgLon]} zoom={20} style={{ height: '400px' }}>
        <TileLayer
          url="https://{s}.google.com/vt/lyrs=s&x={x}&y={y}&z={z}"
          subdomains={['mt0', 'mt1', 'mt2', 'mt3']}
          attribution="Map data &copy; Google"
        />

        {/* <TileLayer
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution="Map data &copy; OpenStreetMap contributors"
        // You can replace the URL with a satellite imagery provider
        /> */}

        {dronePositions.map((drone) => (
          <Marker key={drone.hw_id} position={[drone.lat, drone.lon]}>
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
