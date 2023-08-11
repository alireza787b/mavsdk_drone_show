import React, { useState, useEffect } from 'react';
import axios from 'axios';

const POLLING_RATE_HZ = 2; // Frequency of checking for new data (in Hz)
const STALE_DATA_THRESHOLD_SECONDS = 5; // Threshold for considering data stale (in seconds)

const DroneDetail = ({ drone, goBack, isAccordionView }) => {
  const [detailedDrone, setDetailedDrone] = useState(drone);
  const [isStale, setIsStale] = useState(false);

  // Function to fetch data
  useEffect(() => {
    const url = 'http://127.0.0.1:5000/telemetry';

    const fetchData = () => {
      axios.get(url)
        .then((response) => {
          const droneData = response.data[drone.hw_ID];
          if (droneData) {
            setDetailedDrone({
              hw_ID: drone.hw_ID,
              ...droneData,
            });

            const currentTime = Math.floor(Date.now() / 1000);
            const isDataStale = currentTime - droneData.Update_Time > STALE_DATA_THRESHOLD_SECONDS;
            setIsStale(isDataStale);
          }
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
  }, [drone.hw_ID]);

  return (
    <div>
      
      {!isAccordionView && (
        <>
          <button onClick={goBack}>Return to Overview</button>
          <h1>
            Drone Detail for HW_ID: {detailedDrone.hw_ID}
            <span style={{ color: isStale ? 'red' : 'green' }}>
              ●
            </span>
          </h1>
        </>
      )}
      <p>Update Time (UNIX): {detailedDrone.Update_Time}</p>
      <p>Update Time (Local): {new Date(detailedDrone.Update_Time * 1000).toLocaleString()}</p>
      <p>Mission: {detailedDrone.Mission}</p>
      <p>State: {detailedDrone.State}</p>
      <p>Altitude: {detailedDrone.Position_Alt.toFixed(1)}</p>
      <p>Latitude: {detailedDrone.Position_Lat}</p>
      <p>Longitude: {detailedDrone.Position_Long}</p>
      <p>Velocity North: {detailedDrone.Velocity_North.toFixed(1)}</p>
      <p>Velocity East: {detailedDrone.Velocity_East.toFixed(1)}</p>
      <p>Velocity Down: {detailedDrone.Velocity_Down.toFixed(1)}</p>
      <p>Yaw: {detailedDrone.Yaw.toFixed(0)}</p>
      <p>Battery Voltage: {detailedDrone.Battery_Voltage.toFixed(1)}</p>
      <p>Follow Mode: {detailedDrone.Follow_Mode}</p>
      {/* Add more details as needed */}
    </div>
  );
};

export default DroneDetail;
