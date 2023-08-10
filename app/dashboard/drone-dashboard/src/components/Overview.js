import React, { useState, useEffect } from 'react';
import axios from 'axios';

const POLLING_RATE_HZ = 2; // Frequency of checking for new data (in Hz)
const STALE_DATA_THRESHOLD_SECONDS = 3; // Threshold for considering data stale (in seconds)

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);

  useEffect(() => {
    const url = 'http://127.0.0.1:5000/telemetry';

    // Function to fetch data
    const fetchData = () => {
      axios.get(url)
        .then((response) => {
          const dronesArray = Object.keys(response.data).map((hw_ID) => {
            const previousData = drones.find((drone) => drone.hw_ID === hw_ID);
            const lastUpdated = previousData && JSON.stringify(previousData) === JSON.stringify(response.data[hw_ID])
              ? previousData.lastUpdated
              : new Date().toLocaleString();
            return {
              hw_ID,
              lastUpdated,
              ...response.data[hw_ID],
            };
          });
          setDrones(dronesArray);
        })
        .catch((error) => {
          console.error('Network Error:', error); // Log the error to the console

          // Update the lastUpdated timestamp based on the current time and stale threshold
          const updatedDrones = drones.map((drone) => ({
            ...drone,
            lastUpdated: new Date(new Date() - STALE_DATA_THRESHOLD_SECONDS * 1000).toLocaleString(),
          }));
          setDrones(updatedDrones);
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
  }, [drones]);

  return (
    <div>
      <h1>Connected Drones</h1>
      <ul>
        {drones.map((drone) => {
          // Determine if the data is stale
          const isStale = (new Date() - new Date(drone.lastUpdated)) / 1000 > STALE_DATA_THRESHOLD_SECONDS;
          
          return (
            <div key={drone.hw_ID} onClick={() => setSelectedDrone(drone)}>
              <li>
                <span style={{ color: isStale ? 'red' : 'green' }}>●</span> {/* Indicator */}
                HW_ID: {drone.hw_ID}, Mission: {drone.Mission}, State: {drone.State}, Altitude: {drone.Position_Alt}
              </li>
            </div>
          );
        })}
      </ul>
    </div>
  );
};

export default Overview;
