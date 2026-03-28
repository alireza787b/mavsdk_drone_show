// src/pages/TrajectoryPlanning.js

import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';

// Import existing trajectory components
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import WaypointModal from '../components/trajectory/WaypointModal';
import SwarmTrajectoryTransferDialog from '../components/trajectory/SwarmTrajectoryTransferDialog';
import TrajectoryExportDialog from '../components/trajectory/TrajectoryExportDialog';

import { 
  calculateTrajectoryStats, 
  recalculateAfterDrag,
  calculateWaypointSpeeds,
  TIMING_MODES,
  YAW_CONSTANTS
} from '../utilities/SpeedCalculator';
import { TrajectoryStateManager, ACTION_TYPES } from '../utilities/TrajectoryStateManager';
import { TrajectoryStorage } from '../utilities/TrajectoryStorage';
import { getSwarmClusterStatus, uploadSwarmTrajectory } from '../services/droneApiService';

// Leaflet fallback components
import { useMapContext } from '../contexts/MapContext';
import LeafletMapBase from '../components/map/LeafletMapBase';
import MapFallbackBanner from '../components/map/MapFallbackBanner';
import MapProviderToggle from '../components/map/MapProviderToggle';
import { Marker as LMarker, Polyline as LPolyline, useMapEvents } from 'react-leaflet';
import L from 'leaflet';

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
} catch {
  mapboxAvailable = false;
}

// Leaflet click handler component for adding waypoints
const LeafletClickHandler = ({ isAddingWaypoint, isDragging, onMapClick }) => {
  useMapEvents({
    click(e) {
      if (!isAddingWaypoint || isDragging) return;
      onMapClick({
        lngLat: { lng: e.latlng.lng, lat: e.latlng.lat },
      });
    },
  });
  return null;
};

// Create numbered waypoint icon for Leaflet
const createWaypointIcon = (index, color) =>
  L.divIcon({
    html: `<div style="width:40px;height:40px;border-radius:50%;background:${color};color:#fff;font-size:14px;font-weight:bold;display:flex;align-items:center;justify-content:center;border:3px solid #fff;box-shadow:0 2px 8px rgba(0,0,0,0.3)">${index + 1}</div>`,
    className: '',
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });

