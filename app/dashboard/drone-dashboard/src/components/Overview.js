import React, { useState, useEffect } from 'react';
import axios from 'axios';
import Globe from './Globe';
import CommandSender from './CommandSender';
import DroneWidget from './DroneWidget';
import { getBackendURL , POLLING_RATE_HZ , STALE_DATA_THRESHOLD_SECONDS } from '../utilities';
import '../styles/Overview.css';


const Overview = ({ setSelectedDrone }) => {
  // State management
  const [drones, setDrones] = useState([]);
  const [expandedDrone, setExpandedDrone] = useState(null);

  // Fetch data from the backend
  useEffect(() => {
    const url = `${getBackendURL()}/telemetry`;

    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const dronesArray = Object.keys(response.data).map((hw_ID) => ({
          hw_ID,
          ...response.data[hw_ID],
        }));
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

export default Overview;
