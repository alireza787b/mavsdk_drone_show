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
  const [incompleteDrones, setIncompleteDrones] = useState([]);

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

        // Filter out drones with incomplete data (e.g., missing key properties)
        const validDrones = dronesArray.filter(drone => (
          drone.Position_Lat !== undefined && 
          drone.Position_Long !== undefined &&
          drone.Position_Alt !== undefined &&
          drone.Battery_Voltage !== undefined
        ));

        const invalidDrones = dronesArray.filter(drone => !validDrones.includes(drone));

        setDrones(validDrones);
        setIncompleteDrones(invalidDrones);  // Track incomplete drones for warnings
        setError(null);
        setNotification(null);

        if (invalidDrones.length > 0) {
          setNotification(`${invalidDrones.length} drones have incomplete data.`);
        }

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
