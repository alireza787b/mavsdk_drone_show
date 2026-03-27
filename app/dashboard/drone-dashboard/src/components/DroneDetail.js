import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Marker } from 'react-leaflet';
import { FaMapMarkerAlt, FaWifi, FaClock, FaBatteryFull, FaCompass, FaSatellite, FaPlane, FaCog, FaNetworkWired } from 'react-icons/fa';
import 'leaflet/dist/leaflet.css';
import L from 'leaflet';
import LeafletMapBase from './map/LeafletMapBase';
import DroneReadinessReport from './DroneReadinessReport';
import '../styles/DroneDetail.css';
import { getBackendURL } from '../utilities/utilities';
import { getFlightModeTitle, getSystemStatusTitle, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName } from '../constants/droneStates';
import { getFriendlyMissionName } from '../utilities/missionUtils';
import { FIELD_NAMES, attachDroneRuntimeClock, normalizeDroneData } from '../constants/fieldMappings';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';

const POLLING_RATE_HZ = 2;

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
  const [activeTab, setActiveTab] = useState('overview');

  useEffect(() => {
    const backendURL = getBackendURL();
    const url = `${backendURL}/telemetry`;
    const fetchData = () => {
      axios.get(url).then((response) => {
        const droneData = response.data[drone[FIELD_NAMES.HW_ID]];
        if (droneData) {
          setDetailedDrone(attachDroneRuntimeClock({
            hw_ID: drone[FIELD_NAMES.HW_ID],
            ...normalizeDroneData(droneData),
          }));
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
  }, [drone[FIELD_NAMES.HW_ID]]);

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

  const getConnectionStatus = (runtimeStatus) => {
    if (runtimeStatus.level === 'online') {
      return { class: 'excellent', color: '#38a169', label: runtimeStatus.label };
    }
    if (runtimeStatus.level === 'degraded') {
      return { class: 'good', color: '#f6ad55', label: runtimeStatus.label };
    }
    if (runtimeStatus.level === 'offline') {
      return { class: 'poor', color: '#e53e3e', label: runtimeStatus.label };
    }
    return { class: 'none', color: '#a0aec0', label: runtimeStatus.label };
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
  const flightModeName = getFlightModeTitle(detailedDrone[FIELD_NAMES.FLIGHT_MODE]);
  const flightModeCategory = getFlightModeCategory(detailedDrone[FIELD_NAMES.FLIGHT_MODE]);
  const systemStatusName = getSystemStatusTitle(detailedDrone[FIELD_NAMES.SYSTEM_STATUS]);
  const missionStateName = getDroneShowStateName(detailedDrone[FIELD_NAMES.STATE]);
  const friendlyMissionName = getFriendlyMissionName(detailedDrone[FIELD_NAMES.LAST_MISSION]);

  const isArmed = detailedDrone[FIELD_NAMES.IS_ARMED] || false;
  const batteryStatus = getBatteryStatus(detailedDrone[FIELD_NAMES.BATTERY_VOLTAGE] || 0);
  const gpsStatus = getGpsStatus(
    detailedDrone[FIELD_NAMES.GPS_FIX_TYPE] || 0,
    detailedDrone[FIELD_NAMES.HDOP] || 99.99,
    detailedDrone[FIELD_NAMES.SATELLITES_VISIBLE] || 0
  );
  const runtimeStatus = getDroneRuntimeStatus(detailedDrone);
  const readiness = getDroneReadinessModel(detailedDrone, runtimeStatus);
  const connectionStatus = getConnectionStatus(runtimeStatus);

  // Calculate uptime
  const firstSeen = detailedDrone[FIELD_NAMES.HEARTBEAT_FIRST_SEEN] || 0;
  const uptime = firstSeen > 0 ? (Date.now() / 1000) - firstSeen : 0;

  // Calculate speed
  const groundSpeed = Math.sqrt(
    Math.pow(detailedDrone[FIELD_NAMES.VELOCITY_NORTH] || 0, 2) +
    Math.pow(detailedDrone[FIELD_NAMES.VELOCITY_EAST] || 0, 2)
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
              {readiness.statusLabel}
            </div>
          </div>
        </div>

        <div className="status-card">
          <div className="status-icon">
            <FaBatteryFull style={{ color: batteryStatus.color }} />
          </div>
          <div className="status-info">
            <div className="status-label">Battery</div>
            <div className="status-value">{(detailedDrone[FIELD_NAMES.BATTERY_VOLTAGE] || 0).toFixed(1)}V</div>
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
            <div className="status-value">{detailedDrone[FIELD_NAMES.SATELLITES_VISIBLE] || 0} Sats</div>
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
            <div className="status-value">{detailedDrone[FIELD_NAMES.IP] || 'N/A'}</div>
            <div className="status-sub" style={{ color: connectionStatus.color }}>
              {connectionStatus.label}
            </div>
          </div>
        </div>
      </div>

      <DroneReadinessReport
        drone={detailedDrone}
        runtimeStatus={runtimeStatus}
        variant="detail"
      />

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
            <span>{detailedDrone[FIELD_NAMES.MISSION] || 'None'}</span>
          </div>
          <div className="detail-item">
            <label>Last Mission</label>
            <span>{friendlyMissionName}</span>
          </div>
          <div className="detail-item">
            <label>Follow Mode</label>
            <span>{detailedDrone[FIELD_NAMES.FOLLOW_MODE] || '0'}</span>
          </div>
        </div>
      </div>

      {/* Position & Movement */}
      <div className="detail-section">
        <h3><FaMapMarkerAlt /> Position & Movement</h3>
        <div className="detail-grid">
          <div className="detail-item">
            <label>Altitude</label>
            <span>{(detailedDrone[FIELD_NAMES.POSITION_ALT] || 0).toFixed(1)} m</span>
          </div>
          <div className="detail-item">
            <label>Ground Speed</label>
            <span>{groundSpeed.toFixed(1)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Vertical Speed</label>
            <span>{(detailedDrone[FIELD_NAMES.VELOCITY_DOWN] || 0).toFixed(1)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Heading</label>
            <span>{(detailedDrone[FIELD_NAMES.YAW] || 0).toFixed(0)}°</span>
          </div>
          <div className="detail-item">
            <label>Latitude</label>
            <span>{(detailedDrone[FIELD_NAMES.POSITION_LAT] || 0).toFixed(7)}</span>
          </div>
          <div className="detail-item">
            <label>Longitude</label>
            <span>{(detailedDrone[FIELD_NAMES.POSITION_LONG] || 0).toFixed(7)}</span>
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
            <span>{detailedDrone[FIELD_NAMES.HW_ID]}</span>
          </div>
          <div className="detail-item">
            <label>Position ID</label>
            <span>{detailedDrone[FIELD_NAMES.POS_ID]}</span>
          </div>
          <div className="detail-item">
            <label>Detected Pos ID</label>
            <span>{detailedDrone[FIELD_NAMES.DETECTED_POS_ID]}</span>
          </div>
          <div className="detail-item">
            <label>State Code</label>
            <span>{detailedDrone[FIELD_NAMES.STATE]}</span>
          </div>
          <div className="detail-item">
            <label>Base Mode</label>
            <span>{detailedDrone[FIELD_NAMES.BASE_MODE]} (0x{(detailedDrone[FIELD_NAMES.BASE_MODE] || 0).toString(16).toUpperCase()})</span>
          </div>
          <div className="detail-item">
            <label>Flight Mode Code</label>
            <span>{detailedDrone[FIELD_NAMES.FLIGHT_MODE]}</span>
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
            <span>{detailedDrone[FIELD_NAMES.SATELLITES_VISIBLE] || 0}</span>
          </div>
          <div className="detail-item">
            <label>HDOP</label>
            <span className={detailedDrone[FIELD_NAMES.HDOP] <= 1.0 ? 'good' : detailedDrone[FIELD_NAMES.HDOP] <= 2.0 ? 'fair' : 'poor'}>
              {(detailedDrone[FIELD_NAMES.HDOP] || 0).toFixed(2)}
            </span>
          </div>
          <div className="detail-item">
            <label>VDOP</label>
            <span className={detailedDrone[FIELD_NAMES.VDOP] <= 1.0 ? 'good' : detailedDrone[FIELD_NAMES.VDOP] <= 2.0 ? 'fair' : 'poor'}>
              {(detailedDrone[FIELD_NAMES.VDOP] || 0).toFixed(2)}
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
            <span>{(detailedDrone[FIELD_NAMES.VELOCITY_NORTH] || 0).toFixed(2)} m/s</span>
          </div>
          <div className="detail-item">
            <label>East</label>
            <span>{(detailedDrone[FIELD_NAMES.VELOCITY_EAST] || 0).toFixed(2)} m/s</span>
          </div>
          <div className="detail-item">
            <label>Down</label>
            <span>{(detailedDrone[FIELD_NAMES.VELOCITY_DOWN] || 0).toFixed(2)} m/s</span>
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
            <span>{detailedDrone[FIELD_NAMES.IP] || 'N/A'}</span>
          </div>
          <div className="detail-item">
            <label>First Seen</label>
            <span>{formatTime(detailedDrone[FIELD_NAMES.HEARTBEAT_FIRST_SEEN] * 1000)}</span>
          </div>
          <div className="detail-item">
            <label>Last Heartbeat</label>
            <span>{formatTime(detailedDrone[FIELD_NAMES.HEARTBEAT_LAST_SEEN])}</span>
          </div>
          <div className="detail-item">
            <label>Uptime</label>
            <span>{formatDuration(uptime)}</span>
          </div>
          <div className="detail-item">
            <label>Data Update</label>
            <span>{formatTime(detailedDrone[FIELD_NAMES.UPDATE_TIME] * 1000)}</span>
          </div>
          <div className="detail-item">
            <label>Timestamp</label>
            <span>{formatTime(detailedDrone[FIELD_NAMES.TIMESTAMP])}</span>
          </div>
        </div>
      </div>
    </div>
  );

  const renderMapTab = () => (
    <div className="detail-content">
      <div className="map-display">
        <LeafletMapBase
          center={[detailedDrone[FIELD_NAMES.POSITION_LAT], detailedDrone[FIELD_NAMES.POSITION_LONG]]}
          zoom={13}
          defaultLayer="esriSatellite"
          showLayerControl={false}
          style={{ height: '100%', width: '100%' }}
        >
          <Marker
            position={[detailedDrone[FIELD_NAMES.POSITION_LAT], detailedDrone[FIELD_NAMES.POSITION_LONG]]}
            icon={droneIcon}
          />
        </LeafletMapBase>
      </div>
    </div>
  );

  return (
    <div className={`drone-detail ${isAccordionView ? 'expanded-detail' : ''}`}>
      {!isAccordionView && (
        <div className="detail-header">
          <h1>
            <FaPlane /> Drone {detailedDrone[FIELD_NAMES.HW_ID]} - Detailed View
            <div className="connection-indicator">
              <span
                className="status-dot"
                style={{ backgroundColor: connectionStatus.color }}
                title={runtimeStatus.tooltip}
              />
              <span className="status-text">
                {runtimeStatus.label}
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
