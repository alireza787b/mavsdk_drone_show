// src/pages/GlobeView.js
import React, { useState, useEffect } from 'react';
import Globe from '../components/Globe';
import '../styles/GlobeView.css';
import axios from 'axios'; // Ensure axios is installed: npm install axios
import PropTypes from 'prop-types';
import { getTelemetryURL } from '../utilities/utilities';

const GlobeView = () => {
  const [drones, setDrones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  // Function to fetch drones from the backend
  const fetchDrones = async () => {
    const url = getTelemetryURL();

    try {
      setIsLoading(true);
      const response = await axios.get(url); // Update the API endpoint as needed
      setDrones(response.data);
      setIsLoading(false);
    } catch (err) {
      console.error('Error fetching drones:', err);
      setError('Failed to load drones. Please try again later.');
      setIsLoading(false);
    }
  };

  useEffect(() => {
    fetchDrones();

    // Optional: Implement polling for real-time updates every 10 seconds
    const interval = setInterval(() => {
      fetchDrones();
    }, 10000); // 10,000 ms = 10 seconds

    return () => clearInterval(interval); // Cleanup on unmount
  }, []);

  if (isLoading) {
    return (
      <div className="globe-view-container">
        <h2>Drone 3D Map View</h2>
        <div className="loading-container">
          <div className="spinner"></div>
          <div className="loading-message">Loading drones...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="globe-view-container">
        <h2>Drone 3D Map View</h2>
        <div className="error-message">
          {error}
        </div>
      </div>
    );
  }

  return (
    <div className="globe-view-container">
      <h2>Drone 3D Map View</h2>
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

GlobeView.propTypes = {
  // No props are expected since GlobeView fetches its own data
};

export default GlobeView;
