import React, { useState, useEffect, useCallback } from 'react';
import Globe from '../components/Globe';
import '../styles/GlobeView.css';
import axios from 'axios';
import { getTelemetryURL } from '../utilities/utilities';

const GlobeView = () => {
  const [drones, setDrones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFirstLoad, setIsFirstLoad] = useState(true);
  const [error, setError] = useState(null);

  const fetchDrones = useCallback(async () => {
    const url = getTelemetryURL();

    try {
      if (isFirstLoad) setIsLoading(true);

      const response = await axios.get(url);
      const dronesData = Object.entries(response.data)
        .filter(([id, drone]) => Object.keys(drone).length > 0)
        .map(([id, drone]) => ({
          hw_ID: id,
          position: [
            drone.Position_Lat || 0,
            drone.Position_Long || 0,
            drone.Position_Alt || 0,
          ],
          state: drone.State || 'UNKNOWN',
          follow_mode: drone.Follow_Mode || 0,
          altitude: drone.Position_Alt || 0,
        }));

      // Log received positions
      console.log('Received Drone Positions:', dronesData.map(drone => ({
        hw_ID: drone.hw_ID,
        position: drone.position,
      })));

      setDrones(dronesData);

      if (isFirstLoad) {
        setIsLoading(false);
        setIsFirstLoad(false);
      }
    } catch (err) {
      console.error('Error fetching drones:', err);
      setError('Failed to load drones. Please try again later.');
      setIsLoading(false);
    }
  }, [isFirstLoad]);

  useEffect(() => {
    fetchDrones();
    const interval = setInterval(fetchDrones, 1000);
    return () => clearInterval(interval);
  }, [fetchDrones]);

  if (isLoading) {
    return (
      <div className="globe-view-container">
        <h2>Drone 3D Map View</h2>
        <div className="loading-container">
          <div className="loading-spinner"></div>
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
          <p>{error}</p>
          <button onClick={fetchDrones}>Retry</button>
        </div>
      </div>
    );
  }

  if (drones.length === 0) {
    return (
      <div className="globe-view-container">
        <h2>Drone 3D Map View</h2>
        <div className="no-data-message">
          No drone data available.
        </div>
      </div>
    );
  }

  return (
    <div className="globe-view-container">
      <h2>Drone 3D Map View</h2>
      <Globe drones={drones} />
    </div>
  );
};

export default GlobeView;
