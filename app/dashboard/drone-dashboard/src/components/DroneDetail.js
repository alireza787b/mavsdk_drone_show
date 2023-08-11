import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MapContainer, TileLayer, Marker } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';

const POLLING_RATE_HZ = 2;
const STALE_DATA_THRESHOLD_SECONDS = 5;

const droneIcon = new L.Icon({
  iconUrl: '/drone-marker.png',
  iconSize: [40, 50],
});

const DroneDetail = ({ drone, goBack, isAccordionView }) => {
  const [detailedDrone, setDetailedDrone] = useState(drone);
  const [isStale, setIsStale] = useState(false);
  const [currentTileLayer, setCurrentTileLayer] = useState('OSM');

  useEffect(() => {
    const url = 'http://127.0.0.1:5000/telemetry';
    const fetchData = () => {
      axios.get(url).then((response) => {
        const droneData = response.data[drone.hw_ID];
        if (droneData) {
          setDetailedDrone({
            hw_ID: drone.hw_ID,
            ...droneData,
          });
          const currentTime = Math.floor(Date.now() / 1000);
          const isDataStale = currentTime - droneData.Update_Time > STALE_DATA_THRESHOLD_SECONDS;
          setIsStale(isDataStale);
        }
      }).catch((error) => {
        console.error('Network Error:', error);
      });
    };
    fetchData();
    const pollingInterval = setInterval(fetchData, 1000 / POLLING_RATE_HZ);
    return () => {
      clearInterval(pollingInterval);
    };
  }, [drone.hw_ID]);

  return (
    <div>
      {!isAccordionView && (
        <>
          <button onClick={goBack}>Return to Overview</button>
          <h1>
            Drone Detail for HW_ID: {detailedDrone.hw_ID}
            <span style={{ color: isStale ? 'red' : 'green' }}>
              ●
            </span>
          </h1>
        </>
      )}
      <p>Update Time (UNIX): {detailedDrone.Update_Time}</p>
      <p>Update Time (Local): {new Date(detailedDrone.Update_Time * 1000).toLocaleString()}</p>
      <p>Mission: {detailedDrone.Mission}</p>
      <p>State: {detailedDrone.State}</p>
      <p>Altitude: {detailedDrone.Position_Alt.toFixed(1)}</p>
      <p>Latitude: {detailedDrone.Position_Lat}</p>
      <p>Longitude: {detailedDrone.Position_Long}</p>
      <p>Velocity North: {detailedDrone.Velocity_North.toFixed(1)}</p>
      <p>Velocity East: {detailedDrone.Velocity_East.toFixed(1)}</p>
      <p>Velocity Down: {detailedDrone.Velocity_Down.toFixed(1)}</p>
      <p>Yaw: {detailedDrone.Yaw.toFixed(0)}</p>
      <p>Battery Voltage: {detailedDrone.Battery_Voltage.toFixed(1)}</p>
      <p>Follow Mode: {detailedDrone.Follow_Mode}</p>
      {/* Add more details as needed */}

      <div style={{ height: '300px', width: '300px' }}>
        <select value={currentTileLayer} onChange={(e) => setCurrentTileLayer(e.target.value)}>
          <option value="OSM">OpenStreetMap</option>
          <option value="OTM">OpenTopoMap</option>
          <option value="ESRI">Esri WorldStreetMap</option>
          <option value="STAMEN">Stamen Toner</option>
        </select>
        <MapContainer 
          center={[detailedDrone.Position_Lat, detailedDrone.Position_Long]} 
          zoom={13} 
          style={{ height: '100%', width: '100%' }}
        >
          {currentTileLayer === 'OSM' && (
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            />
          )}
          {currentTileLayer === 'OTM' && (
            <TileLayer
              url="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
              attribution='&copy; OpenTopoMap contributors'
            />
          )}
          {currentTileLayer === 'ESRI' && (
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
              attribution='&copy; Esri'
            />
          )}
          {currentTileLayer === 'STAMEN' && (
            <TileLayer
              url="https://stamen-tiles-{s}.a.ssl.fastly.net/toner/{z}/{x}/{y}{r}.png"
              attribution='Map tiles by Stamen Design, CC BY 3.0 — Map data &copy; OpenStreetMap'
            />
          )}
          <Marker 
            position={[detailedDrone.Position_Lat, detailedDrone.Position_Long]} 
            icon={droneIcon}
          />
        </MapContainer>
      </div>
    </div>
  );
};

export default DroneDetail;