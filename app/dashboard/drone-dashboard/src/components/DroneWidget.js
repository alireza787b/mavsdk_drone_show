import React from 'react';
import { FaExclamationTriangle, FaCheckCircle } from 'react-icons/fa';
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
  const posId = drone.Pos_ID ?? 'N/A';
  const detectedPosId = drone.Detected_Pos_ID ?? 'N/A';
  const posMismatch = posId !== detectedPosId && detectedPosId !== 'N/A';

  // A small handler to navigate or link to /mission-config
  const handlePositionConfigClick = (ev) => {
    ev.stopPropagation(); // Stop from toggling details
    // You could use react-router or window.location here:
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

{/* Single Position ID row with icon indicating match/mismatch */}
<div className="drone-posid-section">
          <p className="single-posid-row">
            <strong>Position ID:</strong> {posId}{' '}
            {posMismatch ? (
              <>
                {/* Warning icon if mismatch */}
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
            ) : (
              // Green check if there's no mismatch and we have valid data
              posId !== 'N/A' && detectedPosId !== 'N/A' && (
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
              )
            )}
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
