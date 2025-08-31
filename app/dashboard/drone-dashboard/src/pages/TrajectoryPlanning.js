// src/pages/TrajectoryPlanning.js
// Production-ready Mapbox trajectory planning - fully integrated with existing app

import React, { useState, useRef, useCallback, useMemo } from 'react';
import { distance } from '@turf/turf';

// Import existing trajectory components (keep your excellent ones!)
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
// Import styles
import '../styles/TrajectoryPlanning.css';
// Conditional Mapbox imports with error handling
let Map, Source, Layer, Marker;
let mapboxAvailable = false;

try {
  const mapboxComponents = require('react-map-gl');
  Map = mapboxComponents.Map || mapboxComponents.default;
  Source = mapboxComponents.Source;
  Layer = mapboxComponents.Layer;
  Marker = mapboxComponents.Marker;
  
  // Import Mapbox CSS
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxAvailable = true;
} catch (error) {
  console.warn('Mapbox not available:', error.message);
  mapboxAvailable = false;
}



/**
 * TrajectoryPlanning Component - Production Ready
 * Features:
 * - Fully integrated with existing drone dashboard
 * - Graceful degradation when Mapbox unavailable
 * - Works with your existing trajectory components
 * - Optional feature - rest of app works without it
 * - Professional error handling and user guidance
 */
