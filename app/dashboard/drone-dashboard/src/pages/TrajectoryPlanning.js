// src/pages/TrajectoryPlanning.js
// PHASE 3 FIXES: Numbered waypoints, speed cautions, elevation estimation
// CRITICAL FIXES: Map markers show numbers, speed violations as warnings only
// ALL FIXES INTEGRATED: Search z-index, real terrain, corrected speed logic

import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { distance } from '@turf/turf';

// Import existing trajectory components
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import WaypointModal from '../components/trajectory/WaypointModal';

// FIXED IMPORTS: Add new speed calculation functions
import { 
  calculateSpeed, 
  calculateTrajectoryStats, 
  suggestOptimalTime, 
  recalculateAfterDrag,
  calculateWaypointSpeeds, // ADDED: New correct speed calculation
  calculateSpeedForNewWaypoint // ADDED: For waypoint creation
} from '../utilities/SpeedCalculator';
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
 * TrajectoryPlanning Component - ALL PHASE 3 FIXES INTEGRATED
 * Fixed Features:
 * - Search suggestions appear above toolbar (z-index fix)
 * - Real terrain elevation API integration in waypoint modal
 * - CORRECTED speed logic: each waypoint shows speed FROM current TO next
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

  // Optional: Debug speed calculation (can be removed in production)
  useEffect(() => {
    if (process.env.NODE_ENV === 'development' && waypoints.length > 0) {
      console.group('🎯 Speed Calculation Debug - FIXED LOGIC');
      waypoints.forEach((wp, index) => {
        if (index < waypoints.length - 1) {
          console.log(`Waypoint ${index + 1}: ${wp.estimatedSpeed?.toFixed(1) || '0.0'} m/s to reach Waypoint ${index + 2}`);
        } else {
          console.log(`Waypoint ${index + 1}: ${wp.estimatedSpeed?.toFixed(1) || '0.0'} m/s (final waypoint)`);
        }
      });
      console.groupEnd();
    }
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

  // FIXED: Calculate trajectory statistics using corrected speed calculations
  const trajectoryStats = useMemo(() => {
    return calculateTrajectoryStats(waypoints);
  }, [waypoints]);

  // Get previous waypoint for speed calculation
  const getPreviousWaypoint = useCallback(() => {
    return waypoints.length > 0 ? waypoints[waypoints.length - 1] : null;
  }, [waypoints]);

  // CRITICAL FIX: Enhanced waypoint management with corrected speed logic
  const addWaypointWithData = useCallback((position, waypointData) => {
    const previousWaypoint = getPreviousWaypoint();
    
    // FIXED: Calculate speed correctly - this will be applied to the PREVIOUS waypoint
    // The new waypoint itself will get its speed in the recalculation phase
    let estimatedSpeed = 0;
    if (previousWaypoint) {
      estimatedSpeed = calculateSpeedForNewWaypoint(position, waypointData, waypoints);
    }

    // Always allow waypoint creation (Phase 3 requirement)
    const speedFeasible = true;

    const newWaypoint = {
      id: `waypoint-${Date.now()}`,
      name: `Waypoint ${waypoints.length + 1}`,
      latitude: position.latitude,
      longitude: position.longitude,
      altitude: waypointData.altitude,
      timeFromStart: waypointData.timeFromStart,
      estimatedSpeed: 0, // Will be calculated in the recalculation phase
      speedFeasible: speedFeasible,
      terrainInfo: waypointData.terrainInfo,
      time: waypointData.timeFromStart,
      speed: 0, // Legacy compatibility
      index: waypoints.length + 1
    };

    // Create new waypoints array with the added waypoint
    const newWaypoints = [...waypoints, newWaypoint];
    
    // CRITICAL FIX: Recalculate all speeds with correct FROM current TO next logic
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(newWaypoints);

    // Use state manager for undo/redo support
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.ADD_WAYPOINT,
      { waypoint: newWaypoint, waypoints: waypointsWithCorrectSpeeds },
      `Add ${newWaypoint.name}`
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    setSelectedWaypointId(newState.selectedWaypointId);
    setIsAddingWaypoint(false);
  }, [waypoints, getPreviousWaypoint]);

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

  // FIXED: Update waypoint with speed recalculation
  const updateWaypoint = useCallback((waypointId, updates) => {
    const updatedWaypoints = waypoints.map(wp => 
      wp.id === waypointId ? { ...wp, ...updates } : wp
    );
    
    // CRITICAL FIX: Recalculate speeds after waypoint update
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(updatedWaypoints);
    
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      { waypointId, updates, waypoints: waypointsWithCorrectSpeeds },
      `Update waypoint ${waypointId}`
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    
    // Mark as unsaved
    setSaveStatus({ saved: false, autoSaveTime: null });
  }, [waypoints]);

  // FIXED: Delete waypoint with speed recalculation  
  const deleteWaypoint = useCallback((waypointId) => {
    const filteredWaypoints = waypoints.filter(wp => wp.id !== waypointId);
    
    // CRITICAL FIX: Recalculate speeds after waypoint deletion
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(filteredWaypoints);
    
    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.DELETE_WAYPOINT,
      { waypointId, waypoints: waypointsWithCorrectSpeeds },
      `Delete waypoint ${waypointId}`
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    
    if (selectedWaypointId === waypointId) {
      setSelectedWaypointId(null);
    }
    
    setSaveStatus({ saved: false, autoSaveTime: null });
  }, [waypoints, selectedWaypointId]);

  // FIXED: Drag-drop handler with correct speed recalculation
  const handleMarkerDragEnd = useCallback((waypointId, newPosition) => {
    const updatedWaypoints = waypoints.map(wp =>
      wp.id === waypointId
        ? { ...wp, latitude: newPosition.latitude, longitude: newPosition.longitude }
        : wp
    );

    // CRITICAL FIX: Use corrected drag recalculation logic
    const waypointsWithRecalculatedSpeeds = recalculateAfterDrag(updatedWaypoints, waypointId);

    const newState = stateManagerRef.current.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      { 
        waypointId, 
        updates: { 
          latitude: newPosition.latitude, 
          longitude: newPosition.longitude 
        },
        waypoints: waypointsWithRecalculatedSpeeds 
      },
      `Move waypoint ${waypointId}`
    );

    setWaypoints(waypointsWithRecalculatedSpeeds);
    setIsDragging(false);
    setDraggedWaypointId(null);
    
    setSaveStatus({ saved: false, autoSaveTime: null });
  }, [waypoints]);

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
    handleMarkerDragEnd(waypointId, { latitude: lat, longitude: lng });
  }, [handleMarkerDragEnd]);

  // Handle marker click
  const handleMarkerClick = useCallback((waypointId) => {
    setSelectedWaypointId(waypointId);
  }, []);

  // FIXED: Clear trajectory function
  const clearTrajectory = useCallback(() => {
    if (waypoints.length === 0) return;
    
    const confirmation = window.confirm(
      `Delete all ${waypoints.length} waypoints? This action cannot be undone.`
    );
    
    if (confirmation) {
      const newState = stateManagerRef.current.executeAction(
        ACTION_TYPES.CLEAR_WAYPOINTS,
        { waypoints: [] },
        'Clear trajectory'
      );
      
      setWaypoints([]);
      setSelectedWaypointId(null);
      setSaveStatus({ saved: false, autoSaveTime: null });
    }
  }, [waypoints.length]);

  // FIXED: Undo/Redo with correct speed handling
  const handleUndo = useCallback(() => {
    const previousState = stateManagerRef.current.undo();
    if (previousState) {
      // CRITICAL FIX: Ensure undone state has correct speeds
      const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(previousState.waypoints || []);
      
      setWaypoints(waypointsWithCorrectSpeeds);
      setSelectedWaypointId(previousState.selectedWaypointId || null);
      setSaveStatus({ saved: false, autoSaveTime: null });
    }
  }, []);

  const handleRedo = useCallback(() => {
    const nextState = stateManagerRef.current.redo();
    if (nextState) {
      // CRITICAL FIX: Ensure redone state has correct speeds
      const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(nextState.waypoints || []);
      
      setWaypoints(waypointsWithCorrectSpeeds);
      setSelectedWaypointId(nextState.selectedWaypointId || null);
      setSaveStatus({ saved: false, autoSaveTime: null });
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

  // FIXED: Load trajectory with speed recalculation
  const handleLoad = useCallback(async (identifier) => {
    const result = await storageRef.current.loadTrajectory(identifier);
    
    if (result.success) {
      const trajectory = result.trajectory;
      
      // CRITICAL FIX: Ensure loaded waypoints have correct speeds
      const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(trajectory.waypoints || []);
      
      const newState = stateManagerRef.current.executeAction(
        ACTION_TYPES.LOAD_TRAJECTORY,
        { 
          waypoints: waypointsWithCorrectSpeeds,
          name: trajectory.name || 'Loaded Trajectory'
        },
        `Load ${trajectory.name}`
      );

      setWaypoints(waypointsWithCorrectSpeeds);
      setTrajectoryName(trajectory.name || '');
      setSelectedWaypointId(null);
      setShowLoadDialog(false);
      setSaveStatus({ saved: true, autoSaveTime: new Date() });
      
      console.info(`Loaded trajectory: ${trajectory.name} with ${waypointsWithCorrectSpeeds.length} waypoints`);
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

  // FIXED: Modal confirm handler for real terrain + correct speeds
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
        speeds: waypoints.slice(0, -1).map(wp => wp.estimatedSpeed || 0) // FIXED: Use correct speed mapping
      }
    };
  }, [waypoints]);

  // FIXED: Get waypoint color based on index and corrected speed status
  const getWaypointColor = useCallback((waypoint, index) => {
    if (index === 0) return '#28a745'; // Start - Green
    if (index === waypoints.length - 1) return '#dc3545'; // End - Red
    if (!waypoint.speedFeasible) return '#ffc107'; // Warning - Yellow
    return '#007bff'; // Default - Blue
  }, [waypoints.length]);

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
                <div className="fallback-header">
                  <span className="fallback-icon">🎯</span>
                  <h2>3D Trajectory Planning</h2>
                </div>
                <p className="fallback-description">Enhanced trajectory planning with 3D terrain visualization requires a free Mapbox token.</p>
                
                <div className="fallback-features">
                  <h3>✨ Enhanced Features:</h3>
                  <div className="features-grid">
                    <div className="feature-item">
                      <span className="feature-icon">🗺️</span>
                      <span>Real terrain elevation</span>
                    </div>
                    <div className="feature-item">
                      <span className="feature-icon">⚡</span>
                      <span>Smart speed calculations</span>
                    </div>
                    <div className="feature-item">
                      <span className="feature-icon">📱</span>
                      <span>Responsive design</span>
                    </div>
                    <div className="feature-item">
                      <span className="feature-icon">🔄</span>
                      <span>Undo/redo system</span>
                    </div>
                    <div className="feature-item">
                      <span className="feature-icon">💾</span>
                      <span>Save/load trajectories</span>
                    </div>
                    <div className="feature-item">
                      <span className="feature-icon">🎨</span>
                      <span>Professional UI</span>
                    </div>
                  </div>
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

        {/* FIXED: Enhanced Waypoint Modal with real terrain integration */}
        <WaypointModal
          isOpen={modalOpen}
          onClose={handleModalClose}
          onConfirm={handleModalConfirm}
          position={pendingWaypointPosition}
          previousWaypoint={getPreviousWaypoint()}
          waypointIndex={waypoints.length + 1}
          mapRef={mapRef} // CRITICAL: Pass map reference for real terrain queries
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
          <p>3D trajectory planning with real terrain elevation requires a Mapbox access token.</p>
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

  // Full Mapbox implementation with ALL PHASE 3 FIXES
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
                'default'
              }
              onLoad={() => {
                setMapReady(true);
                console.info('Map loaded with terrain source for elevation queries');
              }}
            >
              {/* FIXED: Terrain source for real elevation queries */}
              {showTerrain && (
                <Source
                  id="mapbox-dem"
                  type="raster-dem"
                  url="mapbox://mapbox.terrain-rgb"
                  tileSize={512}
                  maxzoom={14}
                />
              )}

              {/* FIXED: Trajectory line visualization with corrected speed logic */}
              {waypoints.length > 1 && (
                <Source
                  id="trajectory-line"
                  type="geojson"
                  data={{
                    type: 'Feature',
                    geometry: {
                      type: 'LineString',
                      coordinates: waypoints.map(wp => [wp.longitude, wp.latitude])
                    }
                  }}
                >
                  <Layer
                    id="trajectory-path"
                    type="line"
                    paint={{
                      'line-color': [
                        'case',
                        ['all', 
                          ['has', 'speedFeasible'],
                          ['==', ['get', 'speedFeasible'], false]
                        ],
                        '#dc3545', // Red for infeasible speeds
                        '#00d4ff'  // Blue for feasible speeds
                      ],
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

              {/* FIXED: Enhanced waypoint markers with numbers and speed warnings */}
              {waypoints.map((waypoint, index) => (
                <Marker
                  key={waypoint.id}
                  longitude={waypoint.longitude}
                  latitude={waypoint.latitude}
                  draggable={!isDragging}
                  onDragStart={() => {
                    setIsDragging(true);
                    setDraggedWaypointId(waypoint.id);
                  }}
                  onDragEnd={(e) => {
                    const newPosition = {
                      longitude: e.lngLat.lng,
                      latitude: e.lngLat.lat
                    };
                    handleMarkerDragEnd(waypoint.id, newPosition);
                  }}
                  onClick={(e) => {
                    e.originalEvent.stopPropagation();
                    handleMarkerClick(waypoint.id);
                  }}
                >
                  <div className={`waypoint-marker-container ${
                    selectedWaypointId === waypoint.id ? 'selected' : ''
                  } ${draggedWaypointId === waypoint.id ? 'dragging' : ''}`}>
                    <div
                      className="waypoint-marker"
                      style={{
                        width: 40,
                        height: 40,
                        borderRadius: '50%',
                        background: getWaypointColor(waypoint, index),
                        color: 'white',
                        fontSize: '14px',
                        fontWeight: 'bold',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        border: '3px solid white',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                        cursor: isDragging ? 'grabbing' : 'grab'
                      }}
                    >
                      {index + 1}
                    </div>
                    
                    {/* PHASE 3: Speed warning badge */}
                    {!waypoint.speedFeasible && (
                      <div className="speed-warning-badge" title="Speed warning - check timing">
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
                <div className="instruction-content">
                  <span className="instruction-icon">📍</span>
                  <span className="instruction-text">Click on the map to add waypoint with real terrain elevation</span>
                </div>
              </div>
            )}

            {isDragging && (
              <div className="map-instruction-overlay drag-mode">
                <div className="instruction-content">
                  <span className="instruction-icon">✋</span>
                  <span className="instruction-text">Dragging waypoint - speeds will recalculate automatically</span>
                </div>
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

      {/* FIXED: Enhanced Waypoint Modal with real terrain integration */}
      <WaypointModal
        isOpen={modalOpen}
        onClose={handleModalClose}
        onConfirm={handleModalConfirm}
        position={pendingWaypointPosition}
        previousWaypoint={getPreviousWaypoint()}
        waypointIndex={waypoints.length + 1} // FIXED: Correct index for display
        mapRef={mapRef} // CRITICAL: Pass map reference for real terrain queries
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