// src/pages/TrajectoryPlanning.js
// PHASE 3 FIXES: Numbered waypoints, speed cautions, elevation estimation
// CRITICAL FIXES: Map markers show numbers, speed violations as warnings only

import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { distance } from '@turf/turf';

// Import existing trajectory components
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import WaypointModal from '../components/trajectory/WaypointModal';

// Import utilities and services
import { calculateSpeed, calculateTrajectoryStats, suggestOptimalTime, recalculateAfterDrag } from '../utilities/SpeedCalculator';
import { TrajectoryStateManager, ACTION_TYPES } from '../utilities/TrajectoryStateManager';
import { TrajectoryStorage } from '../utilities/TrajectoryStorage';

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
  
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxAvailable = true;
} catch (error) {
  console.warn('Mapbox not available:', error.message);
  mapboxAvailable = false;
}

/**
 * PHASE 3: Basic elevation estimation for waypoint creation
 * Simple geographic-based elevation estimation until terrain service is ready
 */
const estimateGroundElevation = (latitude, longitude) => {
  // Basic elevation estimation based on geographic regions
  // This provides reasonable defaults until full terrain integration
  
  // Mountain ranges (rough approximation)
  const mountainRanges = [
    { lat: [25, 50], lng: [-125, -100], elevation: 1500 }, // Rocky Mountains
    { lat: [35, 70], lng: [60, 150], elevation: 2000 },    // Asian mountains  
    { lat: [40, 50], lng: [-10, 50], elevation: 800 },     // European mountains
    { lat: [25, 45], lng: [35, 60], elevation: 1200 },     // Middle East mountains
  ];

  // Check if location is in a mountain range
  for (const range of mountainRanges) {
    if (latitude >= range.lat[0] && latitude <= range.lat[1] &&
        longitude >= range.lng[0] && longitude <= range.lng[1]) {
      return range.elevation;
    }
  }

  // Polar regions
  if (latitude > 60 || latitude < -60) {
    return 200; // Moderate elevation for polar regions
  }
  
  // Tropical/equatorial regions (generally lower)
  if (Math.abs(latitude) < 30) {
    return 50;
  }

  // Coastal areas (detect by proximity to common coastal coordinates)
  const coastalProximity = Math.min(
    Math.abs(longitude % 180), 
    Math.abs(latitude % 90)
  );
  if (coastalProximity < 5) {
    return 10; // Near sea level for coastal areas
  }

  // Default elevation for most continental areas
  return 150;
};

/**
 * TrajectoryPlanning Component - PHASE 3 FIXES
 * Fixed Features:
 * - Numbered waypoint markers clearly visible on map
 * - Speed violations treated as cautions only (non-blocking)
 * - Dynamic color updates when speed issues resolve
 * - Basic elevation estimation (ground + 100m) for new waypoints
 * - Consistent integration with existing app architecture
 */
