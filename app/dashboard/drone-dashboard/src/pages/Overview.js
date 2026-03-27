// src/pages/Overview.js
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import CommandSender from '../components/CommandSender';
import DroneWidget from '../components/DroneWidget';
import ExpandedDronePortal from '../components/ExpandedDronePortal';
import {
  attachDroneRuntimeClock,
  extractServerNowMs,
  normalizeTelemetryResponse,
} from '../constants/fieldMappings';
import { normalizeComparableId } from '../utilities/missionIdentityUtils';
import { getBackendURL, getTelemetryURL } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [configByHwId, setConfigByHwId] = useState({});
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [originRect, setOriginRect] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);
  const droneRefs = useRef({});

  useEffect(() => {
    const backendURL = getBackendURL();
    let active = true;

    const loadConfig = async () => {
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
        if (!active || !Array.isArray(response.data)) {
          return;
        }

        const nextConfigByHwId = response.data.reduce((accumulator, entry) => {
          const hwId = normalizeComparableId(entry?.hw_id);
          if (hwId) {
            accumulator[hwId] = entry;
          }
          return accumulator;
        }, {});

        setConfigByHwId(nextConfigByHwId);
      } catch (loadError) {
        console.warn('Failed to load config metadata for overview cards:', loadError);
      }
    };

    loadConfig();
    const interval = setInterval(loadConfig, 30000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const url = getTelemetryURL();
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const clockMeta = {
          receivedAtMs: Date.now(),
          serverNowMs: extractServerNowMs(response.headers),
        };
        const normalizedTelemetry = normalizeTelemetryResponse(response.data || {}, clockMeta);
        const dronesArray = Object.keys(normalizedTelemetry).map((hw_ID) => attachDroneRuntimeClock({
          ...(configByHwId[normalizeComparableId(hw_ID)] || {}),
          hw_ID,
          ...normalizedTelemetry[hw_ID],
        }, clockMeta));

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
  }, [configByHwId]);

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
