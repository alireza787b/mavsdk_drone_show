// app/dashboard/drone-dashboard/src/components/DroneWidget.js

// Import necessary dependencies
import React from 'react';
import DroneDetail from './DroneDetail'; // Component to display detailed drone information
import { getFlightModeTitle } from '../utilities/flightModeUtils'; // Utility to get flight mode title
import { MAV_MODE_ENUM } from '../constants/mavModeEnum'; // MAV mode enumeration constants
import DroneCriticalCommands from './DroneCriticalCommands'; // Component for drone-specific commands
import '../styles/DroneWidget.css'; // Styles for the DroneWidget component
import { FaExclamationTriangle } from 'react-icons/fa'; // Warning icon from react-icons
import { Tooltip } from 'react-tooltip'; // Tooltip library for displaying additional information

/**
 * DroneWidget Component
 * Displays summarized information about a drone and provides interaction options.
 * @param {Object} props - Component props.
 * @param {Object} props.drone - The drone data to display.
 * @param {Function} props.toggleDroneDetails - Function to toggle the expanded state of the widget.
 * @param {boolean} props.isExpanded - Determines if the widget is expanded.
 * @param {Function} props.setSelectedDrone - Sets the currently selected drone.
 */
const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  // Current time in milliseconds
  const currentTimeInMs = Date.now();

  // Check if the drone data is stale (older than 5000ms)
  const isStale = (currentTimeInMs - (drone.Timestamp || 0)) > 5 * 1000;

  // Get the flight mode title using the flight mode code
  const flightModeTitle = getFlightModeTitle(drone.Flight_Mode || 0);

  // Map MAV_MODE code to a readable name; determine armable status
  const mavModeName = MAV_MODE_ENUM[drone.Flight_Mode] || drone.Flight_Mode;
  const isArmable = drone.Flight_Mode !== 0; // Drone is armable if not in PREFLIGHT mode (0)

  /**
   * Determine the HDOP/VDOP class based on the average DOP value.
   * @param {number} hdop - Horizontal dilution of precision.
   * @param {number} vdop - Vertical dilution of precision.
   * @returns {string} - Corresponding CSS class ('green', 'yellow', or 'red').
   */
  const getHdopVdopClass = (hdop, vdop) => {
    const avgDop = (hdop + vdop) / 2;
    if (avgDop < 0.8) return 'green'; // High precision
    if (avgDop <= 1.0) return 'yellow'; // Moderate precision
    return 'red'; // Poor precision
  };

  /**
   * Determine the battery voltage class based on its value.
   * @param {number} voltage - The drone's battery voltage.
   * @returns {string} - Corresponding CSS class ('green', 'yellow', or 'red').
   */
  const getBatteryClass = (voltage) => {
    if (voltage >= 16) return 'green'; // Battery is in good condition
    if (voltage >= 14.8) return 'yellow'; // Battery is moderate
    return 'red'; // Battery is low
  };

  // Determine the border color class based on the drone's armable status
  const armableClass = isArmable ? 'armable' : 'not-armable';

  // Check if there's a discrepancy between the configured and detected Position ID
  const hasPosIdDiscrepancy = drone.pos_id !== drone.Detected_Pos_ID;

  // Main component render
  return (
    <div className={`drone-widget ${armableClass} ${isExpanded ? 'expanded' : ''}`}>
      {/* Header section with drone title and status indicator */}
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`} />
        Drone {drone.hw_ID || 'Unknown'}
      </h3>

      {/* Core drone information */}
      <div className="drone-info">
        <p><strong>Mission:</strong> {drone.lastMission || 'N/A'}</p>
        <p><strong>Flight Mode:</strong> {flightModeTitle}</p>
        <p><strong>State:</strong> {drone.State || 'Unknown'}</p>
        <p><strong>MAV Mode:</strong> {mavModeName}</p>
        <p><strong>Server Time:</strong> {drone.Timestamp ? new Date(drone.Timestamp).toLocaleString() : 'N/A'}</p>
        <p><strong>Altitude:</strong> {drone.Position_Alt !== undefined ? drone.Position_Alt.toFixed(1) : 'N/A'}m</p>
        <p>
          <strong>HDOP/VDOP:</strong>
          <span className={getHdopVdopClass(drone.Hdop, drone.Vdop)}>
            {drone.Hdop !== undefined && drone.Vdop !== undefined ? `${drone.Hdop}/${drone.Vdop}` : 'N/A'}
          </span>
        </p>
        <p>
          <strong>Battery Voltage:</strong>
          <span className={getBatteryClass(drone.Battery_Voltage)}>
            {drone.Battery_Voltage !== undefined ? `${drone.Battery_Voltage}V` : 'N/A'}
          </span>
        </p>

        {/* Position ID section with discrepancy warning */}
        <div className="drone-posid-section">
          <p>
            <strong>Configured Pos ID:</strong> {drone.pos_id}
          </p>
          {hasPosIdDiscrepancy && (
            <p className="posid-discrepancy">
              <strong>Detected Pos ID:</strong> {drone.Detected_Pos_ID}
              <FaExclamationTriangle
                className="warning-icon"
                data-tooltip-id={`posid-tooltip-${drone.hw_ID}`}
                data-tooltip-content="Detected Pos ID does not match Configured Pos ID."
              />
              <Tooltip id={`posid-tooltip-${drone.hw_ID}`} place="top" effect="solid" />
            </p>
          )}
        </div>

        {/* Critical commands section for the drone */}
        <div className="drone-critical-commands-section">
          <DroneCriticalCommands droneId={drone.hw_ID} />
        </div>
      </div>

      {/* Expanded details content */}
      {isExpanded && (
        <div className="details-content">
          <DroneDetail drone={drone} isAccordionView={true} />
        </div>
      )}
    </div>
  );
};

export default DroneWidget;
