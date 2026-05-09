import React from 'react';
import PropTypes from 'prop-types';
import {
  FaCheckCircle,
  FaBroadcastTower,
  FaCog,
  FaEthernet,
  FaExclamationTriangle,
  FaHome,
  FaInfoCircle,
  FaMobileAlt,
  FaProjectDiagram,
  FaRegCircle,
  FaUsb,
  FaWifi,
} from 'react-icons/fa';
import { Tooltip } from 'react-tooltip';
import { useNavigate } from 'react-router-dom';
import DroneCriticalCommands from './DroneCriticalCommands';
import DroneReadinessReport from './DroneReadinessReport';
import { getFlightModeTitle, getFlightModeCategory } from '../utilities/flightModeUtils';
import { getDroneShowStateName, isMissionReady, isMissionExecuting } from '../constants/droneStates';
import { getMissionDisplayContext } from '../utilities/missionUtils';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { getPromotedMissionConfigField } from '../utilities/missionConfigFields';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { formatAltitudeMeters, resolveMslAltitude } from '../utilities/telemetryAltitude';
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
  commandScopeState = 'out',
  onToggleCommandScope = null,
}) => {
  const navigate = useNavigate();
  const currentTimeInMs = Date.now();
  const runtimeStatus = getDroneRuntimeStatus(drone, currentTimeInMs);
  const telemetryAvailable = drone[FIELD_NAMES.TELEMETRY_AVAILABLE] !== false;
  const telemetryTrusted = telemetryAvailable && runtimeStatus.level === 'online';
  const runtimeTooltipId = `runtime-tooltip-${drone[FIELD_NAMES.HW_ID] || drone[FIELD_NAMES.POS_ID] || 'unknown'}`;
  const runtimeTooltipText = `${runtimeStatus.label}. ${runtimeStatus.tooltip}`;
  const networkTooltipId = `network-tooltip-${drone[FIELD_NAMES.HW_ID] || drone[FIELD_NAMES.POS_ID] || 'unknown'}`;
  const promotedField = getPromotedMissionConfigField(drone);
  const operatorAlias = promotedField?.displayValue && promotedField.displayValue !== 'Not set'
    ? promotedField.displayValue
    : '';
  const hwId = String(drone[FIELD_NAMES.HW_ID] || drone.hw_ID || '');
  const scopeClass = commandScopeState === 'out' ? 'command-scope-out' : 'command-scope-active';
  const scopeToggleTitle = (() => {
    switch (commandScopeState) {
      case 'all':
        return 'This drone is currently in the all-drones command scope. Click to switch to manual scope and exclude it.';
      case 'cluster':
        return 'This drone is currently in the cluster command scope. Click to switch to manual scope and edit membership.';
      case 'selected':
        return 'This drone is currently in the manual command scope. Click to remove it.';
      default:
        return 'This drone is outside the current manual command scope. Click to add it.';
    }
  })();

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
  const missionDisplay = getMissionDisplayContext(
    drone[FIELD_NAMES.MISSION],
    drone[FIELD_NAMES.LAST_MISSION]
  );
  const compactIdentity = formatCompactDroneIdentity(drone[FIELD_NAMES.POS_ID], drone[FIELD_NAMES.HW_ID], `H${hwId || '?'}`);
  const titleLabel = compactIdentity;
  const aliasLabel = operatorAlias ? `${promotedField.label}: ${operatorAlias}` : '';
  const hasCurrentMission = missionDisplay.hasCurrentMission && missionDisplay.currentMissionName !== 'No Mission';

  // GPS status processing (with SITL simulation fallback)
  const systemStatus = drone[FIELD_NAMES.SYSTEM_STATUS] || 0;
  const gpsFixType = drone[FIELD_NAMES.GPS_FIX_TYPE] || (systemStatus === 4 ? 3 : 0); // SITL = 3D fix when active
  const satellitesVisible = drone[FIELD_NAMES.SATELLITES_VISIBLE] || (systemStatus === 4 ? 12 : 0); // SITL simulation
  const positionLat = Number(drone[FIELD_NAMES.POSITION_LAT]);
  const positionLong = Number(drone[FIELD_NAMES.POSITION_LONG]);
  const hasNonZeroCoordinate = Number.isFinite(positionLat)
    && Number.isFinite(positionLong)
    && (Math.abs(positionLat) > 0.000001 || Math.abs(positionLong) > 0.000001);
  const globalPositionValid = drone[FIELD_NAMES.GLOBAL_POSITION_VALID] !== false && hasNonZeroCoordinate;
  const gpsRawValid = drone[FIELD_NAMES.GPS_RAW_VALID] === true || Number(gpsFixType) >= 3;
  const positionUnavailableReason = drone[FIELD_NAMES.POSITION_UNAVAILABLE_REASON] || 'Waiting for valid PX4 global position.';

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

  const getDistanceToHomeDisplay = (distance) => {
    const numeric = Number(distance);
    if (!Number.isFinite(numeric)) return 'N/A';
    if (numeric >= 1000) return `${(numeric / 1000).toFixed(2)}km`;
    return `${numeric.toFixed(1)}m`;
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
  const hasLastKnownTelemetry = runtimeStatus.level === 'degraded' || runtimeStatus.indicatorClass === 'lost';
  const telemetryCanShowLastKnown = telemetryTrusted || hasLastKnownTelemetry;
  const telemetryPresentationClass = telemetryTrusted ? '' : 'stale';
  const telemetryUnavailableText = telemetryCanShowLastKnown ? 'Last known' : telemetryAvailable ? 'Last known' : 'Unavailable';
  const mapPositionAvailable = telemetryCanShowLastKnown && globalPositionValid;
  const mapPositionText = telemetryCanShowLastKnown ? 'Map pending' : telemetryUnavailableText;
  const altitudeUnavailableText = telemetryCanShowLastKnown ? 'Alt n/a' : telemetryUnavailableText;
  const homeUnavailableText = telemetryCanShowLastKnown ? 'Home n/a' : telemetryUnavailableText;
  const altitudeReading = resolveMslAltitude(drone);
  const altitudeAvailable = telemetryCanShowLastKnown && altitudeReading.value !== null;
  const altitudeHelp = altitudeAvailable
    ? altitudeReading.source === 'gps_raw'
      ? 'Raw GPS altitude above MSL from GPS_RAW_INT. Map coordinate is still waiting for valid PX4 global position.'
      : altitudeReading.source === 'local_position'
        ? 'Local height from PX4 LOCAL_POSITION_NED. This supports VIO/non-GPS operation but is not a map coordinate.'
        : 'Altitude above MSL from PX4 global position.'
    : positionUnavailableReason;
  const showLinkOverlay = runtimeStatus.level === 'offline' || runtimeStatus.level === 'unknown';
  const networkInfo = drone[FIELD_NAMES.HEARTBEAT_NETWORK_INFO] || drone.heartbeat_network_info || {};
  const primaryLink = networkInfo?.primary_link && typeof networkInfo.primary_link === 'object'
    ? networkInfo.primary_link
    : null;
  const activeWifi = networkInfo?.wifi && typeof networkInfo.wifi === 'object' ? networkInfo.wifi : null;
  const primaryLinkType = String(primaryLink?.type || '').toLowerCase();
  const primaryLinkLabel = primaryLink?.label || (
    primaryLinkType === 'wifi'
      ? 'Wi-Fi'
      : primaryLinkType === 'usb_modem'
        ? '4G USB'
        : primaryLinkType === 'cellular'
          ? 'Cellular'
          : primaryLinkType === 'ethernet'
            ? 'Ethernet'
            : 'Network'
  );
  const primaryLinkName = primaryLink?.ssid
    || primaryLink?.connection_name
    || primaryLink?.interface
    || activeWifi?.ssid
    || '';
  const primaryWifiSignal = Number(
    primaryLinkType === 'wifi'
      ? (primaryLink?.signal_strength_percent ?? activeWifi?.signal_strength_percent)
      : activeWifi?.signal_strength_percent
  );
  const primaryLinkInternet = primaryLink?.internet_reachable ?? networkInfo?.internet?.reachable;
  const networkTooltipText = primaryLink
    ? [
      `Primary link: ${primaryLinkLabel}${primaryLinkName ? ` (${primaryLinkName})` : ''}`,
      primaryLinkType === 'wifi' && Number.isFinite(primaryWifiSignal) ? `Signal: ${primaryWifiSignal}%` : null,
      primaryLink?.interface ? `Interface: ${primaryLink.interface}` : null,
      primaryLinkInternet === true ? 'Internet: reachable' : primaryLinkInternet === false ? 'Internet: not reachable' : null,
    ].filter(Boolean).join(' · ')
    : 'Primary link telemetry is not reported yet.';
  const NetworkIcon = (() => {
    if (primaryLinkType === 'wifi') return FaWifi;
    if (primaryLinkType === 'usb_modem') return FaUsb;
    if (primaryLinkType === 'cellular') return FaMobileAlt;
    if (primaryLinkType === 'ethernet') return FaEthernet;
    return FaBroadcastTower;
  })();
  const wifiSignalLevel = Number.isFinite(primaryWifiSignal)
    ? primaryWifiSignal >= 75 ? 'strong' : primaryWifiSignal >= 45 ? 'medium' : primaryWifiSignal > 0 ? 'weak' : 'none'
    : 'unknown';
  const networkIndicatorTone = !primaryLink
    ? 'unknown'
    : primaryLinkInternet === false
      ? 'warning'
      : primaryLinkType === 'wifi'
        ? wifiSignalLevel
        : 'active';

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
      } ${scopeClass} command-scope-${commandScopeState} runtime-${runtimeStatus.indicatorClass}`}
      data-command-scope={commandScopeState}
      data-runtime-state={runtimeStatus.indicatorClass}
    >
      {commandScopeState === 'out' && (
        <div className="drone-widget__scope-ribbon" aria-hidden="true">
          Out
        </div>
      )}
      {showLinkOverlay && (
        <div className="drone-widget__link-overlay" aria-hidden="true" data-help={runtimeStatus.tooltip}>
          <FaBroadcastTower />
          <span>{runtimeStatus.label}</span>
        </div>
      )}
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
            data-help={runtimeStatus.tooltip}
            data-tooltip-id={runtimeTooltipId}
            data-tooltip-content={runtimeTooltipText}
            aria-label={`${runtimeStatus.label}. ${runtimeStatus.tooltip}`}
          >
          <span
            className={`status-indicator ${runtimeStatus.indicatorClass}`}
          />
          </div>
          <div className="drone-header__titles">
            <span className="drone-header__title" data-help={titleLabel}>{titleLabel}</span>
            <div className="drone-header__meta">
              {aliasLabel && (
                <span className="drone-header__alias" data-help={aliasLabel}>{aliasLabel}</span>
              )}
            </div>
          </div>
        </div>
        <div className="drone-header__actions">
          <span
            className={`drone-network-indicator link-${primaryLinkType || 'unknown'} signal-${wifiSignalLevel} tone-${networkIndicatorTone}`}
            data-help={networkTooltipText}
            data-tooltip-id={networkTooltipId}
            data-tooltip-content={networkTooltipText}
            aria-label={networkTooltipText}
          >
            <NetworkIcon aria-hidden="true" />
            {primaryLinkType === 'wifi' && (
              <span className="drone-network-indicator__bars" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            )}
          </span>
          <button
            type="button"
            className={`drone-header__action drone-header__action--scope ${commandScopeState !== 'out' ? 'is-active' : ''}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggleCommandScope?.(hwId);
            }}
            data-help={scopeToggleTitle}
            aria-label={scopeToggleTitle}
          >
            {commandScopeState !== 'out' ? <FaCheckCircle aria-hidden="true" /> : <FaRegCircle aria-hidden="true" />}
            <span className="drone-header__scope-state">
              {commandScopeState !== 'out' ? 'In' : 'Out'}
            </span>
          </button>
          <button
            type="button"
            className="drone-header__action"
            onClick={handlePositionConfigClick}
            data-help="Open Mission Config for this drone"
            aria-label="Open Mission Config for this drone"
          >
            <FaCog aria-hidden="true" />
            <span className="drone-header__action-label">Mission</span>
          </button>
          <button
            type="button"
            className="drone-header__action"
            onClick={handleSwarmDesignClick}
            data-help="Open Swarm Design for this drone"
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
          <div className="data-value-inline">
            <span
              className={`mission-badge ${missionDisplay.currentMissionStatusClass}`}
              data-help={missionDisplay.badgeTooltip}
            >
              {missionDisplay.currentMissionName}
            </span>
            {hasCurrentMission && (
              <span className="data-item__meta-chip" data-help={missionDisplay.badgeTooltip}>
                Active
              </span>
            )}
          </div>
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
          <span
            className={`data-value ${altitudeAvailable ? telemetryPresentationClass : 'map-waiting'}`}
            data-help={altitudeHelp}
          >
            {altitudeAvailable ? formatAltitudeMeters(altitudeReading.value, altitudeReading.label) : altitudeUnavailableText}
          </span>
        </div>

        {/* Battery */}
        <div className="data-item">
          <span className="data-label">Battery</span>
          <span className={`data-value ${telemetryTrusted ? batteryStatus.class : telemetryPresentationClass}`}>
            {telemetryCanShowLastKnown ? batteryStatus.text : telemetryUnavailableText}
          </span>
        </div>

        {/* GPS Status */}
        <div className="data-item">
          <span className="data-label">GPS</span>
          <div className="data-value-stack">
            <div className="gps-status">
              <span className={`gps-fix-indicator ${telemetryCanShowLastKnown ? getGpsFixClass(gpsFixType) : 'no-fix'}`}></span>
              <span className={`data-value ${telemetryPresentationClass}`}>
                {telemetryCanShowLastKnown ? getGpsFixName(gpsFixType) : telemetryUnavailableText}
              </span>
            </div>
            <span
              className={`data-subvalue ${gpsRawValid && !globalPositionValid ? 'map-waiting' : ''}`}
              data-help={gpsRawValid && !globalPositionValid ? positionUnavailableReason : 'Raw GPS status and DOP'}
            >
              {telemetryCanShowLastKnown
                ? `${satellitesVisible} sats · ${globalPositionValid ? `DOP ${gpsQuality.text}` : 'map pending'}`
                : 'Waiting for telemetry'}
            </span>
          </div>
        </div>

        {/* Home Distance */}
        <div className="data-item">
          <span className="data-label">Home</span>
          <div className="data-value-inline">
            <FaHome className="data-item__icon" aria-hidden="true" />
            <span
              className={`data-value ${mapPositionAvailable ? telemetryPresentationClass : 'map-waiting'}`}
              data-help={mapPositionAvailable ? 'Horizontal distance from current global position to cached home' : positionUnavailableReason}
            >
              {mapPositionAvailable ? getDistanceToHomeDisplay(drone[FIELD_NAMES.DISTANCE_TO_HOME_M]) : homeUnavailableText}
            </span>
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
          targetLabel={compactIdentity}
          targetDescriptor={`Per-drone override · ${compactIdentity}`}
          canCancelMission={hasCurrentMission}
          currentMissionLabel={missionDisplay.currentMissionName}
        />
      </div>

      <Tooltip id={runtimeTooltipId} place="top" effect="solid" />
      <Tooltip id={networkTooltipId} place="top" effect="solid" />

    </div>
  );
};

DroneWidget.propTypes = {
  drone: PropTypes.object.isRequired,
  toggleDroneDetails: PropTypes.func.isRequired,
  isExpanded: PropTypes.bool,
  setSelectedDrone: PropTypes.func,
  commandScopeState: PropTypes.oneOf(['out', 'selected', 'cluster', 'all']),
  onToggleCommandScope: PropTypes.func,
};

export default DroneWidget;
