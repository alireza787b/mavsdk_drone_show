import React from 'react';
import DroneDetail from './DroneDetail';
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import { MAV_MODE_ENUM } from '../constants/mavModeEnum';  // Import MAV mode enumeration
import '../styles/DroneWidget.css';

const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  const currentTimeInMs = Date.now(); // Current time in milliseconds
  const isStale = (currentTimeInMs - (drone.Timestamp || 0)) > 5 * 1000;  // Checking staleness with 5000 ms threshold

  // Get the flight mode title from the flight mode code
  const flightModeTitle = getFlightModeTitle(drone.Flight_Mode || 0);


  // Map MAV_MODE to a readable name and determine if the drone is armable
  const mavModeName = MAV_MODE_ENUM[drone.Flight_Mode] || `Unknown (${drone.Flight_Mode})`;
  const isArmable = drone.Flight_Mode !== 0; // Any mode other than PREFLIGHT (0) is considered armable

  // Determine HDOP/VDOP class based on value
  const getHdopVdopClass = (hdop, vdop) => {
    const avgDop = (hdop + vdop) / 2;
    if (avgDop < 0.8) return 'green';
    if (avgDop <= 1.0) return 'yellow';
    return 'red';
  };

  // Determine Battery Voltage class based on value
  const getBatteryClass = (voltage) => {
    if (voltage >= 16) return 'green';
    if (voltage >= 14.8) return 'yellow';
    return 'red';
  };

  // Determine the border color class based on the armable status
  const armableClass = isArmable ? 'armable' : 'not-armable';

  return (
    <div className={`drone-widget ${armableClass} ${isExpanded ? 'expanded' : ''}`}>
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`}></span>
        Drone {drone.hw_ID || 'Unknown'}
      </h3>
      <div className="drone-info">
        <p><strong>Mission:</strong> {drone.Mission || 'N/A'}</p>
        <p><strong>Flight Mode:</strong> {flightModeTitle}</p>
        <p><strong>State:</strong> {drone.State || 'Unknown'}</p>
        <p><strong>MAV Mode:</strong> {mavModeName}</p> {/* Display MAV mode */}
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
      </div>
      {isExpanded && (
        <div className="details-content">
          <DroneDetail drone={drone} isAccordionView={true} />
        </div>
      )}
    </div>
  );
};

export default DroneWidget;
