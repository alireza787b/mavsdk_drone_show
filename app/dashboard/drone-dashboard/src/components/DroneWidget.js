import React from 'react';
import { FaExclamationTriangle, FaCheckCircle, FaInfoCircle } from 'react-icons/fa';
import { Tooltip } from 'react-tooltip'; // For hover tooltips
import DroneDetail from './DroneDetail';            // Existing detail component
import DroneCriticalCommands from './DroneCriticalCommands'; // Existing commands
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import { MAV_MODE_ENUM } from '../constants/mavModeEnum';
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

  // Flight Mode info
  const flightModeTitle = getFlightModeTitle(drone.Flight_Mode || 0);
  const mavModeName = MAV_MODE_ENUM[drone.Flight_Mode] || drone.Flight_Mode;
  const isArmable = drone.Flight_Mode !== 0; // e.g., not in PREFLIGHT mode => armable

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
      className={`drone-widget ${isArmable ? 'armable' : 'not-armable'} ${
        isExpanded ? 'expanded' : ''
      }`}
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

      {/* Main info block */}
      <div className="drone-info">
        <p>
          <strong>Mission:</strong> {drone.lastMission || 'N/A'}
        </p>
        <p>
          <strong>Flight Mode:</strong> {flightModeTitle}
        </p>
        <p>
          <strong>State:</strong> {drone.State || 'Unknown'}
        </p>
        <p>
          <strong>MAV Mode:</strong> {mavModeName}
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
