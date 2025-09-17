import React from 'react';
import { FaExclamationTriangle, FaCheckCircle, FaInfoCircle } from 'react-icons/fa';
import { Tooltip } from 'react-tooltip'; // For hover tooltips
import DroneDetail from './DroneDetail';            // Existing detail component
import DroneCriticalCommands from './DroneCriticalCommands'; // Existing commands
import { getFlightModeTitle, getSystemStatusTitle, isSafeMode, isReady, debugFlightMode } from '../utilities/flightModeUtils';
import { getDroneShowStateName, isMissionReady, isMissionExecuting } from '../constants/droneStates';
import { getFriendlyMissionName, getMissionStatusClass } from '../utilities/missionUtils';
import '../styles/DroneWidget.css';

/**
 * DroneWidget Component
 * Displays summarized information about a drone and provides interaction options.
 *
 * @param {Object} props - Component props
 * @param {Object} props.drone - The drone data to display
 * @param {Function} props.toggleDroneDetails - Function to toggle the expanded state of the widget
 * @param {boolean} props.isExpanded - Determines if the widget is expanded
 * @param {Function} props.setSelectedDrone - Sets the currently selected drone
 * @returns {JSX.Element} The DroneWidget component
 */
const DroneWidget = ({
  drone,
  toggleDroneDetails,
  isExpanded,
  setSelectedDrone,
}) => {
  const currentTimeInMs = Date.now();
  // Mark data as stale if older than 5 seconds
  const isStale = currentTimeInMs - (drone.Timestamp || 0) > 5000;

  // Flight Mode and Status info using proper PX4/MAVLink standards
  const flightModeValue = drone.Flight_Mode || 0;
  const flightModeTitle = getFlightModeTitle(flightModeValue);
  const systemStatusName = getSystemStatusTitle(drone.System_Status || 0);

  // Comprehensive flight mode debugging
  React.useEffect(() => {
    // Only debug if we have issues or user wants detailed logging
    if (flightModeValue !== 0 && (flightModeTitle.includes('Unknown') || flightModeTitle.includes('Error'))) {
      debugFlightMode(drone, drone.hw_ID);
    }
  }, [flightModeValue, flightModeTitle, drone.hw_ID]);
  
  // Use proper arming status from telemetry (not derived from flight mode)
  const isArmed = drone.Is_Armed || false;
  const isReadyToArm = drone.Is_Ready_To_Arm || false;
  const isInSafeMode = isSafeMode(drone.Flight_Mode || 0);
  const isSystemReady = isReady(drone.System_Status || 0);

  // Mission state info (separate from PX4 arming)
  const missionReady = isMissionReady(drone.State);
  const missionExecuting = isMissionExecuting(drone.State);
  const missionStateName = getDroneShowStateName(drone.State);

  // Friendly mission name for display
  const friendlyMissionName = getFriendlyMissionName(drone.lastMission);
  const missionStatusClass = getMissionStatusClass(drone.lastMission);

  // Example utility to assign color class for HDOP/VDOP
  const getHdopVdopClass = (hdop, vdop) => {
    if (hdop === undefined || vdop === undefined) return '';
    const avgDop = (hdop + vdop) / 2;
    if (avgDop < 0.8) return 'green';
    if (avgDop <= 1.0) return 'yellow';
    return 'red';
  };

  // Example utility to assign color class for battery
  const getBatteryClass = (voltage) => {
    if (voltage === undefined) return '';
    if (voltage >= 16) return 'green';
    if (voltage >= 14.8) return 'yellow';
    return 'red';
  };

  // For position ID vs. auto-detected
  // We'll treat '0' as a special case => "no auto detection available"
  const posId = drone.Pos_ID ?? 'N/A';
  const detectedPosRaw = drone.Detected_Pos_ID; // might be 0, or an actual number, or undefined
  const detectedPosId = detectedPosRaw === undefined ? 'N/A' : String(detectedPosRaw);

  // True mismatch = both are valid (not 'N/A'), auto != 0, and they differ
  const isAutoDetectZero = detectedPosId === '0';
  const posMismatch =
    posId !== 'N/A' &&
    detectedPosId !== 'N/A' &&
    !isAutoDetectZero &&
    posId !== detectedPosId;

  /**
   * A small handler to navigate or link to /mission-config
   * Only used if there's a real mismatch.
   */
  const handlePositionConfigClick = (ev) => {
    ev.stopPropagation(); // Stop from toggling details
    window.location.href = '/mission-config';
  };

  return (
    <div
      className={`drone-widget ${isReadyToArm ? 'ready-to-arm' : 'not-ready-to-arm'} ${
        isArmed ? 'armed' : 'disarmed'
      } ${missionReady ? 'mission-ready' : ''} ${
        missionExecuting ? 'mission-executing' : ''
      } ${isExpanded ? 'expanded' : ''}`}
    >
      {/* Header with stale vs. active indicator */}
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`} />
        Drone {drone.hw_ID || 'Unknown'}
      </h3>

      {/* Single Position ID row with icon indicating match/mismatch or auto=0 */}
      <div className="drone-posid-section">
        <p className="single-posid-row">
          <strong>Position ID:</strong> {posId}{' '}
          {(() => {
            // 1) If auto detection is 0 => show an info icon (less critical)
            if (isAutoDetectZero) {
              return (
                <>
                  <FaInfoCircle
                    className="posid-info-icon"
                    data-tooltip-id={`posid-tooltip-info-${drone.hw_ID}`}
                    data-tooltip-content="Auto-detected pos_id=0 (not available yet)."
                    style={{ color: 'gray', marginLeft: '8px' }}
                  />
                  <Tooltip
                    id={`posid-tooltip-info-${drone.hw_ID}`}
                    place="top"
                    effect="solid"
                  />
                </>
              );
            }
            // 2) If mismatch => show warning icon
            if (posMismatch) {
              return (
                <>
                  <FaExclamationTriangle
                    className="posid-warning-icon"
                    data-tooltip-id={`posid-tooltip-${drone.hw_ID}`}
                    data-tooltip-content={`Mismatch: Auto-detected = ${detectedPosId}. Click to fix.`}
                    onClick={handlePositionConfigClick}
                    style={{ cursor: 'pointer', marginLeft: '8px' }}
                  />
                  <Tooltip
                    id={`posid-tooltip-${drone.hw_ID}`}
                    place="top"
                    effect="solid"
                  />
                </>
              );
            }
            // 3) If both are 'N/A', or we don't have a real mismatch => either no icon or a green check
            // If both are valid (posId != 'N/A' && detectedPosId != 'N/A'), show green check
            if (posId !== 'N/A' && detectedPosId !== 'N/A') {
              return (
                <>
                  <FaCheckCircle
                    className="posid-match-icon"
                    data-tooltip-id={`posid-tooltip-match-${drone.hw_ID}`}
                    data-tooltip-content={`Auto-detected matches config (${detectedPosId}).`}
                    style={{ color: 'green', marginLeft: '8px' }}
                  />
                  <Tooltip
                    id={`posid-tooltip-match-${drone.hw_ID}`}
                    place="top"
                    effect="solid"
                  />
                </>
              );
            }
            // 4) Otherwise, do nothing
            return null;
          })()}
        </p>
      </div>

      {/* Arming Status Section - QGroundControl Style */}
      <div className="arming-status-section">
        <div className="status-row">
          <span className="status-label"><strong>Armed:</strong></span>
          <span className={`status-indicator ${isArmed ? 'armed' : 'disarmed'}`}>
            {isArmed ? 'YES' : 'NO'}
          </span>
        </div>
        <div className="status-row">
          <span className="status-label"><strong>Ready to Arm:</strong></span>
          <span className={`status-indicator ${isReadyToArm ? 'ready' : 'not-ready'}`}>
            {isReadyToArm ? 'YES' : 'NO'}
          </span>
        </div>
      </div>

      {/* Main info block */}
      <div className="drone-info">
        <p>
          <strong>Mission:</strong>
          <span className={`mission-badge ${missionStatusClass}`}>
            {friendlyMissionName}
          </span>
        </p>
        <p>
          <strong>Flight Mode:</strong> {flightModeTitle}
        </p>
        <p>
          <strong>System Status:</strong> {systemStatusName}
        </p>
        <p>
          <strong>Mission State:</strong> 
          <span className={`mission-state-badge ${
            missionExecuting ? 'executing' : missionReady ? 'ready' : 'idle'
          }`}>
            {missionStateName}
          </span>
        </p>
        <p>
          <strong>Server Time:</strong>{' '}
          {drone.Timestamp ? new Date(drone.Timestamp).toLocaleString() : 'N/A'}
        </p>
        <p>
          <strong>Altitude:</strong>{' '}
          {drone.Position_Alt !== undefined
            ? `${drone.Position_Alt.toFixed(1)}m`
            : 'N/A'}
        </p>
        <p>
          <strong>HDOP/VDOP:</strong>{' '}
          <span className={getHdopVdopClass(drone.Hdop, drone.Vdop)}>
            {drone.Hdop !== undefined && drone.Vdop !== undefined
              ? `${drone.Hdop}/${drone.Vdop}`
              : 'N/A'}
          </span>
        </p>
        <p>
          <strong>Battery Voltage:</strong>{' '}
          <span className={getBatteryClass(drone.Battery_Voltage)}>
            {drone.Battery_Voltage !== undefined
              ? `${drone.Battery_Voltage}V`
              : 'N/A'}
          </span>
        </p>

        {/* Drone-critical commands */}
        <div className="drone-critical-commands-section">
          <DroneCriticalCommands droneId={drone.hw_ID} />
        </div>
      </div>

      {/* Expanded details */}
      {isExpanded && (
        <div className="details-content">
          <DroneDetail drone={drone} isAccordionView />
        </div>
      )}
    </div>
  );
};

export default DroneWidget;
