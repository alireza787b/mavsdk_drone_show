//app/dashboard/drone-dashboard/src/pages/Overview.js
import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types'; // Import PropTypes for validation
import axios from 'axios';
import Globe from '../components/Globe'; // Adjusted import path
import CommandSender from '../components/CommandSender'; // Adjusted import path
import DroneWidget from '../components/DroneWidget'; // Adjusted import path
import { getBackendURL, POLLING_RATE_HZ, STALE_DATA_THRESHOLD_SECONDS } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  // State management
  const [drones, setDrones] = useState([]);
  const [expandedDrone, setExpandedDrone] = useState(null);

  // Fetch data from the backend
  useEffect(() => {
    const url = `${getBackendURL()}/telemetry`;
    console.log(url)
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const dronesArray = Object.keys(response.data).map((hw_ID) => ({
          hw_ID,
          ...response.data[hw_ID],
        }));
        console.log(dronesArray)
        setDrones(dronesArray);
      } catch (error) {
        console.error('Network Error:', error);
      }
    };

    fetchData();
    const pollingInterval = setInterval(fetchData, 1000 / POLLING_RATE_HZ);

    return () => {
      clearInterval(pollingInterval);
    };
  }, []);

  // Function to toggle drone details
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
