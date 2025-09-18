import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { MapContainer, TileLayer, Marker } from 'react-leaflet';
import { FaMapMarkerAlt, FaWifi, FaClock, FaBatteryFull, FaCompass, FaSatellite, FaPlane, FaCog, FaNetworkWired } from 'react-icons/fa';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import '../styles/DroneDetail.css';
import { getBackendURL } from '../utilities/utilities';
import { getFlightModeTitle, getSystemStatusTitle, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName } from '../constants/droneStates';
import { getFriendlyMissionName } from '../utilities/missionUtils';

const POLLING_RATE_HZ = 2;
const STALE_DATA_THRESHOLD_SECONDS = 5;

const droneIcon = new L.Icon({
  iconUrl: '/drone-marker.png',
  iconSize: [40, 50],
});

/**
 * Professional Drone Detail Component
 * Comprehensive operational and technical data display for drone show operations
 */
const DroneDetail = ({ drone, isAccordionView }) => {
  const [detailedDrone, setDetailedDrone] = useState(drone);
  const [isStale, setIsStale] = useState(false);
  const [currentTileLayer, setCurrentTileLayer] = useState('OSM');
  const [activeTab, setActiveTab] = useState('overview');

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

  // Status assessment functions
  const getStatusColor = (isStale) => isStale ? '#e53e3e' : '#38a169';

  const getBatteryStatus = (voltage) => {
    if (voltage >= 16.0) return { class: 'excellent', color: '#38a169', label: 'Excellent' };
    if (voltage >= 15.5) return { class: 'good', color: '#68d391', label: 'Good' };
    if (voltage >= 14.5) return { class: 'warning', color: '#f6ad55', label: 'Warning' };
    return { class: 'critical', color: '#e53e3e', label: 'Critical' };
  };

  const getGpsStatus = (fixType, hdop, satellites) => {
    if (fixType >= 5) return { class: 'rtk', color: '#805ad5', label: 'RTK' };
    if (fixType === 4) return { class: 'dgps', color: '#3182ce', label: 'DGPS' };
    if (fixType === 3 && hdop <= 1.0) return { class: 'good', color: '#38a169', label: '3D Fix (Good)' };
    if (fixType === 3) return { class: 'fair', color: '#f6ad55', label: '3D Fix (Fair)' };
    if (fixType === 2) return { class: 'poor', color: '#e53e3e', label: '2D Fix' };
    return { class: 'none', color: '#a0aec0', label: 'No Fix' };
  };

  const getConnectionStatus = () => {
    const now = Date.now();
    const lastSeen = detailedDrone.Heartbeat_Last_Seen || 0;
    const timeDiff = (now - lastSeen) / 1000;

    if (timeDiff < 5) return { class: 'excellent', color: '#38a169', label: 'Live' };
    if (timeDiff < 15) return { class: 'good', color: '#f6ad55', label: 'Recent' };
    return { class: 'poor', color: '#e53e3e', label: 'Stale' };
  };

  const formatTime = (timestamp) => {
    if (!timestamp) return 'N/A';
    return new Date(timestamp).toLocaleTimeString();
  };

  const formatDuration = (seconds) => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hours > 0) return `${hours}h ${minutes}m ${secs}s`;
    if (minutes > 0) return `${minutes}m ${secs}s`;
    return `${secs}s`;
  };

  // Data processing
  const flightModeName = getFlightModeTitle(detailedDrone.Flight_Mode);
  const flightModeCategory = getFlightModeCategory(detailedDrone.Flight_Mode);
  const systemStatusName = getSystemStatusTitle(detailedDrone.System_Status);
  const missionStateName = getDroneShowStateName(detailedDrone.State);
  const friendlyMissionName = getFriendlyMissionName(detailedDrone.lastMission);

  const isArmed = detailedDrone.Is_Armed || false;
  const isReadyToArm = detailedDrone.Is_Ready_To_Arm || false;

  const batteryStatus = getBatteryStatus(detailedDrone.Battery_Voltage || 0);
  const gpsStatus = getGpsStatus(
    detailedDrone.Gps_Fix_Type || 0,
    detailedDrone.Hdop || 99.99,
    detailedDrone.Satellites_Visible || 0
  );
  const connectionStatus = getConnectionStatus();

  // Calculate uptime
  const firstSeen = detailedDrone.Heartbeat_First_Seen || 0;
  const uptime = firstSeen > 0 ? (Date.now() / 1000) - firstSeen : 0;

  // Calculate speed
  const groundSpeed = Math.sqrt(
    Math.pow(detailedDrone.Velocity_North || 0, 2) +
    Math.pow(detailedDrone.Velocity_East || 0, 2)
  );

  const renderOverviewTab = () => (
    <div className="detail-content">
      {/* Status Dashboard */}
      <div className="status-dashboard">
        <div className="status-card">
          <div className="status-icon">
            <FaPlane style={{ color: isArmed ? '#e53e3e' : '#38a169' }} />
          </div>
          <div className="status-info">
            <div className="status-label">Armed Status</div>
            <div className={`status-value ${isArmed ? 'armed' : 'disarmed'}`}>
              {isArmed ? 'ARMED' : 'DISARMED'}
            </div>
            <div className="status-sub">
              Ready: {isReadyToArm ? 'Yes' : 'No'}
            </div>
          </div>
        </div>

        <div className="status-card">
          <div className="status-icon">
            <FaBatteryFull style={{ color: batteryStatus.color }} />
          </div>
          <div className="status-info">
            <div className="status-label">Battery</div>
            <div className="status-value">{(detailedDrone.Battery_Voltage || 0).toFixed(1)}V</div>
            <div className="status-sub" style={{ color: batteryStatus.color }}>
              {batteryStatus.label}
            </div>
          </div>
        </div>

        <div className="status-card">
          <div className="status-icon">
            <FaSatellite style={{ color: gpsStatus.color }} />
          </div>
          <div className="status-info">
            <div className="status-label">GPS Status</div>
            <div className="status-value">{detailedDrone.Satellites_Visible || 0} Sats</div>
            <div className="status-sub" style={{ color: gpsStatus.color }}>
              {gpsStatus.label}
            </div>
          </div>
        </div>

        <div className="status-card">
          <div className="status-icon">
            <FaWifi style={{ color: connectionStatus.color }} />
          </div>
          <div className="status-info">
            <div className="status-label">Connection</div>
            <div className="status-value">{detailedDrone.IP || 'N/A'}</div>
            <div className="status-sub" style={{ color: connectionStatus.color }}>
              {connectionStatus.label}
            </div>
          </div>
        </div>
      </div>

      {/* Flight Information */}
      <div className="detail-section">
        <h3><FaPlane /> Flight Information</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>Flight Mode</label>
            <span className={`flight-mode ${flightModeCategory}`}>{flightModeName}</span>
          </div>
          <div className="detail-item">
            <label>System Status</label>
            <span>{systemStatusName}</span>
          </div>
          <div className="detail-item">
            <label>Mission State</label>
            <span>{missionStateName}</span>
          </div>
          <div className="detail-item">
            <label>Current Mission</label>
            <span>{detailedDrone.Mission || 'None'}</span>
          </div>
          <div className="detail-item">
            <label>Last Mission</label>
            <span>{friendlyMissionName}</span>
          </div>
          <div className="detail-item">
            <label>Follow Mode</label>
            <span>{detailedDrone.Follow_Mode || '0'}</span>
          </div>
        </div>
      </div>

      {/* Position & Movement */}
      <div className="detail-section">
        <h3><FaMapMarkerAlt /> Position & Movement</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>Altitude</label>
            <span>{(detailedDrone.Position_Alt || 0).toFixed(1)} m</span>
          </div>
          <div className="detail-item">
            <label>Ground Speed</label>
            <span>{groundSpeed.toFixed(1)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Vertical Speed</label>
            <span>{(detailedDrone.Velocity_Down || 0).toFixed(1)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Heading</label>
            <span>{(detailedDrone.Yaw || 0).toFixed(0)}°</span>
          </div>
          <div className="detail-item">
            <label>Latitude</label>
            <span>{(detailedDrone.Position_Lat || 0).toFixed(7)}</span>
          </div>
          <div className="detail-item">
            <label>Longitude</label>
            <span>{(detailedDrone.Position_Long || 0).toFixed(7)}</span>
          </div>
        </div>
      </div>
    </div>
  );

  const renderTechnicalTab = () => (
    <div className="detail-content">
      {/* System Information */}
      <div className="detail-section">
        <h3><FaCog /> System Information</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>Hardware ID</label>
            <span>{detailedDrone.hw_ID}</span>
          </div>
          <div className="detail-item">
            <label>Position ID</label>
            <span>{detailedDrone.Pos_ID}</span>
          </div>
          <div className="detail-item">
            <label>Detected Pos ID</label>
            <span>{detailedDrone.Detected_Pos_ID}</span>
          </div>
          <div className="detail-item">
            <label>State Code</label>
            <span>{detailedDrone.State}</span>
          </div>
          <div className="detail-item">
            <label>Base Mode</label>
            <span>{detailedDrone.Base_Mode} (0x{(detailedDrone.Base_Mode || 0).toString(16).toUpperCase()})</span>
          </div>
          <div className="detail-item">
            <label>Flight Mode Code</label>
            <span>{detailedDrone.Flight_Mode}</span>
          </div>
        </div>
      </div>

      {/* GPS & Navigation */}
      <div className="detail-section">
        <h3><FaSatellite /> GPS & Navigation</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>GPS Fix Type</label>
            <span style={{ color: gpsStatus.color }}>{gpsStatus.label}</span>
          </div>
          <div className="detail-item">
            <label>Satellites Visible</label>
            <span>{detailedDrone.Satellites_Visible || 0}</span>
          </div>
          <div className="detail-item">
            <label>HDOP</label>
            <span className={detailedDrone.Hdop <= 1.0 ? 'good' : detailedDrone.Hdop <= 2.0 ? 'fair' : 'poor'}>
              {(detailedDrone.Hdop || 0).toFixed(2)}
            </span>
          </div>
          <div className="detail-item">
            <label>VDOP</label>
            <span className={detailedDrone.Vdop <= 1.0 ? 'good' : detailedDrone.Vdop <= 2.0 ? 'fair' : 'poor'}>
              {(detailedDrone.Vdop || 0).toFixed(2)}
            </span>
          </div>
        </div>
      </div>

      {/* Velocity Components */}
      <div className="detail-section">
        <h3><FaCompass /> Velocity Components</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>North</label>
            <span>{(detailedDrone.Velocity_North || 0).toFixed(2)} m/s</span>
          </div>
          <div className="detail-item">
            <label>East</label>
            <span>{(detailedDrone.Velocity_East || 0).toFixed(2)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Down</label>
            <span>{(detailedDrone.Velocity_Down || 0).toFixed(2)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Ground Speed</label>
            <span>{groundSpeed.toFixed(2)} m/s</span>
          </div>
        </div>
      </div>

      {/* Network & Connectivity */}
      <div className="detail-section">
        <h3><FaNetworkWired /> Network & Connectivity</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>IP Address</label>
            <span>{detailedDrone.IP || 'N/A'}</span>
          </div>
          <div className="detail-item">
            <label>First Seen</label>
            <span>{formatTime(detailedDrone.Heartbeat_First_Seen * 1000)}</span>
          </div>
          <div className="detail-item">
            <label>Last Heartbeat</label>
            <span>{formatTime(detailedDrone.Heartbeat_Last_Seen)}</span>
          </div>
          <div className="detail-item">
            <label>Uptime</label>
            <span>{formatDuration(uptime)}</span>
          </div>
          <div className="detail-item">
            <label>Data Update</label>
            <span>{formatTime(detailedDrone.Update_Time * 1000)}</span>
          </div>
          <div className="detail-item">
            <label>Timestamp</label>
            <span>{formatTime(detailedDrone.Timestamp)}</span>
          </div>
        </div>
      </div>
    </div>
  );

  const renderMapTab = () => (
    <div className="detail-content">
      <div className="map-controls">
        <select
          value={currentTileLayer}
          onChange={(e) => setCurrentTileLayer(e.target.value)}
          className="tile-layer-select"
        >
          <option value="OSM">OpenStreetMap</option>
          <option value="OTM">OpenTopoMap</option>
          <option value="ESRI">Esri WorldStreetMap</option>
          <option value="STAMEN">Stamen Toner</option>
        </select>
      </div>
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
            position={[detailedDrone.Position_Lat, detailedDrone.Position_Long]}
            icon={droneIcon}
          />
        </MapContainer>
      </div>
    </div>
  );

  return (
    <div className="drone-detail">
      {!isAccordionView && (
        <div className="detail-header">
          <h1>
            <FaPlane /> Drone {detailedDrone.hw_ID} - Detailed View
            <div className="connection-indicator">
              <span
                className="status-dot"
                style={{ backgroundColor: getStatusColor(isStale) }}
              />
              <span className="status-text">
                {isStale ? 'Connection Lost' : 'Live'}
              </span>
            </div>
          </h1>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="tab-navigation">
        <button
          className={`tab-button ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          <FaClock /> Overview
        </button>
        <button
          className={`tab-button ${activeTab === 'technical' ? 'active' : ''}`}
          onClick={() => setActiveTab('technical')}
        >
          <FaCog /> Technical
        </button>
        <button
          className={`tab-button ${activeTab === 'map' ? 'active' : ''}`}
          onClick={() => setActiveTab('map')}
        >
          <FaMapMarkerAlt /> Map
        </button>
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && renderOverviewTab()}
      {activeTab === 'technical' && renderTechnicalTab()}
      {activeTab === 'map' && renderMapTab()}
    </div>
  );
};

export default DroneDetail;