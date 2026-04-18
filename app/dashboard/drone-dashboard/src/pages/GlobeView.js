import React, { useState, useEffect, useCallback } from 'react';

import Globe from '../components/Globe';
import GlobeMapView from '../components/GlobeMapView';
import IdentityDoctrineStrip from '../components/IdentityDoctrineStrip';
import ViewModeToggle, { VIEW_MODES } from '../components/map/ViewModeToggle';
import '../styles/GlobeView.css';

import { FIELD_NAMES } from '../constants/fieldMappings';
import { getFleetConfigResponse, getFleetTelemetryResponse, unwrapFleetTelemetryPayload } from '../services/gcsApiService';
import { getDroneShowStateName } from '../constants/droneStates';
import { normalizeDroneConfigData } from '../utilities/missionIdentityUtils';

const GlobeView = () => {
  const [drones, setDrones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFirstLoad, setIsFirstLoad] = useState(true);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState(VIEW_MODES.SCENE_3D);

  const fetchDrones = useCallback(async () => {
    try {
      if (isFirstLoad) setIsLoading(true);

      const [response, configResponse] = await Promise.allSettled([
        getFleetTelemetryResponse(),
        getFleetConfigResponse(),
      ]);
      if (response.status !== 'fulfilled') {
        throw response.reason;
      }

      const configRows = normalizeDroneConfigData(
        configResponse.status === 'fulfilled' ? configResponse.value?.data || [] : []
      );
      const configMap = new Map(configRows.map((row) => [String(row.hw_id), row]));
      const dronesData = Object.entries(unwrapFleetTelemetryPayload(response.value.data))
        .filter(([id, drone]) => Object.keys(drone).length > 0)
        .map(([id, drone]) => {
          const config = configMap.get(String(id)) || {};
          const stateValue = drone[FIELD_NAMES.STATE] ?? null;

          return {
            hw_id: id,
            pos_id: config.pos_id ?? id,
            position: [
              drone[FIELD_NAMES.POSITION_LAT] ?? 0,
              drone[FIELD_NAMES.POSITION_LONG] ?? 0,
              drone[FIELD_NAMES.POSITION_ALT] ?? 0,
            ],
            state: stateValue,
            stateLabel: stateValue === null ? 'Unknown' : getDroneShowStateName(stateValue),
            follow_mode: drone[FIELD_NAMES.FOLLOW_MODE] ?? 0,
            altitude: drone[FIELD_NAMES.POSITION_ALT] ?? 0,
            marker_color: config.marker_color || config.markerColor || '',
          };
        });

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
        <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
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
        <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
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
        <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
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
      <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
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
