import React from 'react';
import DroneDetail from './DroneDetail';
import { getFlightModeTitle } from '../utilities/flightModeUtils';
import '../styles/DroneWidget.css';

const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  const currentTimeInMs = Date.now(); // Current time in milliseconds
  const isStale = (currentTimeInMs - drone.Timestamp) > 5 * 1000;  // Checking staleness with 5000 ms threshold

  // Get the flight mode title from the flight mode code
  const flightModeTitle = getFlightModeTitle(drone.Flight_Mode);

  return (
    <div className={`drone-widget ${isExpanded ? 'expanded' : ''}`}>
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`}></span>
        Drone {drone.hw_ID}
      </h3>
      <div className="drone-info">
        <p><strong>Mission:</strong> {drone.Mission}</p>
        <p><strong>Flight Mode:</strong> {flightModeTitle}</p> {/* Updated line */}
        <p><strong>State:</strong> {drone.State}</p>
        <p><strong>Server Time:</strong> {new Date(drone.Timestamp).toLocaleString()}</p>
        <p><strong>Altitude:</strong> {drone.Position_Alt.toFixed(1)}m</p>
        <p><strong>HDOP:</strong> {drone.Hdop}</p>
        <p><strong>Battery Voltage:</strong> {drone.Battery_Voltage}V</p>
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
