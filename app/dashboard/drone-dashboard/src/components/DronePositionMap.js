// src/components/DronePositionMap.js

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

const DronePositionMap = ({ originLat, originLon, drones, forwardHeading = 0 }) => {
  const [dronePositions, setDronePositions] = useState([]);

  useEffect(() => {
    const isValidNumber = (value) => !isNaN(value) && isFinite(value);

    if (originLat && originLon && drones.length > 0) {
      const parsedOriginLat = parseFloat(originLat);
      const parsedOriginLon = parseFloat(originLon);

      if (!isValidNumber(parsedOriginLat) || !isValidNumber(parsedOriginLon)) {
        console.error('Invalid origin coordinates:', { originLat, originLon });
        return;
      }

      const origin = new LatLon(parsedOriginLat, parsedOriginLon);

      const positions = drones
        .map((drone) => {
          const x = parseFloat(drone.x); // north
          const y = parseFloat(drone.y); // east
          if (!isValidNumber(x) || !isValidNumber(y)) {
            // Silently skip drones without x,y coords (positions should come from trajectory CSV)
            return null;
          }

          // Distance in meters from origin
          const distance = Math.sqrt(x * x + y * y);

          // Base bearing from origin if heading=0 (y -> east, x -> north):
          let rawBearingDeg = (Math.atan2(y, x) * 180) / Math.PI; // east=90°, north=0
          if (rawBearingDeg < 0) {
            rawBearingDeg += 360;
          }

          let finalBearing = rawBearingDeg + forwardHeading;
          finalBearing %= 360;

          let destination;
          try {
            destination = origin.destinationPoint(distance, finalBearing);
          } catch (error) {
            console.error(
              `Error calculating destination for drone hw_id=${drone.hw_id}:`,
              error
            );
            return null;
          }

          return destination
            ? {
                hw_id: drone.hw_id,
                pos_id: drone.pos_id,
                lat: destination.lat,
                lon: destination.lon,
              }
            : null;
        })
        .filter((pos) => pos !== null);

      setDronePositions(positions);
    } else {
      setDronePositions([]);
    }
  }, [originLat, originLon, drones, forwardHeading]);

  if (!originLat || !originLon) {
    return <p>Please set the origin coordinates to view the drone positions on the map.</p>;
  }

  if (dronePositions.length === 0) {
    return <p>No drone positions available to display on the map.</p>;
  }

  const avgLat = dronePositions.reduce((sum, d) => sum + d.lat, 0) / dronePositions.length;
  const avgLon = dronePositions.reduce((sum, d) => sum + d.lon, 0) / dronePositions.length;

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
      <h3>Drone Positions on Map (Heading = {forwardHeading}°)</h3>
      <MapContainer center={[avgLat, avgLon]} zoom={16} maxZoom={22} scrollWheelZoom>
        <LayersControl position="topright">
          <BaseLayer checked name="Satellite">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="&copy; Esri &mdash; Esri, DeLorme, NAVTEQ"
            />
          </BaseLayer>
          <BaseLayer name="OpenStreetMap">
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://osm.org/copyright">OSM</a>'
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