const TrajectoryPlanning = () => {
  // State management
  const mapRef = useRef(null);
  const [waypoints, setWaypoints] = useState([]);
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [isAddingWaypoint, setIsAddingWaypoint] = useState(false);
  const [showTerrain, setShowTerrain] = useState(true);
  const [sceneMode, setSceneMode] = useState('3D');
  const [error, setError] = useState(null);
  const [mapReady, setMapReady] = useState(false);

  // Mapbox token management with multiple environment variable options
  const mapboxToken = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN || 
                     process.env.REACT_APP_MAPBOX_TOKEN ||
                     process.env.REACT_APP_MAP_TOKEN;

  // Default viewport settings optimized for drone operations
  const [viewState, setViewState] = useState({
    longitude: -122.4194, // San Francisco Bay Area (good for drone testing)
    latitude: 37.7749,
    zoom: 12,
    pitch: showTerrain ? 60 : 0,
    bearing: 0
  });

  // Calculate trajectory statistics using Turf.js (compatible with existing TrajectoryStats component)
  const trajectoryStats = useMemo(() => {
    if (waypoints.length < 2) {
      return {
        totalDistance: 0,
        totalTime: 0,
        maxAltitude: waypoints[0]?.altitude || 0,
        minAltitude: waypoints[0]?.altitude || 0,
      };
    }

    let totalDistance = 0;
    let totalTime = 0;
    let maxAlt = waypoints[0].altitude;
    let minAlt = waypoints[0].altitude;

    for (let i = 1; i < waypoints.length; i++) {
      const prev = waypoints[i - 1];
      const curr = waypoints[i];

      try {
        // Use Turf.js for accurate distance calculation
        const point1 = [prev.longitude, prev.latitude];
        const point2 = [curr.longitude, curr.latitude];
        const segmentDistance = distance(point1, point2, { units: 'meters' });
        
        totalDistance += segmentDistance;
        totalTime = Math.max(totalTime, curr.time || 0);
        maxAlt = Math.max(maxAlt, curr.altitude);
        minAlt = Math.min(minAlt, curr.altitude);
      } catch (err) {
        console.warn('Distance calculation error:', err);
      }
    }

    return {
      totalDistance,
      totalTime,
      maxAltitude: maxAlt,
      minAltitude: minAlt,
    };
  }, [waypoints]);

  // Waypoint management functions (compatible with existing WaypointPanel component)
  const addWaypoint = useCallback((longitude, latitude, altitude = 100) => {
    const newWaypoint = {
      id: `waypoint-${Date.now()}`,
      name: `Waypoint ${waypoints.length + 1}`,
      latitude,
      longitude,
      altitude,
      time: waypoints.length * 10, // 10 seconds between waypoints
      speed: 15, // 15 m/s default speed
    };

    setWaypoints(prev => [...prev, newWaypoint]);
    setIsAddingWaypoint(false);
  }, [waypoints.length]);

  const updateWaypoint = useCallback((id, updates) => {
    setWaypoints(prev => prev.map(wp => 
      wp.id === id ? { ...wp, ...updates } : wp
    ));
  }, []);

  const deleteWaypoint = useCallback((id) => {
    setWaypoints(prev => prev.filter(wp => wp.id !== id));
    if (selectedWaypointId === id) {
      setSelectedWaypointId(null);
    }
  }, [selectedWaypointId]);

  const clearTrajectory = useCallback(() => {
    if (window.confirm('Clear all waypoints?')) {
      setWaypoints([]);
      setSelectedWaypointId(null);
    }
  }, []);

  // Map interaction handlers (only used if Mapbox available)
  const handleMapClick = useCallback((event) => {
    if (!isAddingWaypoint || !mapboxAvailable) return;

    const { lng, lat } = event.lngLat;
    addWaypoint(lng, lat, 100); // Default 100m altitude
  }, [isAddingWaypoint, addWaypoint]);

  // Navigation functions (compatible with existing SearchBar component)
  const flyToWaypoint = useCallback((waypoint) => {
    if (mapRef.current && mapboxAvailable) {
      try {
        mapRef.current.flyTo({
          center: [waypoint.longitude, waypoint.latitude],
          zoom: 15,
          pitch: 60,
          duration: 2000
        });
      } catch (err) {
        console.warn('Navigation error:', err);
      }
    }
  }, []);

  const handleLocationSelect = useCallback((longitude, latitude, altitude = 1000) => {
    if (mapRef.current && mapboxAvailable) {
      try {
        mapRef.current.flyTo({
          center: [longitude, latitude],
          zoom: 12,
          duration: 3000
        });
      } catch (err) {
        console.warn('Location select error:', err);
      }
    }
  }, []);

  // Export functionality (compatible with existing TrajectoryToolbar component)
  const exportTrajectory = useCallback(() => {
    if (waypoints.length === 0) {
      alert('No waypoints to export');
      return;
    }

    try {
      const headers = ['Name', 'Latitude', 'Longitude', 'Altitude_m', 'Time_s', 'Speed_ms'];
      const csvContent = [
        headers.join(','),
        ...waypoints.map(wp => [
          `"${wp.name}"`,
          wp.latitude.toFixed(8),
          wp.longitude.toFixed(8),
          wp.altitude.toFixed(2),
          (wp.time || 0).toFixed(1),
          (wp.speed || 15).toFixed(1)
        ].join(','))
      ].join('\n');

      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const link = document.createElement('a');
      
      const url = URL.createObjectURL(blob);
      link.setAttribute('href', url);
      link.setAttribute('download', `trajectory_${new Date().toISOString().split('T')[0]}.csv`);
      link.style.visibility = 'hidden';
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export failed:', err);
      alert('Export failed: ' + err.message);
    }
  }, [waypoints]);

  // Scene mode handling (compatible with existing TrajectoryToolbar component)
  const handleSceneModeChange = useCallback((mode) => {
    setSceneMode(mode);
    
    if (!mapboxAvailable) return;
    
    let newPitch = 0;
    if (mode === '3D') newPitch = 60;
    else if (mode === '2D') newPitch = 0;
    else if (mode === 'Columbus') newPitch = 30;

    setViewState(prev => ({
      ...prev,
      pitch: newPitch
    }));
  }, []);

  // Terrain toggle
  const toggleTerrain = useCallback(() => {
    setShowTerrain(prev => {
      const newShowTerrain = !prev;
      if (mapboxAvailable) {
        setViewState(current => ({
          ...current,
          pitch: newShowTerrain ? 60 : 0
        }));
      }
      return newShowTerrain;
    });
  }, []);

  // Prepare trajectory line data for Mapbox (only if available)
  const trajectoryLineData = useMemo(() => {
    if (waypoints.length < 2 || !mapboxAvailable) return null;

    return {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: waypoints.map(wp => [wp.longitude, wp.latitude, wp.altitude])
      }
    };
  }, [waypoints]);

  // Error boundary - completely graceful degradation
  if (!mapboxAvailable && !mapboxToken) {
    return (
      <div className="trajectory-planning">
        <div className="trajectory-header">
          <div className="header-left">
            <h1>Trajectory Planning</h1>
            <SearchBar onLocationSelect={handleLocationSelect} />
          </div>
          <TrajectoryStats stats={trajectoryStats} />
        </div>

        <div className="trajectory-container">
          <div className="trajectory-main">
            <TrajectoryToolbar
              isAddingWaypoint={isAddingWaypoint}
              onToggleAddWaypoint={() => setIsAddingWaypoint(!isAddingWaypoint)}
              onClearTrajectory={clearTrajectory}
              onExportTrajectory={exportTrajectory}
              showTerrain={showTerrain}
              onToggleTerrain={toggleTerrain}
              sceneMode={sceneMode}
              onSceneModeChange={handleSceneModeChange}
              waypointCount={waypoints.length}
            />

            <div className="trajectory-fallback-container">
              <div className="trajectory-fallback-content">
                <h2>3D Trajectory Planning</h2>
                <p>Enhanced trajectory planning with 3D terrain visualization requires a free Mapbox token.</p>
                
                <div className="fallback-features">
                  <h3>Available Now:</h3>
                  <ul>
                    <li>Manual waypoint entry via coordinates</li>
                    <li>Trajectory statistics and calculations</li>
                    <li>CSV export and import functionality</li>
                    <li>All drone mission planning features</li>
                  </ul>
                </div>

                <div className="setup-instructions">
                  <h3>Enable 3D Mapping (Optional):</h3>
                  <ol>
                    <li>Get a <strong>free</strong> Mapbox token from <a href="https://account.mapbox.com/access-tokens/" target="_blank" rel="noopener noreferrer">mapbox.com</a></li>
                    <li>Free tier includes <strong>50,000 map loads/month</strong></li>
                    <li>Add to your .env file: <code>REACT_APP_MAPBOX_ACCESS_TOKEN=your_token</code></li>
                    <li>Restart the application</li>
                  </ol>
                </div>

                <div className="alternative-tools">
                  <h3>Alternative Tools:</h3>
                  <p>Use <strong>Globe View</strong> for 3D visualization or <strong>Mission Config</strong> for detailed waypoint management.</p>
                </div>

                {/* Manual waypoint entry form */}
                <div className="manual-waypoint-entry">
                  <h3>Add Waypoint Manually:</h3>
                  <form onSubmit={(e) => {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const lat = parseFloat(formData.get('latitude'));
                    const lng = parseFloat(formData.get('longitude'));
                    const alt = parseFloat(formData.get('altitude'));
                    
                    if (!isNaN(lat) && !isNaN(lng) && !isNaN(alt)) {
                      addWaypoint(lng, lat, alt);
                      e.target.reset();
                    } else {
                      alert('Please enter valid coordinates');
                    }
                  }}>
                    <div className="form-row">
                      <input name="latitude" type="number" step="any" placeholder="Latitude" required />
                      <input name="longitude" type="number" step="any" placeholder="Longitude" required />
                      <input name="altitude" type="number" step="1" placeholder="Altitude (m)" defaultValue="100" required />
                      <button type="submit">Add Waypoint</button>
                    </div>
                  </form>
                </div>
              </div>
            </div>
          </div>

          <WaypointPanel
            waypoints={waypoints}
            selectedWaypointId={selectedWaypointId}
            onSelectWaypoint={setSelectedWaypointId}
            onUpdateWaypoint={updateWaypoint}
            onDeleteWaypoint={deleteWaypoint}
            onMoveWaypoint={() => {}} // Implement drag-drop if needed
            onFlyTo={flyToWaypoint}
          />
        </div>
      </div>
    );
  }

  // Token missing but Mapbox available
  if (!mapboxToken) {
    return (
      <div className="trajectory-error">
        <div className="error-content">
          <h2>Mapbox Token Required</h2>
          <p>3D trajectory planning requires a Mapbox access token.</p>
          <div className="setup-instructions">
            <h3>Quick Setup:</h3>
            <ol>
              <li>Get a <strong>free</strong> token from <a href="https://account.mapbox.com/access-tokens/" target="_blank" rel="noopener noreferrer">mapbox.com</a></li>
              <li>Add to your .env: <code>REACT_APP_MAPBOX_ACCESS_TOKEN=your_token</code></li>
              <li>Restart the application</li>
            </ol>
            <p><strong>Free tier:</strong> 50,000 map loads/month</p>
          </div>
        </div>
      </div>
    );
  }

  // Full Mapbox implementation
  return (
    <div className="trajectory-planning">
      <div className="trajectory-header">
        <div className="header-left">
          <h1>Trajectory Planning</h1>
          <SearchBar onLocationSelect={handleLocationSelect} />
        </div>
        <TrajectoryStats stats={trajectoryStats} />
      </div>

      <div className="trajectory-container">
        <div className="trajectory-main">
          <TrajectoryToolbar
            isAddingWaypoint={isAddingWaypoint}
            onToggleAddWaypoint={() => setIsAddingWaypoint(!isAddingWaypoint)}
            onClearTrajectory={clearTrajectory}
            onExportTrajectory={exportTrajectory}
            showTerrain={showTerrain}
            onToggleTerrain={toggleTerrain}
            sceneMode={sceneMode}
            onSceneModeChange={handleSceneModeChange}
            waypointCount={waypoints.length}
          />

          <div className="map-container">
            <Map
              ref={mapRef}
              {...viewState}
              onMove={evt => setViewState(evt.viewState)}
              onClick={handleMapClick}
              mapboxAccessToken={mapboxToken}
              mapStyle={showTerrain ? "mapbox://styles/mapbox/satellite-streets-v12" : "mapbox://styles/mapbox/streets-v12"}
              terrain={showTerrain ? { source: 'mapbox-dem', exaggeration: 1.5 } : undefined}
              cursor={isAddingWaypoint ? 'crosshair' : 'grab'}
              onLoad={() => setMapReady(true)}
            >
              {/* Add terrain source for 3D visualization */}
              {showTerrain && (
                <Source
                  id="mapbox-dem"
                  type="raster-dem"
                  url="mapbox://mapbox.mapbox-terrain-dem-v1"
                  tileSize={512}
                  maxzoom={14}
                />
              )}

              {/* Trajectory line */}
              {trajectoryLineData && (
                <Source id="trajectory-line" type="geojson" data={trajectoryLineData}>
                  <Layer
                    id="trajectory-line-layer"
                    type="line"
                    paint={{
                      'line-color': '#00d4ff',
                      'line-width': 4,
                      'line-opacity': 0.8
                    }}
                    layout={{
                      'line-join': 'round',
                      'line-cap': 'round'
                    }}
                  />
                </Source>
              )}

              {/* Waypoint markers */}
              {waypoints.map((waypoint, index) => (
                <Marker
                  key={waypoint.id}
                  longitude={waypoint.longitude}
                  latitude={waypoint.latitude}
                  onClick={(e) => {
                    e.originalEvent.stopPropagation();
                    setSelectedWaypointId(waypoint.id);
                  }}
                >
                  <div 
                    className={`waypoint-marker ${selectedWaypointId === waypoint.id ? 'selected' : ''}`}
                    style={{
                      width: selectedWaypointId === waypoint.id ? '20px' : '15px',
                      height: selectedWaypointId === waypoint.id ? '20px' : '15px',
                      backgroundColor: 
                        index === 0 ? '#28a745' : // Green for start
                        index === waypoints.length - 1 ? '#dc3545' : // Red for end
                        selectedWaypointId === waypoint.id ? '#ffc107' : // Yellow for selected
                        '#007bff', // Blue for others
                      border: '2px solid white',
                      borderRadius: '50%',
                      cursor: 'pointer',
                      boxShadow: '0 2px 4px rgba(0,0,0,0.3)'
                    }}
                    title={`${waypoint.name} - Alt: ${waypoint.altitude}m`}
                  />
                </Marker>
              ))}
            </Map>

            {/* Click instruction overlay */}
            {isAddingWaypoint && (
              <div className="map-instruction-overlay">
                Click on the map to add waypoint
              </div>
            )}
          </div>
        </div>

        <WaypointPanel
          waypoints={waypoints}
          selectedWaypointId={selectedWaypointId}
          onSelectWaypoint={setSelectedWaypointId}
          onUpdateWaypoint={updateWaypoint}
          onDeleteWaypoint={deleteWaypoint}
          onMoveWaypoint={() => {}} // Implement if needed
          onFlyTo={flyToWaypoint}
        />
      </div>
    </div>
  );
};

export default TrajectoryPlanning;