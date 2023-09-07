import React from 'react';
import DroneDetail from './DroneDetail';
import '../styles/DroneWidget.css';

const DroneWidget = ({ drone, toggleDroneDetails, isExpanded, setSelectedDrone }) => {
  const isStale = (new Date() / 1000 - drone.Update_Time) > 5;  // Replace 5 with STALE_DATA_THRESHOLD_SECONDS if you want
  
  return (
    <div className={`drone-widget ${isExpanded ? 'expanded' : ''}`}>
      <h3 onClick={() => toggleDroneDetails(drone)}>
        <span className={`status-indicator ${isStale ? 'stale' : 'active'}`}></span>
        Drone {drone.hw_ID}
      </h3>
      <p>Mission: {drone.Mission}</p>
      <p>State: {drone.State}</p>
      <p>Follow Mode: {drone.Follow_Mode === 0 ? 'LEADER' : `Follows ${drone.Follow_Mode}`}</p>
      <p>Altitude: {drone.Position_Alt.toFixed(1)}m</p>
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
