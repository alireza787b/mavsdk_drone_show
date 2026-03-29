// src/pages/TrajectoryPlanning.js

import React, { useState, useRef, useCallback, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

// Import existing trajectory components
import WaypointPanel from '../components/trajectory/WaypointPanel';
import TrajectoryToolbar from '../components/trajectory/TrajectoryToolbar';
import SearchBar from '../components/trajectory/SearchBar';
import TrajectoryStats from '../components/trajectory/TrajectoryStats';
import TrajectorySegmentReview from '../components/trajectory/TrajectorySegmentReview';
import WaypointModal from '../components/trajectory/WaypointModal';
import SwarmTrajectoryTransferDialog from '../components/trajectory/SwarmTrajectoryTransferDialog';
import TrajectoryExportDialog from '../components/trajectory/TrajectoryExportDialog';
import TrajectoryLibraryDialog from '../components/trajectory/TrajectoryLibraryDialog';
import TrajectoryPolicyNotes from '../components/trajectory/TrajectoryPolicyNotes';

import { 
  ALTITUDE_REFERENCE,
  buildTrajectorySegments,
  calculateTrajectoryStats, 
  calculateWaypointSpeeds,
  getTrajectorySegmentColor,
  TIMING_MODES,
  YAW_CONSTANTS
} from '../utilities/SpeedCalculator';
import { TrajectoryStateManager, ACTION_TYPES } from '../utilities/TrajectoryStateManager';
import { TrajectoryStorage } from '../utilities/TrajectoryStorage';
import { getSwarmClusterStatus, uploadSwarmTrajectory } from '../services/droneApiService';
import { buildTrajectoryMissionReadiness } from '../utilities/trajectoryMissionReadiness';
import {
  formatTrajectoryAltitudeEnvelope,
  formatTrajectorySpeedEnvelope,
  formatTrajectorySpeedEnvelopeDetail,
} from '../constants/trajectoryMissionPolicy';
import {
  getTrajectoryOperatorPolicyNotes,
  getTrajectoryWorkflowStages,
} from '../utilities/trajectoryAuthoringGuidance';
import { resolveWaypointTerrainContext } from '../utilities/trajectoryTerrainContext';

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
  const navigate = useNavigate();
  const { provider, isMapboxAvailable: ctxMapboxAvailable } = useMapContext();
  const useLeaflet = provider === 'leaflet' || !ctxMapboxAvailable;

  // Enhanced state management with state manager
  const mapRef = useRef(null);
  const importInputRef = useRef(null);
  const stateManagerRef = useRef(new TrajectoryStateManager());
  const storageRef = useRef(new TrajectoryStorage());
  const terrainRefreshTokenRef = useRef(new Map());
  const waypointsRef = useRef([]);
  
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
    waypointsRef.current = waypoints;
  }, [waypoints]);

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

  const advanceTerrainRefreshToken = useCallback((waypointId) => {
    const nextToken = (terrainRefreshTokenRef.current.get(waypointId) || 0) + 1;
    terrainRefreshTokenRef.current.set(waypointId, nextToken);
    return nextToken;
  }, []);

  const isLatestTerrainRefresh = useCallback(
    (waypointId, token) => terrainRefreshTokenRef.current.get(waypointId) === token,
    []
  );

  const buildTrajectorySourceNotice = useCallback((sourceLabel, trajectory, readiness) => {
    const waypointCount = (trajectory.waypoints || []).length;
    const name = trajectory.name || 'trajectory';

    if (readiness.blockers.length > 0) {
      return {
        tone: 'warning',
        message: `${sourceLabel} ${name} with ${waypointCount} waypoint${waypointCount === 1 ? '' : 's'}. ${readiness.posture.summary}`,
      };
    }

    if (readiness.advisories.length > 0) {
      return {
        tone: 'info',
        message: `${sourceLabel} ${name} with ${waypointCount} waypoint${waypointCount === 1 ? '' : 's'}. ${readiness.posture.summary}`,
      };
    }

    return {
      tone: 'success',
      message: `${sourceLabel} ${name} with ${waypointCount} waypoint${waypointCount === 1 ? '' : 's'}. Ready for swarm assignment.`,
    };
  }, []);

  const applyTrajectoryToPlanner = useCallback((trajectory, sourceLabel) => {
    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(trajectory.waypoints || []);
    const nextStats = calculateTrajectoryStats(waypointsWithCorrectSpeeds);
    const nextReadiness = buildTrajectoryMissionReadiness({
      waypoints: waypointsWithCorrectSpeeds,
      stats: nextStats,
    });
    const notice = buildTrajectorySourceNotice(sourceLabel, trajectory, nextReadiness);

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

    setOperationNotice(notice.message, notice.tone);
  }, [buildTrajectorySourceNotice, clearOperationNotice, setOperationNotice]);

  const trajectoryStats = useMemo(() => {
    return calculateTrajectoryStats(waypoints);
  }, [waypoints]);

  const plannerMissionReadiness = useMemo(
    () => buildTrajectoryMissionReadiness({ waypoints, stats: trajectoryStats }),
    [trajectoryStats, waypoints]
  );
  const trajectorySegments = useMemo(() => buildTrajectorySegments(waypoints), [waypoints]);
  const activeSegmentId = useMemo(
    () => trajectorySegments.find((segment) => segment.toWaypointId === selectedWaypointId)?.id || '',
    [selectedWaypointId, trajectorySegments]
  );

  const plannerBriefItems = useMemo(
    () => [
      ...plannerMissionReadiness.blockers,
      ...plannerMissionReadiness.advisories,
      ...plannerMissionReadiness.notes,
    ],
    [plannerMissionReadiness]
  );

  const plannerWorkflowCards = useMemo(() => {
    const terrainCoverage = trajectoryStats.terrainCoverage || {};
    const estimatedTerrainCount = (terrainCoverage.estimated || 0) + (terrainCoverage.unknown || 0);
    const altitudeReferenceCounts = trajectoryStats.altitudeReferenceCounts || {};
    const authoringBreakdown = trajectoryStats.authoringBreakdown || {};
    const routeEntryCount = authoringBreakdown.routeEntryAnchors || (waypoints.length > 0 ? 1 : 0);
    const speedDrivenLegCount = authoringBreakdown.speedDrivenLegs || 0;
    const timeDrivenLegCount = authoringBreakdown.timeDrivenLegs || 0;
    const terrainAssistedWaypointCount = altitudeReferenceCounts[ALTITUDE_REFERENCE.AGL] || 0;
    const currentPathDetail = waypoints.length > 0
      ? [
          `${trajectoryStats.totalTime.toFixed(0)}s authored route`,
          `${routeEntryCount} route-entry anchor`,
          `${speedDrivenLegCount} speed-driven leg${speedDrivenLegCount === 1 ? '' : 's'}`,
          `${timeDrivenLegCount} time-driven leg${timeDrivenLegCount === 1 ? '' : 's'}`,
          terrainAssistedWaypointCount > 0
            ? `${terrainAssistedWaypointCount} terrain-assisted waypoint${terrainAssistedWaypointCount === 1 ? '' : 's'}`
            : null,
        ].filter(Boolean).join(' • ')
      : 'Add the first waypoint or import a route to begin authoring.';

    return [
      {
        label: 'Planner Scope',
        value: 'Top leaders • Global MSL',
        detail: 'Followers are generated later from the current Swarm Design hierarchy and offsets. The authored route stays global lat/lon with stored MSL altitude; PX4 launch/home truth is only used during execution checks and recovery.',
      },
      {
        label: 'Current Path',
        value: waypoints.length > 0 ? `${waypoints.length} waypoint${waypoints.length === 1 ? '' : 's'}` : 'No path yet',
        detail: currentPathDetail,
      },
      {
        label: 'Launch Readiness',
        value: waypoints.length === 0
          ? 'Not ready'
          : plannerMissionReadiness.posture.label,
        detail: waypoints.length === 0
          ? 'Author the leader route first, then send it to a swarm cluster.'
          : estimatedTerrainCount > 0 && plannerMissionReadiness.advisories.length === 0 && plannerMissionReadiness.blockers.length === 0
            ? `Verify ${estimatedTerrainCount} terrain estimate${estimatedTerrainCount === 1 ? '' : 's'} before launch.`
            : plannerMissionReadiness.posture.summary,
      },
      {
        label: 'Mission Envelope',
        value: formatTrajectorySpeedEnvelope(),
        detail: `${formatTrajectoryAltitudeEnvelope()} • ${formatTrajectorySpeedEnvelopeDetail()}`,
      },
    ];
  }, [plannerMissionReadiness, trajectoryStats, waypoints.length]);

  const plannerWorkflowStages = useMemo(() => getTrajectoryWorkflowStages(), []);
  const plannerPolicyNotes = useMemo(
    () => getTrajectoryOperatorPolicyNotes({ stats: trajectoryStats, waypointCount: waypoints.length }),
    [trajectoryStats, waypoints.length]
  );

  const addWaypointWithData = useCallback((position, waypointData) => {
    const newWaypoint = {
      id: `waypoint-${Date.now()}`,
      name: `Waypoint ${waypoints.length + 1}`,
      latitude: position.latitude,
      longitude: position.longitude,
      altitude: waypointData.altitude,
      altitudeReference: waypointData.altitudeReference || ALTITUDE_REFERENCE.MSL,
      targetAgl: waypointData.targetAgl || 0,
      timeFromStart: waypointData.timeFromStart,
      timingMode: waypointData.timingMode || TIMING_MODES.MANUAL_TIME,
      preferredSpeed: waypointData.preferredSpeed || 0,
      estimatedSpeed: 0, // Will be calculated in the recalculation phase
      // Recalculated immediately after insertion; keep the transient shape stable.
      speedFeasible: true,
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

  const commitWaypointUpdate = useCallback(async (
    waypointId,
    updates,
    historyLabel = `Update waypoint ${waypointId}`
  ) => {
    const currentWaypoints = waypointsRef.current;
    const currentWaypoint = currentWaypoints.find((wp) => wp.id === waypointId);
    if (!currentWaypoint) {
      return false;
    }

    let normalizedUpdates = { ...updates };
    const hasCoordinateUpdate =
      Object.prototype.hasOwnProperty.call(updates, 'latitude') ||
      Object.prototype.hasOwnProperty.call(updates, 'longitude');
    const refreshToken = advanceTerrainRefreshToken(waypointId);

    if (hasCoordinateUpdate) {
      const latitude = updates.latitude ?? currentWaypoint.latitude;
      const longitude = updates.longitude ?? currentWaypoint.longitude;
      const terrainPatch = await resolveWaypointTerrainContext(
        { ...currentWaypoint, ...updates, latitude, longitude },
        { latitude, longitude }
      );

      if (!isLatestTerrainRefresh(waypointId, refreshToken)) {
        return false;
      }

      normalizedUpdates = {
        ...normalizedUpdates,
        ...terrainPatch,
      };

      if (terrainPatch.terrainAccurate === false) {
        setOperationNotice(
          `${currentWaypoint.name || 'Waypoint'} terrain context was refreshed with estimated elevation at the new coordinates. Review clearance before launch.`,
          'warning'
        );
      }
    }

    const latestWaypoints = waypointsRef.current;
    const updatedWaypoints = latestWaypoints.map((wp) =>
      wp.id === waypointId ? { ...wp, ...normalizedUpdates } : wp
    );

    const waypointsWithCorrectSpeeds = calculateWaypointSpeeds(updatedWaypoints);

    stateManagerRef.current.executeAction(
      ACTION_TYPES.UPDATE_WAYPOINT,
      { waypointId, updates: normalizedUpdates, waypoints: waypointsWithCorrectSpeeds },
      historyLabel
    );

    setWaypoints(waypointsWithCorrectSpeeds);
    setSaveStatus({ saved: false, autoSaveTime: null });
    return true;
  }, [
    advanceTerrainRefreshToken,
    isLatestTerrainRefresh,
    setOperationNotice,
  ]);

  const updateWaypoint = useCallback(async (waypointId, updates) => {
    await commitWaypointUpdate(waypointId, updates, `Update waypoint ${waypointId}`);
  }, [commitWaypointUpdate]);

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

  const handleMarkerDragEnd = useCallback(async (waypointId, newPosition) => {
    try {
      await commitWaypointUpdate(
        waypointId,
        {
          latitude: newPosition.latitude,
          longitude: newPosition.longitude,
        },
        `Move waypoint ${waypointId}`
      );
    } finally {
      setIsDragging(false);
      setDraggedWaypointId(null);
    }
  }, [commitWaypointUpdate]);

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

  const handleLoad = useCallback(async (identifier) => {
    const result = await storageRef.current.loadTrajectory(identifier);
    
    if (result.success) {
      const trajectory = result.trajectory;
      applyTrajectoryToPlanner(
        trajectory,
        'Loaded'
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
        'Imported'
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

  const handleSelectSegment = useCallback((segment) => {
    setSelectedWaypointId(segment.toWaypointId);
    const waypoint = waypoints.find((item) => item.id === segment.toWaypointId);
    if (waypoint) {
      flyToWaypoint(waypoint);
    }
  }, [flyToWaypoint, waypoints]);

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
    const uploadTone = plannerMissionReadiness.blockers.length > 0
      ? 'warning'
      : plannerMissionReadiness.advisories.length > 0
        ? 'info'
        : 'success';
    const uploadMessage = plannerMissionReadiness.blockers.length > 0
      ? `Leader ${leaderId} path assigned as a draft. ${plannerMissionReadiness.posture.summary}`
      : plannerMissionReadiness.advisories.length > 0
        ? `Leader ${leaderId} path assigned. ${plannerMissionReadiness.posture.summary}`
        : result.message || `Leader ${leaderId} path assigned. Review and process the formation on Swarm Trajectory.`;

    setOperationNotice(uploadMessage, uploadTone, {
      actionLabel: 'Open Swarm Trajectory',
      dismissLabel: 'Stay in Planner',
      actionHandler: () => navigate('/swarm-trajectory'),
    });

    return result;
  }, [navigate, plannerMissionReadiness.advisories.length, plannerMissionReadiness.blockers.length, plannerMissionReadiness.posture.summary, setOperationNotice, waypoints]);

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
          plannerMissionReadiness.blockers.length > 0
            ? `Path assigned to Leader ${leaderId} as a draft. Resolve blockers before processing or launch.`
            : plannerMissionReadiness.advisories.length > 0
              ? `Path assigned to Leader ${leaderId}. Operator review is still required before processing or launch.`
              : result.message ||
                `Path assigned to Leader ${leaderId}. Next step: process the swarm formation.`,
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
  }, [handleUploadCurrentTrajectory, plannerMissionReadiness.advisories.length, plannerMissionReadiness.blockers.length, swarmTransferState.selectedLeaderId, waypoints.length]);

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
    if (waypoint.speedStatus === 'impossible') return '#dc3545';
    if (waypoint.speedStatus === 'marginal' || !waypoint.speedFeasible) return '#f5a623';
    return '#007bff'; // Default - Blue
  }, [waypoints.length]);

  const pathRiskLegend = waypoints.length > 1 ? (
    <div className="trajectory-path-legend" aria-label="Trajectory path risk legend">
      <div className="trajectory-path-legend__item">
        <span
          className="trajectory-path-legend__swatch"
          style={{ backgroundColor: getTrajectorySegmentColor('feasible') }}
        />
        <span>Nominal leg</span>
      </div>
      <div className="trajectory-path-legend__item">
        <span
          className="trajectory-path-legend__swatch"
          style={{ backgroundColor: getTrajectorySegmentColor('marginal') }}
        />
        <span>Review leg</span>
      </div>
      <div className="trajectory-path-legend__item">
        <span
          className="trajectory-path-legend__swatch"
          style={{ backgroundColor: getTrajectorySegmentColor('impossible') }}
        />
        <span>Unsafe leg</span>
      </div>
    </div>
  ) : null;

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
      stats={trajectoryStats}
      missionReadiness={plannerMissionReadiness}
      onOpenSwarmTrajectory={() => navigate('/swarm-trajectory')}
      onOpenSwarmDesign={() => navigate('/swarm-design')}
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

  const saveDialog = (
    <TrajectoryLibraryDialog
      mode="save"
      isOpen={showSaveDialog}
      onClose={() => setShowSaveDialog(false)}
      onSave={handleSave}
      initialName={trajectoryName}
      currentStats={trajectoryStats}
      currentWaypointCount={waypoints.length}
    />
  );

  const loadDialog = (
    <TrajectoryLibraryDialog
      mode="load"
      isOpen={showLoadDialog}
      onClose={() => setShowLoadDialog(false)}
      onLoad={handleLoad}
      trajectories={availableTrajectories}
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

        <TrajectorySegmentReview
          segments={trajectorySegments}
          activeSegmentId={activeSegmentId}
          onSelectSegment={handleSelectSegment}
        />

        <div className="trajectory-workflow-brief" aria-label="Trajectory planning workflow brief">
          <div className="trajectory-workflow-brief__cards">
            {plannerWorkflowCards.map((card) => (
              <div key={card.label} className="trajectory-workflow-brief__card">
                <span className="trajectory-workflow-brief__label">{card.label}</span>
                <strong className="trajectory-workflow-brief__value">{card.value}</strong>
                <span className="trajectory-workflow-brief__detail">{card.detail}</span>
              </div>
            ))}
          </div>
          <div className="trajectory-workflow-brief__stages" aria-label="Trajectory planning mission stages">
            {plannerWorkflowStages.map((stage, index) => (
              <div key={stage.key} className="trajectory-workflow-brief__stage">
                <span className="trajectory-workflow-brief__stage-index">{index + 1}</span>
                <div className="trajectory-workflow-brief__stage-copy">
                  <strong>{stage.label}</strong>
                  <span>{stage.detail}</span>
                </div>
              </div>
            ))}
          </div>
          {plannerBriefItems.length > 0 ? (
            <div className="trajectory-workflow-brief__alerts">
              {plannerBriefItems.map((item) => (
                <div
                  key={`${item.code}-${item.text}`}
                  className={`trajectory-workflow-brief__alert trajectory-workflow-brief__alert--${item.tone}`}
                >
                  {item.text}
                </div>
              ))}
            </div>
          ) : null}
          <TrajectoryPolicyNotes
            notes={plannerPolicyNotes}
            title="Trajectory execution policy"
            className="trajectory-workflow-brief__policy"
          />
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
                {trajectorySegments.map((segment) => (
                  <LPolyline
                    key={segment.id}
                    positions={segment.coordinates.map(([longitude, latitude]) => [latitude, longitude])}
                    pathOptions={{ color: segment.color, weight: 4, opacity: 0.85 }}
                  />
                ))}

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

        {saveDialog}
        {loadDialog}
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

      <TrajectorySegmentReview
        segments={trajectorySegments}
        activeSegmentId={activeSegmentId}
        onSelectSegment={handleSelectSegment}
      />

      <div className="trajectory-workflow-brief" aria-label="Trajectory planning workflow brief">
        <div className="trajectory-workflow-brief__cards">
          {plannerWorkflowCards.map((card) => (
            <div key={card.label} className="trajectory-workflow-brief__card">
              <span className="trajectory-workflow-brief__label">{card.label}</span>
              <strong className="trajectory-workflow-brief__value">{card.value}</strong>
              <span className="trajectory-workflow-brief__detail">{card.detail}</span>
            </div>
          ))}
        </div>
        <div className="trajectory-workflow-brief__stages" aria-label="Trajectory planning mission stages">
          {plannerWorkflowStages.map((stage, index) => (
            <div key={stage.key} className="trajectory-workflow-brief__stage">
              <span className="trajectory-workflow-brief__stage-index">{index + 1}</span>
              <div className="trajectory-workflow-brief__stage-copy">
                <strong>{stage.label}</strong>
                <span>{stage.detail}</span>
              </div>
            </div>
          ))}
        </div>
        {plannerBriefItems.length > 0 ? (
          <div className="trajectory-workflow-brief__alerts">
            {plannerBriefItems.map((item) => (
              <div
                key={`${item.code}-${item.text}`}
                className={`trajectory-workflow-brief__alert trajectory-workflow-brief__alert--${item.tone}`}
              >
                {item.text}
              </div>
            ))}
          </div>
        ) : null}
        <TrajectoryPolicyNotes
          notes={plannerPolicyNotes}
          title="Trajectory execution policy"
          className="trajectory-workflow-brief__policy"
        />
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

              {trajectorySegments.length > 0 && (
                <Source
                  id="trajectory-line"
                  type="geojson"
                  data={{
                    type: 'FeatureCollection',
                    features: trajectorySegments.map((segment) => ({
                      type: 'Feature',
                      properties: {
                        speedStatus: segment.speedStatus,
                      },
                      geometry: {
                        type: 'LineString',
                        coordinates: segment.coordinates,
                      },
                    })),
                  }}
                >
                  <Layer
                    id="trajectory-path"
                    type="line"
                    paint={{
                      'line-color': [
                        'match',
                        ['get', 'speedStatus'],
                        'impossible',
                        '#dc3545',
                        'marginal',
                        '#f5a623',
                        '#00d4ff'
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

            {pathRiskLegend}
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

      {saveDialog}
      {loadDialog}
      {exportDialog}
      {swarmTransferDialog}
    </div>
  );
};

export default TrajectoryPlanning;