const TrajectoryPlanning = () => {
  const { provider, isMapboxAvailable: ctxMapboxAvailable } = useMapContext();
  const useLeaflet = provider === 'leaflet' || !ctxMapboxAvailable;

  // Enhanced state management with state manager
  const mapRef = useRef(null);
  const importInputRef = useRef(null);
  const stateManagerRef = useRef(new TrajectoryStateManager());
  const storageRef = useRef(new TrajectoryStorage());
  
  // Core state
  const [waypoints, setWaypoints] = useState([]);
  const [selectedWaypointId, setSelectedWaypointId] = useState(null);
  const [isAddingWaypoint, setIsAddingWaypoint] = useState(false);
  const [showTerrain, setShowTerrain] = useState(true);
  const [sceneMode, setSceneMode] = useState('3D');

  // Enhanced state
  const [historyStatus, setHistoryStatus] = useState({ canUndo: false, canRedo: false });
  const [saveStatus, setSaveStatus] = useState({ saved: true, autoSaveTime: null });
  const [trajectoryName, setTrajectoryName] = useState('');
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [showLoadDialog, setShowLoadDialog] = useState(false);
  const [showExportDialog, setShowExportDialog] = useState(false);
  const [showSwarmTransferDialog, setShowSwarmTransferDialog] = useState(false);
  const [availableTrajectories, setAvailableTrajectories] = useState([]);
  const [plannerNotice, setPlannerNotice] = useState(null);
  const [swarmTransferState, setSwarmTransferState] = useState({
    loading: false,
    submitting: false,
    clusters: [],
    selectedLeaderId: '',
    error: '',
    successMessage: '',
  });

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

  const initializeServices = useCallback(() => {
    stateManagerRef.current.setInitialState({
      waypoints: [],
      selectedWaypointId: null,
    });
  }, []);

  const loadAvailableTrajectories = useCallback(() => {
    const trajectories = storageRef.current.getAllTrajectories();
    setAvailableTrajectories(trajectories);
  }, []);

  // Update history status when waypoints change
  useEffect(() => {
    const status = stateManagerRef.current.getHistoryStatus();
    setHistoryStatus(status);
    setSaveStatus(prev => ({ ...prev, saved: false }));
  }, [waypoints]);

  const setOperationNotice = useCallback((text, tone = 'info', options = {}) => {
    setPlannerNotice({
      text,
      tone,
      actionLabel: options.actionLabel || '',
      actionHandler: options.actionHandler || null,
      dismissLabel: options.dismissLabel || '',
    });
  }, []);

  const clearOperationNotice = useCallback(() => {
    setPlannerNotice(null);
  }, []);

  const applyTrajectoryToPlanner = useCallback((trajectory, successMessage) => {
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(trajectory.waypoints || []);

    stateManagerRef.current.executeAction(
      ACTION_TYPES.LOAD_TRAJECTORY,
      {
        waypoints: waypointsWithCorrectSpeeds,
        selectedWaypointId: null,
      },
      `Load ${trajectory.name || 'trajectory'}`
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    setTrajectoryName(trajectory.name || '');
    setSelectedWaypointId(null);
    setSaveStatus({ saved: true, autoSaveTime: Date.now() });
    clearOperationNotice();

    if (successMessage) {
      setOperationNotice(successMessage, 'success');
    }
  }, [clearOperationNotice, setOperationNotice]);

  const trajectoryStats = useMemo(() => {
    return calculateTrajectoryStats(waypoints);
  }, [waypoints]);

  const addWaypointWithData = useCallback((position, waypointData) => {
    // Always allow waypoint creation (Phase 3 requirement)
    const speedFeasible = true;

    const newWaypoint = {
      id: `waypoint-${Date.now()}`,
      name: `Waypoint ${waypoints.length + 1}`,
      latitude: position.latitude,
      longitude: position.longitude,
      altitude: waypointData.altitude,
      timeFromStart: waypointData.timeFromStart,
      timingMode: waypointData.timingMode || TIMING_MODES.MANUAL_TIME,
      preferredSpeed: waypointData.preferredSpeed || 0,
      estimatedSpeed: 0, // Will be calculated in the recalculation phase
      speedFeasible: speedFeasible,
      terrainInfo: waypointData.terrainInfo,
      groundElevation: waypointData.groundElevation || 0,
      terrainAccurate: waypointData.terrainAccurate !== false,
      time: waypointData.timeFromStart,
      speed: 0, // Legacy compatibility
      index: waypoints.length + 1,
      // Aviation standard heading data
      heading: waypointData.heading || 0,
      headingMode: waypointData.headingMode || YAW_CONSTANTS.AUTO,
      calculatedHeading: waypointData.calculatedHeading || 0
    };

    // Create new waypoints array with the added waypoint
    const newWaypoints = [...waypoints, newWaypoint];
    
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
  }, [waypoints]);

  const updateWaypoint = useCallback((waypointId, updates) => {
    const updatedWaypoints = waypoints.map(wp => 
      wp.id === waypointId ? { ...wp, ...updates } : wp
    );
    
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(updatedWaypoints);
    
    stateManagerRef.current.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      { waypointId, updates, waypoints: waypointsWithCorrectSpeeds },
      `Update waypoint ${waypointId}`
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    
    // Mark as unsaved
    setSaveStatus({ saved: false, autoSaveTime: null });
  }, [waypoints]);

  const deleteWaypoint = useCallback((waypointId) => {
    const filteredWaypoints = waypoints.filter(wp => wp.id !== waypointId);
    
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(filteredWaypoints);
    
    stateManagerRef.current.executeAction(
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

  const handleMarkerDragEnd = useCallback((waypointId, newPosition) => {
    const updatedWaypoints = waypoints.map(wp =>
      wp.id === waypointId
        ? { ...wp, latitude: newPosition.latitude, longitude: newPosition.longitude }
        : wp
    );

    const waypointsWithRecalculatedSpeeds = recalculateAfterDrag(updatedWaypoints, waypointId);

    stateManagerRef.current.executeAction(
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

  // Handle marker click
  const handleMarkerClick = useCallback((waypointId) => {
    setSelectedWaypointId(waypointId);
  }, []);

  const clearTrajectory = useCallback(() => {
    if (waypoints.length === 0) return;

    setOperationNotice(
      `Clear all ${waypoints.length} waypoint${waypoints.length === 1 ? '' : 's'} from the planner?`,
      'warning',
      {
        actionLabel: 'Clear Path',
        dismissLabel: 'Keep Path',
        actionHandler: () => {
          stateManagerRef.current.executeAction(
            ACTION_TYPES.CLEAR_TRAJECTORY,
            { waypoints: [], selectedWaypointId: null },
            'Clear trajectory'
          );

          setWaypoints([]);
          setSelectedWaypointId(null);
          setSaveStatus({ saved: false, autoSaveTime: null });
          clearOperationNotice();
        },
      }
    );
  }, [clearOperationNotice, setOperationNotice, waypoints.length]);

  const handleUndo = useCallback(() => {
    const previousState = stateManagerRef.current.undo();
    if (previousState?.state) {
      const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(previousState.state.waypoints || []);

      setWaypoints(waypointsWithCorrectSpeeds);
      setSelectedWaypointId(previousState.state.selectedWaypointId || null);
      setSaveStatus({ saved: false, autoSaveTime: null });
      clearOperationNotice();
    }
  }, [clearOperationNotice]);

  const handleRedo = useCallback(() => {
    const nextState = stateManagerRef.current.redo();
    if (nextState?.state) {
      const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(nextState.state.waypoints || []);

      setWaypoints(waypointsWithCorrectSpeeds);
      setSelectedWaypointId(nextState.state.selectedWaypointId || null);
      setSaveStatus({ saved: false, autoSaveTime: null });
      clearOperationNotice();
    }
  }, [clearOperationNotice]);

  // Save trajectory functionality
  const handleSave = useCallback(async (name) => {
    if (!name.trim()) {
      setOperationNotice('Enter a trajectory name before saving.', 'warning');
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
      setOperationNotice(result.message, 'success');
    } else {
      setOperationNotice(`Save failed: ${result.error}`, 'error');
    }
  }, [loadAvailableTrajectories, setOperationNotice, trajectoryStats, waypoints]);

  // FIXED: Load trajectory with speed recalculation
  const handleLoad = useCallback(async (identifier) => {
    const result = await storageRef.current.loadTrajectory(identifier);
    
    if (result.success) {
      const trajectory = result.trajectory;
      applyTrajectoryToPlanner(
        trajectory,
        `Loaded ${trajectory.name} with ${(trajectory.waypoints || []).length} waypoints.`
      );
      setShowLoadDialog(false);
    } else {
      setOperationNotice(`Load failed: ${result.error}`, 'error');
    }
  }, [applyTrajectoryToPlanner, setOperationNotice]);

  const handleImportRequest = useCallback(() => {
    importInputRef.current?.click();
  }, []);

  const handleImportFileChange = useCallback(async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';

    if (!file) {
      return;
    }

    const result = await storageRef.current.importTrajectory(file);

    if (result.success) {
      applyTrajectoryToPlanner(
        result.trajectory,
        `Imported ${file.name} and loaded it into the planner.`
      );
      loadAvailableTrajectories();
    } else {
      setOperationNotice(`Import failed: ${result.error}`, 'error');
    }
  }, [applyTrajectoryToPlanner, loadAvailableTrajectories, setOperationNotice]);

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

  // Initialize services on component mount
  useEffect(() => {
    initializeServices();
    loadAvailableTrajectories();
  }, [initializeServices, loadAvailableTrajectories]);

  useEffect(() => {
    const autoSaveInterval = setInterval(autoSave, 30000);
    return () => {
      clearInterval(autoSaveInterval);
    };
  }, [autoSave]);

  // Enhanced map interaction handlers
  const handleMapClick = useCallback((event) => {
    if (!isAddingWaypoint || isDragging) return;

    const { lng, lat } = event.lngLat || { lng: event.longitude, lat: event.latitude };
    
    setPendingWaypointPosition({ latitude: lat, longitude: lng });
    setModalOpen(true);
  }, [isAddingWaypoint, isDragging]);

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
    if (mapRef.current && mapboxAvailable && !useLeaflet) {
      try {
        mapRef.current.flyTo({
          center: [waypoint.longitude, waypoint.latitude],
          zoom: 15,
          pitch: 60,
          duration: 2000
        });
      } catch (err) {}
    } else {
      // Leaflet mode: update viewState so map re-centers
      setViewState(prev => ({
        ...prev,
        latitude: waypoint.latitude,
        longitude: waypoint.longitude,
        zoom: 15,
      }));
    }
  }, [useLeaflet]);

  // Enhanced location select with elevation estimation
  const handleLocationSelect = useCallback((longitude, latitude) => {
    if (mapRef.current && mapboxAvailable && !useLeaflet) {
      try {
        mapRef.current.flyTo({
          center: [longitude, latitude],
          zoom: 12,
          duration: 3000
        });
      } catch (err) {}
    } else {
      // Leaflet mode: update viewState
      setViewState(prev => ({
        ...prev,
        latitude,
        longitude,
        zoom: 12,
      }));
    }

  }, [useLeaflet]);

  const openSwarmTransferDialog = useCallback(() => {
    if (waypoints.length === 0) {
      setOperationNotice('Add at least one waypoint before assigning a leader trajectory to the swarm.', 'warning');
      return;
    }

    clearOperationNotice();
    setShowSwarmTransferDialog(true);
    setSwarmTransferState((prev) => ({
      ...prev,
      loading: true,
      error: '',
      successMessage: '',
    }));

    getSwarmClusterStatus()
      .then((data) => {
        const clusters = [...(data.clusters || [])].sort(
          (a, b) => Number(a.leader_id) - Number(b.leader_id)
        );

        setSwarmTransferState((prev) => ({
          ...prev,
          loading: false,
          clusters,
          selectedLeaderId:
            clusters.find((cluster) => Number(cluster.leader_id) === Number(prev.selectedLeaderId))?.leader_id ||
            clusters[0]?.leader_id ||
            '',
        }));
      })
      .catch((loadError) => {
        setSwarmTransferState((prev) => ({
          ...prev,
          loading: false,
          clusters: [],
          selectedLeaderId: '',
          error: loadError?.response?.data?.error || loadError.message || 'Failed to load swarm cluster status.',
        }));
      });
  }, [clearOperationNotice, setOperationNotice, waypoints.length]);

  const closeSwarmTransferDialog = useCallback(() => {
    setShowSwarmTransferDialog(false);
    setSwarmTransferState((prev) => ({
      ...prev,
      error: '',
      successMessage: '',
    }));
  }, []);

  const handleUploadCurrentTrajectory = useCallback(async (leaderId) => {
    if (waypoints.length === 0) {
      throw new Error('No trajectory is currently loaded in the planner.');
    }

    const csvContent = storageRef.current.convertToCSV(waypoints);
    const csvBlob = new Blob([csvContent], { type: 'text/csv' });
    const result = await uploadSwarmTrajectory(leaderId, csvBlob, `Drone ${leaderId}.csv`);

    setOperationNotice(
      result.message || `Leader ${leaderId} trajectory uploaded. Review and process the formation on Swarm Trajectory.`,
      'success'
    );

    return result;
  }, [setOperationNotice, waypoints]);

  const handleSendTrajectoryToSwarm = useCallback(async () => {
    const leaderId = swarmTransferState.selectedLeaderId;

    if (!leaderId || waypoints.length === 0) {
      return;
    }

    setSwarmTransferState((prev) => ({
      ...prev,
      submitting: true,
      error: '',
      successMessage: '',
    }));

    try {
      const result = await handleUploadCurrentTrajectory(leaderId);

      setSwarmTransferState((prev) => ({
        ...prev,
        submitting: false,
        successMessage:
          result.message ||
          `Trajectory uploaded for Leader ${leaderId}. Next step: process the swarm formation.`,
      }));

      const refreshed = await getSwarmClusterStatus();
      const clusters = [...(refreshed.clusters || [])].sort(
        (a, b) => Number(a.leader_id) - Number(b.leader_id)
      );

      setSwarmTransferState((prev) => ({
        ...prev,
        clusters,
      }));
    } catch (submitError) {
      setSwarmTransferState((prev) => ({
        ...prev,
        submitting: false,
        error: submitError?.response?.data?.error || submitError.message || 'Failed to upload trajectory.',
      }));
    }
  }, [handleUploadCurrentTrajectory, swarmTransferState.selectedLeaderId, waypoints.length]);

  const openExportDialog = useCallback(() => {
    if (waypoints.length === 0) {
      setOperationNotice('No waypoints are available to export.', 'warning');
      return;
    }

    setShowExportDialog(true);
  }, [setOperationNotice, waypoints.length]);

  const handleExportTrajectory = useCallback(async (format) => {
    const name = trajectoryName || 'trajectory';
    const result = await storageRef.current.exportCurrentTrajectory(name, waypoints, format, {
      source: 'trajectory-planning',
      stats: trajectoryStats,
      savedName: trajectoryName || null,
    });

    if (result.success) {
      setShowExportDialog(false);
      setOperationNotice(result.message, 'success');
    } else {
      setOperationNotice(`Export failed: ${result.error}`, 'error');
    }
  }, [setOperationNotice, trajectoryName, trajectoryStats, waypoints]);

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

  const getWaypointColor = useCallback((waypoint, index) => {
    if (index === 0) return '#28a745'; // Start - Green
    if (index === waypoints.length - 1) return '#dc3545'; // End - Red
    if (!waypoint.speedFeasible) return '#ffc107'; // Warning - Yellow
    return '#007bff'; // Default - Blue
  }, [waypoints.length]);

  const plannerNoticeBanner = plannerNotice ? (
    <div className={`trajectory-planner-notice ${plannerNotice.tone || 'info'}`}>
      <div className="trajectory-planner-notice__copy">{plannerNotice.text}</div>
      <div className="trajectory-planner-notice__actions">
        {plannerNotice.actionLabel && plannerNotice.actionHandler && (
          <button
            type="button"
            className="trajectory-planner-notice__action"
            onClick={plannerNotice.actionHandler}
          >
            {plannerNotice.actionLabel}
          </button>
        )}
        <button type="button" onClick={clearOperationNotice}>
          {plannerNotice.dismissLabel || 'Dismiss'}
        </button>
      </div>
    </div>
  ) : null;

  const swarmTransferDialog = (
    <SwarmTrajectoryTransferDialog
      isOpen={showSwarmTransferDialog}
      onClose={closeSwarmTransferDialog}
      onSubmit={handleSendTrajectoryToSwarm}
      clusters={swarmTransferState.clusters}
      loading={swarmTransferState.loading}
      submitting={swarmTransferState.submitting}
      selectedLeaderId={swarmTransferState.selectedLeaderId}
      onSelectLeaderId={(leaderId) => {
        setSwarmTransferState((prev) => ({
          ...prev,
          selectedLeaderId: leaderId,
          error: '',
          successMessage: '',
        }));
      }}
      error={swarmTransferState.error}
      successMessage={swarmTransferState.successMessage}
      trajectoryName={trajectoryName}
      waypointCount={waypoints.length}
      totalDistance={trajectoryStats.totalDistance}
      totalTime={trajectoryStats.totalTime}
    />
  );

  const exportDialog = (
    <TrajectoryExportDialog
      isOpen={showExportDialog}
      onClose={() => setShowExportDialog(false)}
      onExport={handleExportTrajectory}
      trajectoryName={trajectoryName}
    />
  );

  // Leaflet fallback: show Leaflet map when Mapbox unavailable
  if (useLeaflet || (!mapboxAvailable && !mapboxToken) || !mapboxToken) {
    return (
      <div className="trajectory-planning">
        <input
          ref={importInputRef}
          type="file"
          accept=".csv,.json,text/csv,application/json"
          hidden
          onChange={handleImportFileChange}
        />
        <div className="trajectory-header">
          <div className="header-left">
            <h1>Trajectory Planning</h1>
            <SearchBar onLocationSelect={handleLocationSelect} />
            <MapProviderToggle />
          </div>
          <TrajectoryStats stats={trajectoryStats} />
        </div>

        <div className="trajectory-container">
          <div className="trajectory-main">
            <TrajectoryToolbar
              isAddingWaypoint={isAddingWaypoint}
              onToggleAddWaypoint={() => setIsAddingWaypoint(!isAddingWaypoint)}
              onClearTrajectory={clearTrajectory}
              onExportTrajectory={openExportDialog}
              showTerrain={false}
              onToggleTerrain={() => {}}
              sceneMode="2D"
              onSceneModeChange={() => {}}
              waypointCount={waypoints.length}
              canUndo={historyStatus.canUndo}
              canRedo={historyStatus.canRedo}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onSave={() => setShowSaveDialog(true)}
              onLoad={() => setShowLoadDialog(true)}
              onImport={handleImportRequest}
              onSendToSwarm={openSwarmTransferDialog}
              canSendToSwarm={waypoints.length > 0}
              saveStatus={saveStatus}
              trajectoryName={trajectoryName}
            />

            {plannerNoticeBanner}

            <div className="map-container">
              <MapFallbackBanner />
              <LeafletMapBase
                center={[viewState.latitude || 35.7262, viewState.longitude || 51.2721]}
                zoom={viewState.zoom || 12}
                defaultLayer="osm"
                style={{ width: '100%', height: '100%' }}
              >
                <LeafletClickHandler
                  isAddingWaypoint={isAddingWaypoint}
                  isDragging={isDragging}
                  onMapClick={handleMapClick}
                />

                {/* Trajectory line */}
                {waypoints.length >= 2 && (
                  <LPolyline
                    positions={waypoints.map((wp) => [wp.latitude, wp.longitude])}
                    pathOptions={{ color: '#00d4ff', weight: 4, opacity: 0.8 }}
                  />
                )}

                {/* Waypoint markers */}
                {waypoints.map((waypoint, index) => (
                  <LMarker
                    key={waypoint.id}
                    position={[waypoint.latitude, waypoint.longitude]}
                    icon={createWaypointIcon(index, getWaypointColor(waypoint, index))}
                    draggable={true}
                    eventHandlers={{
                      dragstart: () => {
                        setIsDragging(true);
                        setDraggedWaypointId(waypoint.id);
                      },
                      dragend: (e) => {
                        const { lat, lng } = e.target.getLatLng();
                        handleMarkerDragEnd(waypoint.id, { latitude: lat, longitude: lng });
                      },
                      click: () => handleMarkerClick(waypoint.id),
                    }}
                  />
                ))}
              </LeafletMapBase>

              {/* Instruction overlays */}
              {isAddingWaypoint && !isDragging && (
                <div className="map-instruction-overlay">
                  <div className="instruction-content">
                    <span className="instruction-icon">📍</span>
                    <span className="instruction-text">Click on the map to add waypoint</span>
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

        <WaypointModal
          isOpen={modalOpen}
          onClose={handleModalClose}
          onConfirm={handleModalConfirm}
          position={pendingWaypointPosition}
          previousWaypoint={waypoints.length > 0 ? waypoints[waypoints.length - 1] : null}
          waypointIndex={waypoints.length + 1}
          mapRef={mapRef}
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
                  if (e.key === 'Enter') handleSave(e.target.value);
                  else if (e.key === 'Escape') setShowSaveDialog(false);
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

        {exportDialog}
        {swarmTransferDialog}
      </div>
    );
  }

  return (
    <div className="trajectory-planning">
      <input
        ref={importInputRef}
        type="file"
        accept=".csv,.json,text/csv,application/json"
        hidden
        onChange={handleImportFileChange}
      />
      <div className="trajectory-header">
        <div className="header-left">
          <h1>Trajectory Planning</h1>
          <SearchBar onLocationSelect={handleLocationSelect} />
          <MapProviderToggle />
        </div>
        <TrajectoryStats stats={trajectoryStats} />
      </div>

      <div className="trajectory-container">
        <div className="trajectory-main">
          <TrajectoryToolbar
            isAddingWaypoint={isAddingWaypoint}
            onToggleAddWaypoint={() => setIsAddingWaypoint(!isAddingWaypoint)}
            onClearTrajectory={clearTrajectory}
            onExportTrajectory={openExportDialog}
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
            onImport={handleImportRequest}
            onSendToSwarm={openSwarmTransferDialog}
            canSendToSwarm={waypoints.length > 0}
            saveStatus={saveStatus}
            trajectoryName={trajectoryName}
          />

          {plannerNoticeBanner}

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
            >
              {showTerrain && (
                <Source
                  id="mapbox-dem"
                  type="raster-dem"
                  url="mapbox://mapbox.terrain-rgb"
                  tileSize={512}
                  maxzoom={14}
                />
              )}

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
                  <span className="instruction-text">Click on the map to add a waypoint with terrain-aware altitude context</span>
                </div>
              </div>
            )}

            {isDragging && (
              <div className="map-instruction-overlay drag-mode">
                <div className="instruction-content">
                  <span className="instruction-icon">✋</span>
                  <span className="instruction-text">Dragging a waypoint recalculates timing and speed automatically</span>
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

      <WaypointModal
        isOpen={modalOpen}
        onClose={handleModalClose}
        onConfirm={handleModalConfirm}
        position={pendingWaypointPosition}
        previousWaypoint={waypoints.length > 0 ? waypoints[waypoints.length - 1] : null}
        waypointIndex={waypoints.length + 1}
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

      {exportDialog}
      {swarmTransferDialog}
    </div>
  );
};

export default TrajectoryPlanning;
