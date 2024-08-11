// Overview.js

import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import Globe from '../components/Globe';
import CommandSender from '../components/CommandSender';
import DroneWidget from '../components/DroneWidget';
import { getTelemetryURL } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);

  useEffect(() => {
    const url = getTelemetryURL();
    console.log("Polling started. Fetching telemetry data from:", url);

    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const dronesArray = Object.keys(response.data).map((hw_ID) => ({
          hw_ID,
          ...response.data[hw_ID],
        }));

        setDrones(dronesArray);
        setError(null);
        setNotification(null);

        console.info("Data fetched successfully:", dronesArray);
      } catch (error) {
        console.error('Network Error:', error.message);
        console.debug("Detailed error:", error.response ? error.response.data : "No response data");

        setError('Failed to fetch data from the backend.');
        setNotification('Network issue, retrying...');

        setTimeout(() => {
          setNotification(null);
        }, 3000);
      }
    };

    fetchData();
    const pollingInterval = setInterval(fetchData, 1000);

    return () => {
      clearInterval(pollingInterval);
      console.log("Polling stopped.");
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
        <CommandSender />
      </div>

      <h2 className="connected-drones-header">Connected Drones</h2>
      
      {notification && <div className="notification">{notification}</div>}
      <div className="drone-list">
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

      <Globe 
        drones={drones.map(drone => ({
          hw_ID: drone.hw_ID,
          position: [drone.Position_Lat, drone.Position_Long, drone.Position_Alt],
          state: drone.State,
          follow_mode: drone.Follow_Mode,
          altitude: drone.Position_Alt
        }))}
      />
    </div>
  );
};

// Define PropTypes for better validation
Overview.propTypes = {
  setSelectedDrone: PropTypes.func.isRequired,
};

export default Overview;
