import React from 'react';
import DroneDetail from './DroneDetail';
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import '../styles/DroneWidget.css';

const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  const currentTimeInMs = Date.now(); // Current time in milliseconds
  const isStale = (currentTimeInMs - (drone.Timestamp || 0)) > 5 * 1000;  // Checking staleness with 5000 ms threshold

  // Get the flight mode title from the flight mode code
  const flightModeTitle = getFlightModeTitle(drone.Flight_Mode || 0);

  // Determine if the drone is armable or not
  const armableClass = drone.Is_Armable ? 'armable' : 'not-armable';

  // Determine HDOP class based on value
  const getHdopClass = (hdop) => {
    if (hdop < 0.8) return 'green';
    if (hdop <= 1.0) return 'yellow';
    if (hdop == 0.0) return 'red'
    return 'red';
  };

  // Determine Battery Voltage class based on value
  const getBatteryClass = (voltage) => {
    if (voltage >= 16) return 'green';
    if (voltage >= 14.8) return 'yellow';
    return 'red';
  };

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
        <p><strong>Server Time:</strong> {drone.Timestamp ? new Date(drone.Timestamp).toLocaleString() : 'N/A'}</p>
        <p><strong>Altitude:</strong> {drone.Position_Alt !== undefined ? drone.Position_Alt.toFixed(1) : 'N/A'}m</p>
        <p><strong>HDOP:</strong> <span className={getHdopClass(drone.Hdop)}>{drone.Hdop !== undefined ? drone.Hdop : 'N/A'}</span></p>
        <p><strong>Battery Voltage:</strong> <span className={getBatteryClass(drone.Battery_Voltage)}>{drone.Battery_Voltage !== undefined ? `${drone.Battery_Voltage}V` : 'N/A'}</span></p>
      </div>
      <div className="drone-actions">
        <button className="external-view-btn" onClick={(e) => { e.stopPropagation(); setSelectedDrone(drone); }}>
          🔗 External View
        </button>
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
