import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MapContainer, TileLayer, Marker } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import '../styles/DroneDetail.css';
import { getBackendURL } from '../utilities'; // Adjust the path if needed


const POLLING_RATE_HZ = 2;
const STALE_DATA_THRESHOLD_SECONDS = 5;

const droneIcon = new L.Icon({
  iconUrl: '/drone-marker.png',
  iconSize: [40, 50],
});

const DroneDetail = ({ drone, isAccordionView }) => {
  const [detailedDrone, setDetailedDrone] = useState(drone);
  const [isStale, setIsStale] = useState(false);
  const [currentTileLayer, setCurrentTileLayer] = useState('OSM');

  useEffect(() => {
    const backendURL = getBackendURL(); // Get the dynamic backend URL
    const url = `${backendURL}/telemetry`;
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
            <h1>
                Drone Detail for HW_ID: {detailedDrone.hw_ID}
                <span style={{ color: isStale ? 'red' : 'green' }}>●</span>
            </h1>
        )}

        {/* Identifiers & Time */}
        <p>HW_ID: {detailedDrone.hw_ID}</p>
        <p>Update Time (UNIX): {detailedDrone.Update_Time}</p>
        <p>Update Time (Local): {new Date(detailedDrone.Update_Time * 1000).toLocaleString()}</p>

        {/* Mission & Status Information */}
        <p>Mission: {detailedDrone.Mission}</p>
        <p>State: {detailedDrone.State}</p>
        <p>Follow Mode: {detailedDrone.Follow_Mode}</p>

        {/* Positional Information */}
        <p>Altitude: {detailedDrone.Position_Alt.toFixed(1)}m</p>
        <p>Latitude: {detailedDrone.Position_Lat}</p>
        <p>Longitude: {detailedDrone.Position_Long}</p>

            {/* Movement & Direction */}
        <p>Velocity North: {detailedDrone.Velocity_North.toFixed(1)}m/s</p>
        <p>Velocity East: {detailedDrone.Velocity_East.toFixed(1)}m/s</p>
        <p>Velocity Down: {detailedDrone.Velocity_Down.toFixed(1)}m/s</p>
        <p>Yaw: {detailedDrone.Yaw.toFixed(0)}°</p>

           {/* Battery & System Health */}
        <p>Battery Voltage: {detailedDrone.Battery_Voltage.toFixed(1)}V</p>
        <select value={currentTileLayer} onChange={(e) => setCurrentTileLayer(e.target.value)}>
          <option value="OSM">OpenStreetMap</option>
          <option value="OTM">OpenTopoMap</option>
          <option value="ESRI">Esri WorldStreetMap</option>
          <option value="STAMEN">Stamen Toner</option>
        </select>
        <div style={{ height: '300px', width: '300px' }}>
        

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