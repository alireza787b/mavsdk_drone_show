import React from 'react';
import { FaExclamationTriangle, FaCheckCircle, FaInfoCircle, FaCog, FaProjectDiagram } from 'react-icons/fa';
import { Tooltip } from 'react-tooltip';
import { useNavigate } from 'react-router-dom';
import DroneCriticalCommands from './DroneCriticalCommands';
import DroneReadinessReport from './DroneReadinessReport';
import { getFlightModeTitle, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName, isMissionReady, isMissionExecuting } from '../constants/droneStates';
import { getFriendlyMissionName, getMissionStatusClass } from '../utilities/missionUtils';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { getPromotedMissionConfigField } from '../utilities/missionConfigFields';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
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
  const navigate = useNavigate();
  const currentTimeInMs = Date.now();
  const runtimeStatus = getDroneRuntimeStatus(drone, currentTimeInMs);
  const telemetryAvailable = drone[FIELD_NAMES.TELEMETRY_AVAILABLE] !== false;
  const telemetryTrusted = telemetryAvailable && runtimeStatus.level === 'online';
  const runtimeTooltipId = `runtime-tooltip-${drone[FIELD_NAMES.HW_ID] || drone[FIELD_NAMES.POS_ID] || 'unknown'}`;
  const runtimeTooltipText = `${runtimeStatus.label}. ${runtimeStatus.tooltip}`;
  const promotedField = getPromotedMissionConfigField(drone);
  const operatorAlias = promotedField?.displayValue && promotedField.displayValue !== 'Not set'
    ? promotedField.displayValue
    : '';
  const hwId = String(drone[FIELD_NAMES.HW_ID] || drone.hw_ID || '');

  // Force re-render every second for live time updates
  const [, forceUpdate] = React.useReducer(x => x + 1, 0);
  React.useEffect(() => {
    const interval = setInterval(forceUpdate, 1000);
    return () => clearInterval(interval);
  }, []);


  // Flight mode and system status
  const flightModeValue = drone[FIELD_NAMES.FLIGHT_MODE] || 0;
  const baseMode = drone[FIELD_NAMES.BASE_MODE] || 0;

  // Derive actual flight mode from base mode if custom mode is 0 (SITL issue)
  const actualFlightMode = flightModeValue === 0 && baseMode === 192 ? 262147 : flightModeValue; // 192 = armed, use Hold as fallback
  const flightModeTitle = getFlightModeTitle(actualFlightMode);
  const flightModeCategory = getFlightModeCategory(actualFlightMode);

  // Arming and readiness status
  const isArmed = drone[FIELD_NAMES.IS_ARMED] || false;
  const readiness = getDroneReadinessModel(drone, runtimeStatus);
  const isReadyToArm = readiness.isReady;
  const readinessBadgeClass = isReadyToArm ? 'ready' : readiness.status;

  // Mission states
  const missionReady = isMissionReady(drone[FIELD_NAMES.STATE]);
  const missionExecuting = isMissionExecuting(drone[FIELD_NAMES.STATE]);
  const missionStateName = getDroneShowStateName(drone[FIELD_NAMES.STATE]);
  const friendlyMissionName = getFriendlyMissionName(drone[FIELD_NAMES.LAST_MISSION]);
  const missionStatusClass = getMissionStatusClass(drone[FIELD_NAMES.LAST_MISSION]);

  // GPS status processing (with SITL simulation fallback)
  const systemStatus = drone[FIELD_NAMES.SYSTEM_STATUS] || 0;
  const gpsFixType = drone[FIELD_NAMES.GPS_FIX_TYPE] || (systemStatus === 4 ? 3 : 0); // SITL = 3D fix when active
  const satellitesVisible = drone[FIELD_NAMES.SATELLITES_VISIBLE] || (systemStatus === 4 ? 12 : 0); // SITL simulation

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
    if ((hdop === undefined || hdop === 0) && systemStatus === 4) {
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
  const posIdRaw = drone[FIELD_NAMES.POS_ID];
  const posId = posIdRaw === undefined || posIdRaw === null ? 'N/A' : String(posIdRaw);
  const detectedPosRaw = drone[FIELD_NAMES.DETECTED_POS_ID];
  const detectedPosId = detectedPosRaw === undefined ? 'N/A' : String(detectedPosRaw);
  const isAutoDetectZero = detectedPosId === '0';
  const posMismatch = posId !== 'N/A' && detectedPosId !== 'N/A' && !isAutoDetectZero && posId !== detectedPosId;

  const handlePositionConfigClick = (ev) => {
    ev.stopPropagation();
    if (!hwId) {
      return;
    }
    navigate(`/mission-config?drone=${hwId}&edit=1`);
  };

  const handleSwarmDesignClick = (ev) => {
    ev.stopPropagation();
    if (!hwId) {
      return;
    }
    navigate(`/swarm-design?drone=${hwId}`);
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

  const batteryStatus = getBatteryStatus(drone[FIELD_NAMES.BATTERY_VOLTAGE]);
  const gpsQuality = getGpsQualityStatus(drone[FIELD_NAMES.HDOP], drone[FIELD_NAMES.VDOP]);
  const telemetryPresentationClass = telemetryTrusted ? '' : 'stale';
  const telemetryUnavailableText = telemetryAvailable ? 'Last known' : 'Unavailable';

  // Get drone IP (use snake_case standard)
  const droneIP = drone[FIELD_NAMES.IP] || (drone[FIELD_NAMES.HW_ID] === '1' ? '127.0.0.1' : 'N/A');

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
        if (typeof setSelectedDrone === 'function') {
          setSelectedDrone(drone);
        }
        toggleDroneDetails(drone);
      }}>
        <div className="drone-header">
          <div
            className="drone-header__status"
            title={runtimeStatus.tooltip}
            data-tooltip-id={runtimeTooltipId}
            data-tooltip-content={runtimeTooltipText}
            aria-label={`${runtimeStatus.label}. ${runtimeStatus.tooltip}`}
          >
          <span
            className={`status-indicator ${runtimeStatus.indicatorClass}`}
          />
          </div>
          <div className="drone-header__titles">
            <span className="drone-header__title">Pos {drone[FIELD_NAMES.POS_ID] ?? 'N/A'} (HW {drone[FIELD_NAMES.HW_ID] || 'Unknown'})</span>
            <div className="drone-header__meta">
              {operatorAlias && (
                <span className="drone-header__alias">{promotedField.label}: {operatorAlias}</span>
              )}
            </div>
          </div>
        </div>
        <div className="drone-header__actions">
          <button
            type="button"
            className="drone-header__action"
            onClick={handlePositionConfigClick}
            title="Open Mission Config for this drone"
            aria-label="Open Mission Config for this drone"
          >
            <FaCog aria-hidden="true" />
            <span className="drone-header__action-label">Mission</span>
          </button>
          <button
            type="button"
            className="drone-header__action"
            onClick={handleSwarmDesignClick}
            title="Open Swarm Design for this drone"
            aria-label="Open Swarm Design for this drone"
          >
            <FaProjectDiagram aria-hidden="true" />
            <span className="drone-header__action-label">Swarm</span>
          </button>
        </div>
      </h3>

      {/* Critical Status Badges */}
      <div className="critical-status">
        <span className={`status-badge ${isArmed ? 'armed' : 'disarmed'}`}>
          {isArmed ? 'ARMED' : 'DISARMED'}
        </span>
        <span className={`status-badge ${readinessBadgeClass}`}>
          {isReadyToArm ? 'READY' : readiness.statusLabel.toUpperCase()}
        </span>
      </div>

      <DroneReadinessReport
        drone={drone}
        runtimeStatus={runtimeStatus}
        variant="compact"
      />

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
                    data-tooltip-id={`posid-tooltip-info-${drone[FIELD_NAMES.HW_ID]}`}
                    data-tooltip-content="Auto-detected pos_id=0 (not available yet)."
                  />
                  <Tooltip id={`posid-tooltip-info-${drone[FIELD_NAMES.HW_ID]}`} place="top" effect="solid" />
                </>
              );
            }
            if (posMismatch) {
              return (
                <>
                  <FaExclamationTriangle
                    className="posid-warning-icon"
                    data-tooltip-id={`posid-tooltip-${drone[FIELD_NAMES.HW_ID]}`}
                    data-tooltip-content={`Mismatch: Auto-detected = ${detectedPosId}. Click to fix.`}
                    onClick={handlePositionConfigClick}
                    style={{ cursor: 'pointer' }}
                  />
                  <Tooltip id={`posid-tooltip-${drone[FIELD_NAMES.HW_ID]}`} place="top" effect="solid" />
                </>
              );
            }
            if (posId !== 'N/A' && detectedPosId !== 'N/A') {
              return (
                <>
                  <FaCheckCircle
                    className="posid-match-icon"
                    data-tooltip-id={`posid-tooltip-match-${drone[FIELD_NAMES.HW_ID]}`}
                    data-tooltip-content={`Auto-detected matches config (${detectedPosId}).`}
                  />
                  <Tooltip id={`posid-tooltip-match-${drone[FIELD_NAMES.HW_ID]}`} place="top" effect="solid" />
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
          <span className={`data-value ${telemetryPresentationClass}`}>
            {telemetryTrusted ? getAltitudeDisplay(drone[FIELD_NAMES.POSITION_ALT]) : telemetryUnavailableText}
          </span>
        </div>

        {/* Battery */}
        <div className="data-item">
          <span className="data-label">Battery</span>
          <span className={`data-value ${telemetryTrusted ? batteryStatus.class : telemetryPresentationClass}`}>
            {telemetryTrusted ? batteryStatus.text : telemetryUnavailableText}
          </span>
        </div>

        {/* GPS Status */}
        <div className="data-item">
          <span className="data-label">GPS Fix</span>
          <div className="gps-status">
            <span className={`gps-fix-indicator ${telemetryTrusted ? getGpsFixClass(gpsFixType) : 'no-fix'}`}></span>
            <span className={`data-value ${telemetryPresentationClass}`}>
              {telemetryTrusted ? getGpsFixName(gpsFixType) : telemetryUnavailableText}
            </span>
          </div>
        </div>

        {/* GPS Quality */}
        <div className="data-item">
          <span className="data-label">GPS Quality</span>
          <div className="data-value-stack">
            <span className={`data-value ${telemetryTrusted ? gpsQuality.class : telemetryPresentationClass}`}>
              {telemetryTrusted ? gpsQuality.text : telemetryUnavailableText}
            </span>
            <span className="data-subvalue">{telemetryTrusted ? `${satellitesVisible} sats` : 'Waiting for telemetry'}</span>
          </div>
        </div>
      </div>

      {/* Last Update Indicator */}
      <div className="last-update">
        <div className="update-time">Last seen: {formatLastUpdate(drone[FIELD_NAMES.TIMESTAMP])}</div>
        {droneIP && droneIP !== 'N/A' && (
          <div className="drone-ip">{droneIP}</div>
        )}
      </div>

      {/* Action Commands */}
      <div className="drone-critical-commands-section">
        <DroneCriticalCommands
          droneId={String(drone[FIELD_NAMES.HW_ID])}
          isArmed={isArmed}
          runtimeStatus={runtimeStatus}
        />
      </div>

      <Tooltip id={runtimeTooltipId} place="top" effect="solid" />

    </div>
  );
};

export default DroneWidget;
