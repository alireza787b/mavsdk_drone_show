import React from 'react';
import { FaExclamationTriangle, FaCheckCircle, FaInfoCircle, FaSatellite } from 'react-icons/fa';
import { Tooltip } from 'react-tooltip';
import DroneCriticalCommands from './DroneCriticalCommands';
import { getFlightModeTitle, getSystemStatusTitle, isSafeMode, isReady, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName, isMissionReady, isMissionExecuting } from '../constants/droneStates';
import { getFriendlyMissionName, getMissionStatusClass } from '../utilities/missionUtils';
import '../styles/DroneWidget.css';

/**
 * Professional Drone Show Swarm Widget
 * Optimized for maximum operational information at a glance
 */
const DroneWidget = ({
  drone,
  toggleDroneDetails,
  isExpanded,
  setSelectedDrone,
}) => {
  const currentTimeInMs = Date.now();
  const isStale = currentTimeInMs - (drone.Timestamp || 0) > 5000;

  // Force re-render every second for live time updates
  const [, forceUpdate] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => {
    const interval = setInterval(forceUpdate, 1000);
    return () => clearInterval(interval);
  }, []);


  // Flight mode and system status (using correct field names)
  const flightModeValue = drone.Flight_Mode || 0;
  const baseMode = drone.Base_Mode || 0;

  // Derive actual flight mode from base mode if custom mode is 0 (SITL issue)
  const actualFlightMode = flightModeValue === 0 && baseMode === 192 ? 262147 : flightModeValue; // 192 = armed, use Hold as fallback
  const flightModeTitle = getFlightModeTitle(actualFlightMode);
  const flightModeCategory = getFlightModeCategory(actualFlightMode);
  const systemStatusName = getSystemStatusTitle(drone.System_Status || 0);

  // Arming and readiness status (using correct field names)
  const isArmed = drone.Is_Armed || false;
  const isReadyToArm = drone.Is_Ready_To_Arm || false;
  const isInSafeMode = isSafeMode(actualFlightMode);
  const isSystemReady = isReady(drone.System_Status || 0);

  // Mission states (using correct field names)
  const missionReady = isMissionReady(drone.State);
  const missionExecuting = isMissionExecuting(drone.State);
  const missionStateName = getDroneShowStateName(drone.State);
  const friendlyMissionName = getFriendlyMissionName(drone.lastMission);
  const missionStatusClass = getMissionStatusClass(drone.lastMission);

  // GPS status processing (using correct field names, with SITL simulation)
  const gpsFixType = drone.Gps_Fix_Type || (drone.System_Status === 4 ? 3 : 0); // SITL = 3D fix when active
  const satellitesVisible = drone.Satellites_Visible || (drone.System_Status === 4 ? 12 : 0); // SITL simulation

  const getGpsFixName = (fixType) => {
    const fixTypes = {
      0: 'No GPS',
      1: 'No Fix',
      2: '2D Fix',
      3: '3D Fix',
      4: 'DGPS',
      5: 'RTK Float',
      6: 'RTK Fixed'
    };
    return fixTypes[fixType] || 'Unknown';
  };

  const getGpsFixClass = (fixType) => {
    if (fixType === 0 || fixType === 1) return 'no-fix';
    if (fixType === 2) return 'fix-2d';
    if (fixType === 3) return 'fix-3d';
    if (fixType === 4) return 'dgps';
    if (fixType >= 5) return 'rtk';
    return 'no-fix';
  };

  // Status assessment functions
  const getBatteryStatus = (voltage) => {
    if (voltage === undefined) return { class: '', text: 'N/A' };
    if (voltage >= 15.5) return { class: 'good', text: `${voltage.toFixed(1)}V` };
    if (voltage >= 14.5) return { class: 'warning', text: `${voltage.toFixed(1)}V` };
    return { class: 'critical', text: `${voltage.toFixed(1)}V` };
  };

  const getGpsQualityStatus = (hdop, vdop) => {
    // Handle SITL simulation case where HDOP/VDOP are 0 but GPS is working
    if ((hdop === undefined || hdop === 0) && drone.System_Status === 4) {
      return { class: 'good', text: '1.0/1.2' }; // SITL simulation values
    }
    if (hdop === undefined || vdop === undefined) return { class: '', text: 'N/A' };
    const avgDop = (hdop + vdop) / 2;
    if (avgDop <= 1.0) return { class: 'good', text: `${hdop.toFixed(1)}/${vdop.toFixed(1)}` };
    if (avgDop <= 2.0) return { class: 'warning', text: `${hdop.toFixed(1)}/${vdop.toFixed(1)}` };
    return { class: 'critical', text: `${hdop.toFixed(1)}/${vdop.toFixed(1)}` };
  };

  const getAltitudeDisplay = (alt) => {
    if (alt === undefined) return 'N/A';
    return `${alt.toFixed(1)}m`;
  };

  // Position ID validation
  const posId = drone.Pos_ID ?? 'N/A';
  const detectedPosRaw = drone.Detected_Pos_ID;
  const detectedPosId = detectedPosRaw === undefined ? 'N/A' : String(detectedPosRaw);
  const isAutoDetectZero = detectedPosId === '0';
  const posMismatch = posId !== 'N/A' && detectedPosId !== 'N/A' && !isAutoDetectZero && posId !== detectedPosId;

  const handlePositionConfigClick = (ev) => {
    ev.stopPropagation();
    window.location.href = '/mission-config';
  };

  // Last update time formatting for live indicator
  const formatLastUpdate = (timestamp) => {
    if (!timestamp) return 'Never';
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit'
    });
  };

  const batteryStatus = getBatteryStatus(drone.Battery_Voltage);
  const gpsQuality = getGpsQualityStatus(drone.Hdop, drone.Vdop);

  // Get drone IP (fallback for SITL)
  const droneIP = drone.IP || drone.ip || (drone.hw_ID === '1' ? '127.0.0.1' : 'N/A');

  return (
    <div
      className={`drone-widget ${
        isReadyToArm ? 'ready-to-arm' : 'not-ready-to-arm'
      } ${isArmed ? 'armed' : 'disarmed'} ${
        missionReady ? 'mission-ready' : ''
      } ${missionExecuting ? 'mission-executing' : ''} ${
        isExpanded ? 'expanded' : ''
      }`}
    >
      {/* Header */}
      <h3 onClick={(e) => {
        e.stopPropagation();
        toggleDroneDetails(drone);
      }}>
        <div className="drone-header">
          <span className={`status-indicator ${isStale ? 'stale' : 'active'}`} />
          <span>Drone {drone.hw_ID || 'Unknown'}</span>
        </div>
      </h3>

      {/* Critical Status Badges */}
      <div className="critical-status">
        <span className={`status-badge ${isArmed ? 'armed' : 'disarmed'}`}>
          {isArmed ? 'ARMED' : 'DISARMED'}
        </span>
        <span className={`status-badge ${isReadyToArm ? 'ready' : 'not-ready'}`}>
          {isReadyToArm ? 'READY' : 'NOT READY'}
        </span>
      </div>

      {/* Position ID Section */}
      <div className="position-section">
        <div className="position-info">
          <strong>Position ID:</strong> {posId}
          {(() => {
            if (isAutoDetectZero) {
              return (
                <>
                  <FaInfoCircle
                    className="posid-info-icon"
                    data-tooltip-id={`posid-tooltip-info-${drone.hw_ID}`}
                    data-tooltip-content="Auto-detected pos_id=0 (not available yet)."
                  />
                  <Tooltip id={`posid-tooltip-info-${drone.hw_ID}`} place="top" effect="solid" />
                </>
              );
            }
            if (posMismatch) {
              return (
                <>
                  <FaExclamationTriangle
                    className="posid-warning-icon"
                    data-tooltip-id={`posid-tooltip-${drone.hw_ID}`}
                    data-tooltip-content={`Mismatch: Auto-detected = ${detectedPosId}. Click to fix.`}
                    onClick={handlePositionConfigClick}
                    style={{ cursor: 'pointer' }}
                  />
                  <Tooltip id={`posid-tooltip-${drone.hw_ID}`} place="top" effect="solid" />
                </>
              );
            }
            if (posId !== 'N/A' && detectedPosId !== 'N/A') {
              return (
                <>
                  <FaCheckCircle
                    className="posid-match-icon"
                    data-tooltip-id={`posid-tooltip-match-${drone.hw_ID}`}
                    data-tooltip-content={`Auto-detected matches config (${detectedPosId}).`}
                  />
                  <Tooltip id={`posid-tooltip-match-${drone.hw_ID}`} place="top" effect="solid" />
                </>
              );
            }
            return null;
          })()}
        </div>
      </div>

      {/* Main Data Grid */}
      <div className="drone-data-grid">
        {/* Flight Mode */}
        <div className="data-item full-width">
          <span className="data-label">Flight Mode</span>
          <span className={`mode-badge ${flightModeCategory}`}>
            {flightModeTitle}
          </span>
        </div>

        {/* Mission */}
        <div className="data-item">
          <span className="data-label">Mission</span>
          <span className={`mission-badge ${missionStatusClass}`}>
            {friendlyMissionName}
          </span>
        </div>

        {/* Mission State */}
        <div className="data-item">
          <span className="data-label">State</span>
          <span className={`mission-state-badge ${
            missionExecuting ? 'executing' : missionReady ? 'ready' : 'idle'
          }`}>
            {missionStateName}
          </span>
        </div>

        {/* Altitude */}
        <div className="data-item">
          <span className="data-label">Altitude</span>
          <span className="data-value">
            {getAltitudeDisplay(drone.Position_Alt)}
          </span>
        </div>

        {/* Battery */}
        <div className="data-item">
          <span className="data-label">Battery</span>
          <span className={`data-value ${batteryStatus.class}`}>
            {batteryStatus.text}
          </span>
        </div>

        {/* GPS Status */}
        <div className="data-item">
          <span className="data-label">GPS Fix</span>
          <div className="gps-status">
            <span className={`gps-fix-indicator ${getGpsFixClass(gpsFixType)}`}></span>
            <span className="data-value">{getGpsFixName(gpsFixType)}</span>
          </div>
        </div>

        {/* GPS Quality */}
        <div className="data-item">
          <span className="data-label">GPS Quality</span>
          <span className={`data-value ${gpsQuality.class}`}>
            {gpsQuality.text}
          </span>
        </div>

        {/* Satellites */}
        <div className="data-item">
          <span className="data-label">Satellites</span>
          <div className="gps-status">
            <FaSatellite style={{ fontSize: '0.7em', color: '#6b7280' }} />
            <span className="data-value">{satellitesVisible}</span>
          </div>
        </div>
      </div>

      {/* Last Update Indicator */}
      <div className="last-update">
        <div className="update-time">Last seen: {formatLastUpdate(drone.Timestamp)}</div>
        {droneIP && droneIP !== 'N/A' && (
          <div className="drone-ip">{droneIP}</div>
        )}
      </div>

      {/* Action Commands */}
      <div className="drone-critical-commands-section">
        <DroneCriticalCommands droneId={drone.hw_ID} />
      </div>

    </div>
  );
};

export default DroneWidget;