import React, { useState, useEffect, useCallback } from 'react';

import Globe from '../components/Globe';
import GlobeMapView from '../components/GlobeMapView';
import ViewModeToggle, { VIEW_MODES } from '../components/map/ViewModeToggle';
import '../styles/GlobeView.css';

import { FIELD_NAMES } from '../constants/fieldMappings';
import { getFleetTelemetryResponse, unwrapFleetTelemetryPayload } from '../services/gcsApiService';

const GlobeView = () => {
  const [drones, setDrones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFirstLoad, setIsFirstLoad] = useState(true);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState(VIEW_MODES.SCENE_3D);

  const fetchDrones = useCallback(async () => {
    try {
      if (isFirstLoad) setIsLoading(true);

      const response = await getFleetTelemetryResponse();
      const dronesData = Object.entries(unwrapFleetTelemetryPayload(response.data))
        .filter(([id, drone]) => Object.keys(drone).length > 0)
        .map(([id, drone]) => ({
          hw_id: id,
          position: [
            drone[FIELD_NAMES.POSITION_LAT] || 0,
            drone[FIELD_NAMES.POSITION_LONG] || 0,
            drone[FIELD_NAMES.POSITION_ALT] || 0,
          ],
          state: drone[FIELD_NAMES.STATE] || 'UNKNOWN',
          follow_mode: drone[FIELD_NAMES.FOLLOW_MODE] || 0,
          altitude: drone[FIELD_NAMES.POSITION_ALT] || 0,
        }));

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
        <h2>Drone Visualization</h2>
        <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
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
        <h2>Drone Visualization</h2>
        <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
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
        <h2>Drone Visualization</h2>
        <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
        <div className="no-data-message">
          No drone data available.
        </div>
      </div>
    );
  }

  return (
    <div className="globe-view-container">
      <h2>Drone Visualization</h2>
      <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
      {viewMode === VIEW_MODES.SCENE_3D ? (
        <Globe drones={drones} />
      ) : (
        <GlobeMapView drones={drones} />
      )}
    </div>
  );
};

export default GlobeView;
