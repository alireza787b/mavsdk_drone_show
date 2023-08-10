import React, { useState, useEffect } from 'react';
import axios from 'axios';

const POLLING_RATE_HZ = 2; // Frequency of checking for new data (in Hz)
const STALE_DATA_THRESHOLD_SECONDS = 5; // Threshold for considering data stale (in seconds)

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Function to update the current time
  const updateTime = () => {
    setCurrentTime(new Date());
  };

  // Set up an interval to update the current time every second
  useEffect(() => {
    const timeInterval = setInterval(updateTime, 1000);
    return () => {
      clearInterval(timeInterval);
    };
  }, []);

  // Function to fetch data
  useEffect(() => {
    const url = 'http://127.0.0.1:5000/telemetry';

    const fetchData = () => {
      axios.get(url)
        .then((response) => {
          const dronesArray = Object.keys(response.data).map((hw_ID) => ({
            hw_ID,
            ...response.data[hw_ID],
          }));
          setDrones(dronesArray);
        })
        .catch((error) => {
          console.error('Network Error:', error);
        });
    };

    // Initial fetch
    fetchData();

    // Set up polling
    const pollingInterval = setInterval(fetchData, 1000 / POLLING_RATE_HZ);

    // Clean up interval when component unmounts
    return () => {
      clearInterval(pollingInterval);
    };
  }, []);

  return (
    <div>
      <h1>Connected Drones</h1>
      <ul>
        {drones.map((drone) => {
          // Determine if the data is stale
          const isStale = (new Date() / 1000 - drone.Update_Time) > STALE_DATA_THRESHOLD_SECONDS;

          return (
            <div className="drone-item" key={drone.hw_ID} onClick={() => setSelectedDrone(drone)}>
              <li>
                <span style={{ color: isStale ? 'red' : 'green' }}>●</span> {/* Indicator */}
                HW_ID: {drone.hw_ID}, Mission: {drone.Mission}, State: {drone.State}, Follow Mode: {drone.Follow_Mode === 0 ? 'LEADER' : `Follows ${drone.Follow_Mode}`}, Altitude: {drone.Position_Alt.toFixed(1)}
              </li>
            </div>
          );
        })}
      </ul>
    </div>
  );
};

export default Overview;
