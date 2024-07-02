import React from 'react';
import DroneDetail from './DroneDetail';
import '../styles/DroneWidget.css';

const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  const currentTimeInMs = Date.now(); // Current time in milliseconds
  const isStale = (currentTimeInMs - drone.Timestamp) > 5*1000;  // Checking staleness with 5000 ms threshold
  return (
    <div className={`drone-widget ${isExpanded ? 'expanded' : ''}`}>
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`}></span>
        Drone {drone.hw_ID}
      </h3>
      <p>Mission: {drone.Mission}</p>
      <p>Flight Mode: {drone.Flight_Mode}</p>
      <p>State: {drone.State}</p>
      <p>Server Time: {new Date(drone.Timestamp).toLocaleString()} / {drone.Timestamp}</p>
      <p>Altitude: {drone.Position_Alt.toFixed(1)}m</p>
      <p>HDOP: {drone.Hdop}</p>
      <p>Battery Voltage: {drone.Battery_Voltage}</p>
      
      <div className="drone-actions">
        <span onClick={(e) => { e.stopPropagation(); setSelectedDrone(drone); }}>🔗 External View</span>
      </div>
      <div className="details-content">
        {isExpanded && <DroneDetail drone={drone} isAccordionView={true} />}
      </div>
    </div>
  );

};

export default DroneWidget;