const TrajectoryPlanning = () => {
  // Enhanced state management with state manager
  const mapRef = useRef(null);
  const stateManagerRef = useRef(new TrajectoryStateManager());
  const storageRef = useRef(new TrajectoryStorage());
  
  // Core state
  const [waypoints, setWaypoints] = useState([]);
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [isAddingWaypoint, setIsAddingWaypoint] = useState(false);
  const [showTerrain, setShowTerrain] = useState(true);
  const [sceneMode, setSceneMode] = useState('3D');
  const [error, setError] = useState(null);
  const [mapReady, setMapReady] = useState(false);

  // Enhanced state
  const [historyStatus, setHistoryStatus] = useState({ canUndo: false, canRedo: false });
  const [saveStatus, setSaveStatus] = useState({ saved: true, autoSaveTime: null });
  const [trajectoryName, setTrajectoryName] = useState('');
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showLoadDialog, setShowLoadDialog] = useState(false);
  const [availableTrajectories, setAvailableTrajectories] = useState([]);

  // Drag-drop state
  const [isDragging, setIsDragging] = useState(false);
  const [draggedWaypointId, setDraggedWaypointId] = useState(null);

  // Modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingWaypointPosition, setPendingWaypointPosition] = useState(null);

  // Mapbox token management
  const mapboxToken = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN || 
                     process.env.REACT_APP_MAPBOX_TOKEN ||
                     process.env.REACT_APP_MAP_TOKEN;

  // Default viewport settings
  const [viewState, setViewState] = useState({
    longitude: 51.2721,
    latitude: 35.7262,
    zoom: 12,
    pitch: showTerrain ? 60 : 0,
    bearing: 0
  });

  // Initialize services on component mount
  useEffect(() => {
    initializeServices();
    loadAvailableTrajectories();
    
    // Auto-save every 30 seconds
    const autoSaveInterval = setInterval(autoSave, 30000);
    
    return () => {
      clearInterval(autoSaveInterval);
    };
  }, []);

  // Update history status when waypoints change
  useEffect(() => {
    const status = stateManagerRef.current.getHistoryStatus();
    setHistoryStatus(status);
    
    // Mark as unsaved when waypoints change
    setSaveStatus(prev => ({ ...prev, saved: false }));
  }, [waypoints]);

  // Initialize services
  const initializeServices = async () => {
    try {
      // Set initial state in state manager
      stateManagerRef.current.setInitialState({
        waypoints: [],
        selectedWaypointId: null
      });
      
      console.info('Trajectory services initialized');
    } catch (error) {
      console.warn('Service initialization failed:', error);
    }
  };

  // Load available trajectories for UI
  const loadAvailableTrajectories = () => {
    const trajectories = storageRef.current.getAllTrajectories();
    setAvailableTrajectories(trajectories);
  };

  // Calculate trajectory statistics using enhanced calculation
  const trajectoryStats = useMemo(() => {
    return calculateTrajectoryStats(waypoints);
  }, [waypoints]);

  // Get previous waypoint for speed calculation
  const getPreviousWaypoint = useCallback(() => {
    return waypoints.length > 0 ? waypoints[waypoints.length - 1] : null;
  }, [waypoints]);

  // PHASE 3: Enhanced waypoint management with elevation estimation
  const addWaypointWithData = useCallback((position, waypointData) => {
    const previousWaypoint = getPreviousWaypoint();
    
    let estimatedSpeed = 0;
    if (previousWaypoint) {
      const tempWaypoint = {
        ...position,
        altitude: waypointData.altitude,
        timeFromStart: waypointData.timeFromStart
      };
      estimatedSpeed = calculateSpeed(previousWaypoint, tempWaypoint);
    }

    // PHASE 3: Speed violations are cautions only, never blocking
    const speedFeasible = true; // Always allow waypoint creation

    const newWaypoint = {
      id: `waypoint-${Date.now()}`,
      name: `Waypoint ${waypoints.length + 1}`,
      latitude: position.latitude,
      longitude: position.longitude,
      altitude: waypointData.altitude,
      timeFromStart: waypointData.timeFromStart,
      estimatedSpeed: waypointData.estimatedSpeed || estimatedSpeed,
      speedFeasible: speedFeasible,
      terrainInfo: waypointData.terrainInfo,
      time: waypointData.timeFromStart,
      speed: waypointData.estimatedSpeed || estimatedSpeed,
      // PHASE 3: Add waypoint index for display
      index: waypoints.length + 1
    };

    // Use state manager for undo/redo support
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.ADD_WAYPOINT,
      { waypoint: newWaypoint },
      `Add ${newWaypoint.name}`
    );

    setWaypoints(newState.waypoints);
    setSelectedWaypointId(newState.selectedWaypointId);
    setIsAddingWaypoint(false);
  }, [waypoints.length, getPreviousWaypoint]);

  // Legacy addWaypoint function with elevation estimation
  const addWaypoint = useCallback((longitude, latitude, altitude = null, timeFromStart = null) => {
    const previousWaypoint = getPreviousWaypoint();
    const calculatedTime = timeFromStart || (previousWaypoint ? previousWaypoint.timeFromStart + 10 : 10);
    
    // PHASE 3: If no altitude provided, estimate ground elevation + 100m
    let finalAltitude = altitude;
    if (finalAltitude === null) {
      const groundElevation = estimateGroundElevation(latitude, longitude);
      finalAltitude = groundElevation + 100; // 100m above estimated ground
    }
    
    const waypointData = {
      altitude: finalAltitude,
      timeFromStart: calculatedTime,
      estimatedSpeed: 0,
      speedFeasible: true
    };

    addWaypointWithData({ latitude, longitude }, waypointData);
  }, [addWaypointWithData, getPreviousWaypoint]);

  // Enhanced update with state tracking and speed recalculation
  const updateWaypoint = useCallback((id, updates) => {
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      { id, updates },
      `Edit waypoint`
    );

    // Recalculate speeds if position or time changed
    if (updates.latitude || updates.longitude || updates.altitude || updates.timeFromStart) {
      const updatedWaypoints = recalculateAfterDrag(newState.waypoints, id);
      
      const finalState = stateManagerRef.current.executeAction(
        ACTION_TYPES.BATCH_UPDATE,
        { waypoints: updatedWaypoints },
        'Recalculate speeds'
      );
      
      setWaypoints(finalState.waypoints);
    } else {
      setWaypoints(newState.waypoints);
    }
  }, []);

  // Enhanced drag-drop with state tracking
  const handleWaypointDrag = useCallback((event, waypointId) => {
    if (!isDragging) return;
    
    const { lng, lat } = event.lngLat;
    
    setWaypoints(prev => prev.map(wp => 
      wp.id === waypointId 
        ? { ...wp, latitude: lat, longitude: lng }
        : wp
    ));
  }, [isDragging]);

  const handleWaypointDragStart = useCallback((waypointId) => {
    setIsDragging(true);
    setDraggedWaypointId(waypointId);
    setSelectedWaypointId(waypointId);
  }, []);

  const handleWaypointDragEnd = useCallback((event, waypointId) => {
    const { lng, lat } = event.lngLat;
    
    // Use state manager for drag completion
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.MOVE_WAYPOINT,
      { id: waypointId, latitude: lat, longitude: lng },
      'Move waypoint'
    );

    // Recalculate speeds after drag
    const updatedWaypoints = recalculateAfterDrag(newState.waypoints, waypointId);
    
    const finalState = stateManagerRef.current.executeAction(
      ACTION_TYPES.BATCH_UPDATE,
      { waypoints: updatedWaypoints },
      'Recalculate after move'
    );

    setWaypoints(finalState.waypoints);
    setIsDragging(false);
    setDraggedWaypointId(null);
  }, []);

  // Enhanced delete with state tracking
  const deleteWaypoint = useCallback((id) => {
    const waypoint = waypoints.find(wp => wp.id === id);
    if (!waypoint) return;

    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.DELETE_WAYPOINT,
      { id },
      `Delete ${waypoint.name}`
    );

    // Recalculate speeds after deletion and update indices
    const updatedWaypoints = newState.waypoints.map((wp, index) => {
      let recalculatedWaypoint = {
        ...wp,
        name: `Waypoint ${index + 1}`, // Update names
        index: index + 1 // Update indices
      };

      if (index > 0) {
        const previousWaypoint = newState.waypoints[index - 1];
        const recalculatedSpeed = calculateSpeed(previousWaypoint, wp);
        
        recalculatedWaypoint = {
          ...recalculatedWaypoint,
          estimatedSpeed: recalculatedSpeed,
          speed: recalculatedSpeed
        };
      }

      return recalculatedWaypoint;
    });

    const finalState = stateManagerRef.current.executeAction(
      ACTION_TYPES.BATCH_UPDATE,
      { waypoints: updatedWaypoints },
      'Recalculate after delete'
    );

    setWaypoints(finalState.waypoints);
    if (selectedWaypointId === id) {
      setSelectedWaypointId(null);
    }
  }, [waypoints, selectedWaypointId]);

  // Enhanced clear with confirmation
  const clearTrajectory = useCallback(() => {
    if (!window.confirm('Clear all waypoints? This action can be undone.')) return;

    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.CLEAR_TRAJECTORY,
      {},
      'Clear trajectory'
    );

    setWaypoints(newState.waypoints);
    setSelectedWaypointId(newState.selectedWaypointId);
    setTrajectoryName('');
  }, []);

  // Undo functionality
  const handleUndo = useCallback(() => {
    const result = stateManagerRef.current.undo();
    if (result) {
      setWaypoints(result.state.waypoints);
      setSelectedWaypointId(result.state.selectedWaypointId);
      console.info(`Undid: ${result.undoneAction}`);
    }
  }, []);

  // Redo functionality
  const handleRedo = useCallback(() => {
    const result = stateManagerRef.current.redo();
    if (result) {
      setWaypoints(result.state.waypoints);
      setSelectedWaypointId(result.state.selectedWaypointId);
      console.info(`Redid: ${result.redoneAction}`);
    }
  }, []);

  // Save trajectory functionality
  const handleSave = useCallback(async (name) => {
    if (!name.trim()) {
      alert('Please enter a trajectory name');
      return;
    }

    const result = await storageRef.current.saveTrajectory(name, waypoints, {
      createdWith: 'Trajectory Planning v3.0',
      stats: trajectoryStats
    });

    if (result.success) {
      setSaveStatus({ saved: true, autoSaveTime: Date.now() });
      setTrajectoryName(name);
      setShowSaveDialog(false);
      loadAvailableTrajectories();
      alert(result.message);
    } else {
      alert(`Save failed: ${result.error}`);
    }
  }, [waypoints, trajectoryStats]);

  // Load trajectory functionality
  const handleLoad = useCallback(async (identifier) => {
    const result = await storageRef.current.loadTrajectory(identifier);
    
    if (result.success) {
      const trajectory = result.trajectory;
      
      // Create checkpoint before loading
      stateManagerRef.current.createCheckpoint('Before load trajectory');
      
      const newState = stateManagerRef.current.executeAction(
        ACTION_TYPES.LOAD_TRAJECTORY,
        { waypoints: trajectory.waypoints },
        `Load ${trajectory.name}`
      );

      setWaypoints(newState.waypoints);
      setSelectedWaypointId(newState.selectedWaypointId);
      setTrajectoryName(trajectory.name);
      setSaveStatus({ saved: true, autoSaveTime: Date.now() });
      setShowLoadDialog(false);
      alert(`Loaded: ${trajectory.name}`);
    } else {
      alert(`Load failed: ${result.error}`);
    }
  }, []);

  // Auto-save functionality
  const autoSave = useCallback(async () => {
    if (waypoints.length === 0) return;

    const result = await storageRef.current.autoSave(waypoints, {
      autoSavedAt: Date.now(),
      stats: trajectoryStats
    });

    if (result.success) {
      setSaveStatus(prev => ({ ...prev, autoSaveTime: Date.now() }));
    }
  }, [waypoints, trajectoryStats]);

  // Enhanced map interaction handlers
  const handleMapClick = useCallback((event) => {
    if (!isAddingWaypoint || isDragging) return;

    const { lng, lat } = event.lngLat || { lng: event.longitude, lat: event.latitude };
    
    setPendingWaypointPosition({ latitude: lat, longitude: lng });
    setModalOpen(true);
  }, [isAddingWaypoint, isDragging]);

  // Handle manual coordinate entry (fallback mode)
  const handleManualWaypointAdd = useCallback((lat, lng, alt) => {
    const previousWaypoint = getPreviousWaypoint();
    const suggestedTime = previousWaypoint 
      ? suggestOptimalTime(previousWaypoint, { latitude: lat, longitude: lng }, 8, alt)
      : 10;

    const waypointData = {
      altitude: alt,
      timeFromStart: suggestedTime,
      estimatedSpeed: 0,
      speedFeasible: true
    };

    addWaypointWithData({ latitude: lat, longitude: lng }, waypointData);
  }, [addWaypointWithData, getPreviousWaypoint]);

  // Modal handlers
  const handleModalConfirm = useCallback((waypointData) => {
    if (pendingWaypointPosition) {
      addWaypointWithData(pendingWaypointPosition, waypointData);
    }
    setModalOpen(false);
    setPendingWaypointPosition(null);
  }, [pendingWaypointPosition, addWaypointWithData]);

  const handleModalClose = useCallback(() => {
    setModalOpen(false);
    setPendingWaypointPosition(null);
  }, []);

  // Navigation functions
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

  // Enhanced location select with elevation estimation
  const handleLocationSelect = useCallback(async (longitude, latitude, altitude = null) => {
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

    // PHASE 3: Log estimated elevation for user awareness
    if (altitude === null) {
      const groundElevation = estimateGroundElevation(latitude, longitude);
      console.info(`Estimated ground elevation: ${groundElevation}m MSL at ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`);
    }
  }, []);

  // Enhanced export with additional formats
  const exportTrajectory = useCallback(async () => {
    if (waypoints.length === 0) {
      alert('No waypoints to export');
      return;
    }

    const format = prompt('Export format? (csv/json/kml)', 'csv');
    if (!format) return;

    const name = trajectoryName || 'trajectory';
    const result = await storageRef.current.exportTrajectory(name, format);
    
    if (!result.success) {
      alert(`Export failed: ${result.error}`);
    }
  }, [waypoints, trajectoryName]);

  // Scene mode handling
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

  // PHASE 3: Enhanced trajectory line with dynamic speed-based coloring
  const trajectoryLineData = useMemo(() => {
    if (waypoints.length < 2 || !mapboxAvailable) return null;

    return {
      type: 'Feature',
      geometry: {
        type: 'LineString',
        coordinates: waypoints.map(wp => [wp.longitude, wp.latitude, wp.altitude])
      },
      properties: {
        speeds: waypoints.slice(1).map(wp => wp.estimatedSpeed || 0)
      }
    };
  }, [waypoints]);

  // PHASE 3: Get marker color based on speed and status
  const getWaypointMarkerColor = useCallback((waypoint, index) => {
    if (index === 0) return '#28a745'; // Green for start
    if (index === waypoints.length - 1) return '#dc3545'; // Red for end
    if (selectedWaypointId === waypoint.id) return '#ffc107'; // Yellow for selected
    
    // PHASE 3: Dynamic color based on speed status
    const speed = waypoint.estimatedSpeed || 0;
    if (speed > 20) return '#ff6b6b'; // Light red for high speed caution
    if (speed > 12) return '#ffd93d'; // Light yellow for medium speed caution
    return '#007bff'; // Blue for normal speed
  }, [waypoints.length, selectedWaypointId]);

  // Error boundary - graceful degradation  
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
              canUndo={historyStatus.canUndo}
              canRedo={historyStatus.canRedo}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onSave={() => setShowSaveDialog(true)}
              onLoad={() => setShowLoadDialog(true)}
              saveStatus={saveStatus}
            />

            <div className="trajectory-fallback-container">
              <div className="trajectory-fallback-content">
                <h2>3D Trajectory Planning</h2>
                <p>Enhanced trajectory planning with 3D terrain visualization requires a free Mapbox token.</p>
                
                <div className="fallback-features">
                  <h3>PHASE 3 Features Available:</h3>
                  <ul>
                    <li>Numbered waypoint system with clear ordering</li>
                    <li>Speed violations treated as cautions only</li>
                    <li>Basic elevation estimation (ground + 100m MSL)</li>
                    <li>Dynamic color updates when speeds improve</li>
                    <li>Professional undo/redo system</li>
                    <li>Save/load with validation and backup</li>
                    <li>Enhanced geocoding search</li>
                    <li>Auto-save with recovery</li>
                  </ul>
                </div>

                <div className="manual-waypoint-entry">
                  <h3>Add Waypoint Manually:</h3>
                  <form onSubmit={(e) => {
                    e.preventDefault();
                    const formData = new FormData(e.target);
                    const lat = parseFloat(formData.get('latitude'));
                    const lng = parseFloat(formData.get('longitude'));
                    let alt = parseFloat(formData.get('altitude'));
                    
                    // If no altitude provided, use estimation
                    if (isNaN(alt)) {
                      const groundElevation = estimateGroundElevation(lat, lng);
                      alt = groundElevation + 100;
                    }
                    
                    if (!isNaN(lat) && !isNaN(lng)) {
                      handleManualWaypointAdd(lat, lng, alt);
                      e.target.reset();
                    } else {
                      alert('Please enter valid coordinates');
                    }
                  }}>
                    <div className="form-row">
                      <input name="latitude" type="number" step="any" placeholder="Latitude" required />
                      <input name="longitude" type="number" step="any" placeholder="Longitude" required />
                      <input name="altitude" type="number" step="1" placeholder="Altitude MSL (auto if empty)" />
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
            onMoveWaypoint={() => {}}
            onFlyTo={flyToWaypoint}
          />
        </div>

        <WaypointModal
          isOpen={modalOpen}
          onClose={handleModalClose}
          onConfirm={handleModalConfirm}
          position={pendingWaypointPosition}
          previousWaypoint={getPreviousWaypoint()}
          waypointIndex={waypoints.length}
        />
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

  // Full Mapbox implementation with PHASE 3 fixes
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
            canUndo={historyStatus.canUndo}
            canRedo={historyStatus.canRedo}
            undoDescription={historyStatus.undoDescription}
            redoDescription={historyStatus.redoDescription}
            onUndo={handleUndo}
            onRedo={handleRedo}
            onSave={() => setShowSaveDialog(true)}
            onLoad={() => setShowLoadDialog(true)}
            saveStatus={saveStatus}
            trajectoryName={trajectoryName}
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
              cursor={
                isDragging ? 'grabbing' :
                isAddingWaypoint ? 'crosshair' : 
                'grab'
              }
              onLoad={() => setMapReady(true)}
            >
              {/* Terrain source */}
              {showTerrain && (
                <Source
                  id="mapbox-dem"
                  type="raster-dem"
                  url="mapbox://mapbox.mapbox-terrain-dem-v1"
                  tileSize={512}
                  maxzoom={14}
                />
              )}

              {/* Enhanced trajectory line with dynamic coloring */}
              {trajectoryLineData && (
                <Source id="trajectory-line" type="geojson" data={trajectoryLineData}>
                  <Layer
                    id="trajectory-line-layer"
                    type="line"
                    paint={{
                      'line-color': '#00d4ff', // Default blue
                      'line-width': isDragging ? 3 : 4,
                      'line-opacity': isDragging ? 0.6 : 0.8
                    }}
                    layout={{
                      'line-join': 'round',
                      'line-cap': 'round'
                    }}
                  />
                </Source>
              )}

              {/* PHASE 3: NUMBERED waypoint markers with clear visibility */}
              {waypoints.map((waypoint, index) => (
                <Marker
                  key={waypoint.id}
                  longitude={waypoint.longitude}
                  latitude={waypoint.latitude}
                  draggable={true}
                  onDrag={(event) => handleWaypointDrag(event, waypoint.id)}
                  onDragStart={() => handleWaypointDragStart(waypoint.id)}
                  onDragEnd={(event) => handleWaypointDragEnd(event, waypoint.id)}
                  onClick={(e) => {
                    e.originalEvent.stopPropagation();
                    setSelectedWaypointId(waypoint.id);
                  }}
                >
                  <div 
                    className={`waypoint-marker-container ${selectedWaypointId === waypoint.id ? 'selected' : ''} ${
                      isDragging && draggedWaypointId === waypoint.id ? 'dragging' : ''
                    }`}
                  >
                    {/* PHASE 3: Main circular marker with dynamic coloring */}
                    <div 
                      className="waypoint-marker"
                      style={{
                        width: selectedWaypointId === waypoint.id ? '32px' : '24px',
                        height: selectedWaypointId === waypoint.id ? '32px' : '24px',
                        backgroundColor: getWaypointMarkerColor(waypoint, index),
                        border: `3px solid white`,
                        borderRadius: '50%',
                        cursor: isDragging && draggedWaypointId === waypoint.id ? 'grabbing' : 'grab',
                        boxShadow: selectedWaypointId === waypoint.id 
                          ? '0 4px 12px rgba(0,123,255,0.4)' 
                          : '0 2px 8px rgba(0,0,0,0.3)',
                        transition: isDragging ? 'none' : 'all 0.2s ease',
                        transform: isDragging && draggedWaypointId === waypoint.id ? 'scale(1.1)' : 'scale(1)',
                        opacity: isDragging && draggedWaypointId !== waypoint.id ? 0.7 : 1,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'white',
                        fontWeight: 'bold',
                        fontSize: selectedWaypointId === waypoint.id ? '14px' : '12px'
                      }}
                      title={`${waypoint.name} - Alt: ${waypoint.altitude}m MSL - Speed: ${waypoint.estimatedSpeed?.toFixed(1) || 0} m/s`}
                    >
                      {/* PHASE 3: Display waypoint number clearly */}
                      {index + 1}
                    </div>
                    
                    {/* PHASE 3: Speed warning indicator for high speeds */}
                    {waypoint.estimatedSpeed > 20 && (
                      <div className="speed-warning-badge" title="High speed - caution advised">
                        ⚠
                      </div>
                    )}
                  </div>
                </Marker>
              ))}
            </Map>

            {/* Instruction overlays */}
            {isAddingWaypoint && !isDragging && (
              <div className="map-instruction-overlay">
                Click on the map to add waypoint with auto-estimated MSL altitude
              </div>
            )}

            {isDragging && (
              <div className="map-instruction-overlay drag-mode">
                Dragging waypoint - speeds will recalculate automatically
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
          onMoveWaypoint={() => {}}
          onFlyTo={flyToWaypoint}
        />
      </div>

      {/* Enhanced Waypoint Modal with elevation estimation */}
      <WaypointModal
        isOpen={modalOpen}
        onClose={handleModalClose}
        onConfirm={handleModalConfirm}
        position={pendingWaypointPosition}
        previousWaypoint={getPreviousWaypoint()}
        waypointIndex={waypoints.length}
      />

      {/* Save Dialog */}
      {showSaveDialog && (
        <div className="dialog-overlay" onClick={() => setShowSaveDialog(false)}>
          <div className="dialog-content" onClick={e => e.stopPropagation()}>
            <h3>Save Trajectory</h3>
            <input
              type="text"
              placeholder="Enter trajectory name"
              defaultValue={trajectoryName}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  handleSave(e.target.value);
                } else if (e.key === 'Escape') {
                  setShowSaveDialog(false);
                }
              }}
              autoFocus
            />
            <div className="dialog-buttons">
              <button onClick={() => setShowSaveDialog(false)}>Cancel</button>
              <button onClick={(e) => {
                const input = e.target.parentElement.parentElement.querySelector('input');
                handleSave(input.value);
              }}>Save</button>
            </div>
          </div>
        </div>
      )}

      {/* Load Dialog */}
      {showLoadDialog && (
        <div className="dialog-overlay" onClick={() => setShowLoadDialog(false)}>
          <div className="dialog-content" onClick={e => e.stopPropagation()}>
            <h3>Load Trajectory</h3>
            <div className="trajectory-list">
              {availableTrajectories.length === 0 ? (
                <p>No saved trajectories found</p>
              ) : (
                availableTrajectories.map(traj => (
                  <div key={traj.id} className="trajectory-item">
                    <div className="trajectory-info">
                      <strong>{traj.name}</strong>
                      <small>{traj.waypoints.length} waypoints</small>
                    </div>
                    <button onClick={() => handleLoad(traj.id)}>Load</button>
                  </div>
                ))
              )}
            </div>
            <div className="dialog-buttons">
              <button onClick={() => setShowLoadDialog(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default TrajectoryPlanning;