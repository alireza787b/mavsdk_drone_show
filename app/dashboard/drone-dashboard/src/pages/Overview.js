import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import CommandSender from '../components/CommandSender';
import DroneWidget from '../components/DroneWidget';
import { getTelemetryURL } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);
  const [incompleteDrones, setIncompleteDrones] = useState([]);

  useEffect(() => {
    const url = getTelemetryURL();
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const dronesArray = Object.keys(response.data).map((hw_ID) => ({
          hw_ID,
          ...response.data[hw_ID],
        }));

        const validDrones = dronesArray.filter(drone => (
          drone.Position_Lat !== undefined && 
          drone.Position_Long !== undefined &&
          drone.Position_Alt !== undefined &&
          drone.Battery_Voltage !== undefined
        ));

        const invalidDrones = dronesArray.filter(drone => !validDrones.includes(drone));

        setDrones(validDrones);
        setIncompleteDrones(invalidDrones);  
        setError(null);
        setNotification(null);

        if (invalidDrones.length > 0) {
          setNotification(`${invalidDrones.length} drones have incomplete data.`);
        }
      } catch (error) {
        setError('Failed to fetch data from the backend.');
        setNotification('Network issue, retrying...');
      }
    };

    fetchData();
    const pollingInterval = setInterval(fetchData, 1000);

    return () => {
      clearInterval(pollingInterval);
    };
  }, []);

  const toggleDroneDetails = (drone) => {
    if (expandedDrone && expandedDrone.hw_ID === drone.hw_ID) {
      setExpandedDrone(null);
    } else {
      setExpandedDrone(drone);
    }
  };

  return (
    <div className="overview-container">
      <div className="mission-trigger-section">
        <CommandSender drones={drones} />
      </div>

      <h2 className="connected-drones-header">Connected Drones</h2>

      {notification && <div className="notification">{notification}</div>}
      {error && <div className="error-message">{error}</div>}

      <div className="drone-list">
        {drones.length === 0 && !error && <p>No valid drone data available.</p>}
        {drones.map((drone) => (
          <DroneWidget
            drone={drone}
            isExpanded={expandedDrone && expandedDrone.hw_ID === drone.hw_ID}
            toggleDroneDetails={toggleDroneDetails}
            setSelectedDrone={setSelectedDrone}
            key={drone.hw_ID}
          />
        ))}
      </div>
    </div>
  );
};

Overview.propTypes = {
  setSelectedDrone: PropTypes.func.isRequired,
};

export default Overview;
