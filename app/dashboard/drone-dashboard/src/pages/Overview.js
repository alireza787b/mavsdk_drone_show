// src/pages/Overview.js
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import CommandSender from '../components/CommandSender';
import DroneWidget from '../components/DroneWidget';
import ExpandedDronePortal from '../components/ExpandedDronePortal';
import { getTelemetryURL } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [originRect, setOriginRect] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);
  const [incompleteDrones, setIncompleteDrones] = useState([]);
  const droneRefs = useRef({});

  useEffect(() => {
    const url = getTelemetryURL();
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const dronesArray = Object.keys(response.data).map((hw_ID) => ({
          hw_ID,
          ...response.data[hw_ID],
        }));

        const validDrones = dronesArray.filter(
          (drone) =>
            drone.position_lat !== undefined &&
            drone.position_long !== undefined &&
            drone.position_alt !== undefined &&
            drone.battery_voltage !== undefined
        );

        const invalidDrones = dronesArray.filter(
          (drone) => !validDrones.includes(drone)
        );

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
      setOriginRect(null);
    } else {
      // Get the position of the clicked drone widget for animation
      const droneElement = droneRefs.current[drone.hw_ID];
      if (droneElement) {
        const rect = droneElement.getBoundingClientRect();
        setOriginRect(rect);
      }
      setExpandedDrone(drone);
    }
  };

  const closeExpandedDrone = () => {
    setExpandedDrone(null);
    setOriginRect(null);
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
          <div
            key={drone.hw_ID}
            ref={(el) => droneRefs.current[drone.hw_ID] = el}
          >
            <DroneWidget
              drone={drone}
              isExpanded={expandedDrone && expandedDrone.hw_ID === drone.hw_ID}
              toggleDroneDetails={toggleDroneDetails}
              setSelectedDrone={setSelectedDrone}
            />
          </div>
        ))}
      </div>

      {/* Expanded Drone Portal */}
      <ExpandedDronePortal
        drone={expandedDrone}
        isOpen={!!expandedDrone}
        onClose={closeExpandedDrone}
        originRect={originRect}
      />
    </div>
  );
};

Overview.propTypes = {
  setSelectedDrone: PropTypes.func.isRequired,
};

export default Overview;
