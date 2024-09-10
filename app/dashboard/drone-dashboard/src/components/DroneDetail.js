import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MapContainer, TileLayer, Marker } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import '../styles/DroneDetail.css';
import { getBackendURL } from '../utilities/utilities';
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import { MAV_MODE_ENUM } from '../constants/mavModeEnum'; // Import MAV mode enumeration

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
    const backendURL = getBackendURL();
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

  // Determine color for stale data
  const dataStatusColor = isStale ? 'red' : 'green';

  // Determine Battery Voltage class based on value
  const getBatteryClass = (voltage) => {
    if (voltage >= 16) return 'green';
    if (voltage >= 14.8) return 'yellow';
    return 'red';
  };

  // Determine HDOP class based on value
  const getHdopClass = (hdop) => {
    if (hdop < 0.8) return 'green';
    if (hdop <= 1.0) return 'yellow';
    return 'red';
  };


  // Map MAV mode to informative name
  const mavModeName = MAV_MODE_ENUM[detailedDrone.Flight_Mode] || `Unknown (${detailedDrone.Flight_Mode})`;

  // Determine if the drone is armable based on MAV mode
  const isArmable = detailedDrone.Flight_Mode && detailedDrone.Flight_Mode !== 0; // Any mode except preflight should be armable
  const armableClass = isArmable ? 'armable' : 'not-armable';

  return (
    <div className="drone-detail">
      {!isAccordionView && (
        <h1>
          Drone Detail for HW_ID: {detailedDrone.hw_ID}
          <span style={{ color: dataStatusColor }}> ●</span>
        </h1>
      )}

      {/* Identifiers & Time */}
      <div className="detail-group">
        <p><strong>HW_ID:</strong> {detailedDrone.hw_ID}</p>
        <p><strong>Update Time:</strong> {new Date(detailedDrone.droneData.Update_Time * 1000).toLocaleString()}</p>
      </div>

      {/* Armable Status */}
      <div className="armable-status">
        <p><strong>Armable:</strong> 
          <span className={`armable-badge ${armableClass}`}>
            {isArmable ? 'Yes' : 'No'}
          </span>
        </p>
      </div>

      {/* MAV Mode & System Status Information */}
      <div className="detail-group">
        <p><strong>Mission:</strong> {detailedDrone.Mission}</p>
        <p><strong>Flight Mode:</strong> {getFlightModeTitle(detailedDrone.Flight_Mode)}</p>
        <p><strong>MAV Mode:</strong> {mavModeName}</p> {/* Display MAV mode */}
        <p><strong>State:</strong> {drone.State || 'Unknown'}</p>

        <p><strong>Follow Mode:</strong> {detailedDrone.Follow_Mode}</p>
      </div>

      {/* Positional Information */}
      <div className="detail-group">
        <p><strong>Altitude:</strong> {detailedDrone.Position_Alt.toFixed(1)}m</p>
        <p><strong>Latitude:</strong> {detailedDrone.Position_Lat}</p>
        <p><strong>Longitude:</strong> {detailedDrone.Position_Long}</p>
      </div>

      {/* Movement & Direction */}
      <div className="detail-group">
        <p><strong>Velocity North:</strong> {detailedDrone.Velocity_North.toFixed(1)}m/s</p>
        <p><strong>Velocity East:</strong> {detailedDrone.Velocity_East.toFixed(1)}m/s</p>
        <p><strong>Velocity Down:</strong> {detailedDrone.Velocity_Down.toFixed(1)}m/s</p>
        <p><strong>Yaw:</strong> {detailedDrone.Yaw.toFixed(0)}°</p>
      </div>

      {/* Battery & System Health */}
      <div className="detail-group">
        <p><strong>Battery Voltage:</strong> 
          <span className={getBatteryClass(detailedDrone.Battery_Voltage)}>
            {detailedDrone.Battery_Voltage.toFixed(1)}V
          </span>
        </p>
        <p><strong>HDOP:</strong> 
          <span className={getHdopClass(detailedDrone.Hdop)}>
            {detailedDrone.Hdop}
          </span>
        </p>
      </div>

      {/* Map Selection */}
      <div className="map-container">
        <select value={currentTileLayer} onChange={(e) => setCurrentTileLayer(e.target.value)} className="tile-layer-select">
          <option value="OSM">OpenStreetMap</option>
          <option value="OTM">OpenTopoMap</option>
          <option value="ESRI">Esri WorldStreetMap</option>
          <option value="STAMEN">Stamen Toner</option>
        </select>
        <div className="map-display">
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
              position={[detailedDrone.droneData.Position_Lat, detailedDrone.droneData.Position_Long]}
              icon={droneIcon}
            />
          </MapContainer>
        </div>
      </div>
    </div>
  );
};

export default DroneDetail;
