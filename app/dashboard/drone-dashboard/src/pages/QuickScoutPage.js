// src/pages/QuickScoutPage.js
/**
 * QuickScout SAR - Main page composition.
 * Plan mode: draw polygon, select drones, configure, compute plan, launch.
 * Monitor mode: watch mission progress, manage POIs, control drones.
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { toast } from 'react-toastify';
import * as sarApi from '../services/sarApiService';
import {
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
} from '../services/gcsApiService';

// SAR components
import PlanMonitorToggle from '../components/sar/PlanMonitorToggle';
import MissionStatsBar from '../components/sar/MissionStatsBar';
import MissionPlanSidebar from '../components/sar/MissionPlanSidebar';
import MissionMonitorSidebar from '../components/sar/MissionMonitorSidebar';
import MissionActionBar from '../components/sar/MissionActionBar';
import CoveragePreview from '../components/sar/CoveragePreview';
import POIMarkerSystem from '../components/sar/POIMarkerSystem';
import DrawControl, { MapboxSetupInstructions, MapboxDrawActionBar } from '../components/sar/SearchAreaDrawer';

// SearchBar
import SearchBar from '../components/trajectory/SearchBar';

// Leaflet fallback components
import { useMapContext } from '../contexts/MapContext';
import LeafletMapBase from '../components/map/LeafletMapBase';
import LeafletDrawControl from '../components/map/LeafletDrawControl';
import LeafletCoveragePreview from '../components/map/LeafletCoveragePreview';
import LeafletPOIMarkers from '../components/map/LeafletPOIMarkers';
import MapFallbackBanner from '../components/map/MapFallbackBanner';
import MapProviderToggle from '../components/map/MapProviderToggle';
import { Marker as LeafletMarker, useMap } from 'react-leaflet';
import L from 'leaflet';
import {
  DEFAULT_QUICKSCOUT_PROFILE_ID,
  deriveQuickScoutProfileId,
  getQuickScoutProfile,
} from '../utilities/quickScoutProfiles';

// Styles
import '../styles/QuickScout.css';

// Conditional Mapbox imports — only checks if npm package exists;
// actual token/connectivity detection is handled by MapContext.
let Map, Marker;
let mapboxLibAvailable = false;

try {
  const rgl = require('react-map-gl');
  Map = rgl.Map || rgl.default;
  Marker = rgl.Marker;
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxLibAvailable = true;
} catch (e) {
  console.warn('Mapbox not available:', e.message);
}

const DEFAULT_SURVEY_CONFIG = {
  algorithm: 'boustrophedon',
  sweep_width_m: 30,
  overlap_percent: 10,
  cruise_altitude_msl: 50,
  survey_altitude_agl: 40,
  cruise_speed_ms: 10,
  survey_speed_ms: 5,
  use_terrain_following: true,
  camera_interval_s: 2,
};

const ACTIVE_MISSION_STATES = new Set(['executing', 'paused']);
const MONITOR_MISSION_STATES = new Set(['executing', 'paused', 'completed', 'aborted']);

// Create simple drone icon for Leaflet markers
// Note: divIcon HTML must use inline styles — Leaflet injects outside React's CSS scope
const createDroneIcon = (hwId) =>
  L.divIcon({
    html: `<div style="width:20px;height:20px;background:var(--color-primary,#00d4ff);border-radius:50%;border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:#000">${hwId}</div>`,
    className: '',
    iconSize: [20, 20],
    iconAnchor: [10, 10],
  });

// Leaflet flyTo controller — bridges React state to Leaflet imperative API
const LeafletFlyTo = ({ target }) => {
  const map = useMap();
  useEffect(() => {
    if (target) {
      map.flyTo([target.latitude, target.longitude], target.zoom || 15, { duration: 1.5 });
    }
  }, [target, map]);
  return null;
};

const QuickScoutPage = () => {
  const { provider, isMapboxAvailable, mapboxToken } = useMapContext();
  const useLeaflet = provider === 'leaflet' || !isMapboxAvailable || !mapboxLibAvailable;

  // Mode
  const [mode, setMode] = useState('plan');

  // Plan state
  const [searchArea, setSearchArea] = useState([]);
  const [searchAreaSqM, setSearchAreaSqM] = useState(0);
  const [surveyConfig, setSurveyConfig] = useState({ ...DEFAULT_SURVEY_CONFIG });
  const [missionProfileId, setMissionProfileId] = useState(DEFAULT_QUICKSCOUT_PROFILE_ID);
  const [missionLabel, setMissionLabel] = useState('');
  const [missionBrief, setMissionBrief] = useState('');
  const [returnBehavior, setReturnBehavior] = useState('return_home');
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [coveragePlan, setCoveragePlan] = useState(null);
  const [computing, setComputing] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [loadingMissionCatalog, setLoadingMissionCatalog] = useState(false);
  const [missionCatalog, setMissionCatalog] = useState([]);
  const [recoveringMissionId, setRecoveringMissionId] = useState(null);

  // Monitor state
  const [missionId, setMissionId] = useState(null);
  const [missionStatus, setMissionStatus] = useState(null);
  const [pois, setPois] = useState([]);
  const [addingPOI, setAddingPOI] = useState(false);

  // Telemetry
  const [drones, setDrones] = useState([]);

  // Config drones (from config.json)
  const [configDrones, setConfigDrones] = useState([]);

  // Map
  const [viewport, setViewport] = useState({
    longitude: 0, latitude: 0, zoom: 3,
  });
  const poiClickRef = useRef(null);
  const mapRef = useRef(null);
  const drawControlRef = useRef(null);
  const [flyToTarget, setFlyToTarget] = useState(null);
  const autoRecoveryCheckedRef = useRef(false);

  const resetWorkspace = useCallback(() => {
    setMode('plan');
    setSearchArea([]);
    setSearchAreaSqM(0);
    setSurveyConfig({ ...DEFAULT_SURVEY_CONFIG });
    setMissionProfileId(DEFAULT_QUICKSCOUT_PROFILE_ID);
    setMissionLabel('');
    setMissionBrief('');
    setReturnBehavior('return_home');
    setSelectedDrones([]);
    setCoveragePlan(null);
    setMissionId(null);
    setMissionStatus(null);
    setPois([]);
    setAddingPOI(false);
    setRecoveringMissionId(null);
    drawControlRef.current?.reset();
  }, []);

  const refreshMissionCatalog = useCallback(async ({ withLoading = false } = {}) => {
    if (withLoading) {
      setLoadingMissionCatalog(true);
    }

    try {
      const response = await sarApi.listMissions({ limit: 8 });
      const missions = Array.isArray(response?.missions) ? response.missions : [];
      setMissionCatalog(missions);
      return missions;
    } catch (error) {
      return null;
    } finally {
      if (withLoading) {
        setLoadingMissionCatalog(false);
      }
    }
  }, []);

  const applyWorkspace = useCallback((workspace, { preferredMode = null } = {}) => {
    const operation = workspace?.operation;
    const status = workspace?.status;

    if (!operation || !status) {
      return;
    }

    setMissionId(operation.mission_id);
    setMissionStatus(status);
    setPois(status.pois || []);
    setSearchArea(operation.search_area?.points || []);
    setSearchAreaSqM(operation.search_area?.area_sq_m || operation.total_area_sq_m || 0);
    const recoveredSurveyConfig = {
      ...DEFAULT_SURVEY_CONFIG,
      ...(operation.survey_config || {}),
    };
    setSurveyConfig(recoveredSurveyConfig);
    setMissionProfileId(operation.mission_profile || deriveQuickScoutProfileId(recoveredSurveyConfig));
    setMissionLabel(operation.mission_label || '');
    setMissionBrief(operation.mission_brief || '');
    setReturnBehavior(operation.return_behavior || 'return_home');
    setSelectedDrones(
      Array.isArray(operation.pos_ids) && operation.pos_ids.length > 0
        ? operation.pos_ids
        : (operation.plans || []).map((plan) => plan.pos_id)
    );
    setCoveragePlan({
      mission_id: operation.mission_id,
      plans: operation.plans || [],
      total_area_sq_m: operation.total_area_sq_m || 0,
      estimated_coverage_time_s: operation.estimated_coverage_time_s || 0,
      algorithm_used: operation.algorithm_used || DEFAULT_SURVEY_CONFIG.algorithm,
    });

    const recoveredState = status.state || operation.state;
    setMode(preferredMode || (MONITOR_MISSION_STATES.has(recoveredState) ? 'monitor' : 'plan'));
  }, []);

  const handleRecoverMission = useCallback(async (
    targetMissionId,
    { preferredMode = null, silent = false } = {},
  ) => {
    if (!targetMissionId) {
      return;
    }

    setRecoveringMissionId(targetMissionId);
    try {
      const workspace = await sarApi.getMissionWorkspace(targetMissionId);
      applyWorkspace(workspace, { preferredMode });
      await refreshMissionCatalog();
      if (!silent) {
        toast.success(`Opened mission ${targetMissionId}`);
      }
    } catch (error) {
      const detail = error.response?.data?.detail || error.message;
      toast.error(`Unable to recover mission: ${detail}`);
    } finally {
      setRecoveringMissionId(null);
    }
  }, [applyWorkspace, refreshMissionCatalog]);

  // Telemetry polling
  useEffect(() => {
    const fetchTelemetry = async () => {
      try {
        const response = await getFleetTelemetryResponse();
        const telemetry = unwrapFleetTelemetryPayload(response.data);
        const dronesArray = Object.keys(telemetry).map((hw_ID) => ({
          hw_ID, ...telemetry[hw_ID],
        }));
        setDrones(dronesArray);
      } catch (e) {
        // Silent failure
      }
    };
    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 2000);
    return () => clearInterval(interval);
  }, []);

  // Persisted mission catalog / recovery polling
  useEffect(() => {
    let active = true;

    const fetchCatalog = async (withLoading) => {
      const missions = await refreshMissionCatalog({ withLoading });
      if (!active) {
        return;
      }

      if (missions === null || autoRecoveryCheckedRef.current || missionId) {
        return;
      }

      autoRecoveryCheckedRef.current = true;
      const activeMission = missions.find((mission) => ACTIVE_MISSION_STATES.has(mission.state));
      if (activeMission) {
        handleRecoverMission(activeMission.mission_id, {
          preferredMode: 'monitor',
          silent: true,
        });
      }
    };

    fetchCatalog(true);
    const interval = setInterval(() => fetchCatalog(false), 10000);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, [handleRecoverMission, missionId, refreshMissionCatalog]);

  // Fetch config drones on mount
  useEffect(() => {
    const fetchConfigDrones = async () => {
      try {
        const response = await getFleetConfigResponse();
        if (Array.isArray(response.data)) {
          setConfigDrones(response.data);
        }
      } catch (e) {
        // Config not available — not critical
      }
    };
    fetchConfigDrones();
  }, []);

  // Merge config drones with live telemetry
  const mergedDrones = useMemo(() => {
    // Start with config entries
    const merged = configDrones.map((cfg) => {
      const hwId = String(cfg.hw_id);
      const telemetry = drones.find((d) => String(d.hw_ID) === hwId);
      return {
        hw_ID: hwId,
        hw_id: hwId,
        pos_id: cfg.pos_id,
        pos_ID: cfg.pos_id,
        ip: cfg.ip,
        online: !!telemetry,
        ...(telemetry || {}),
      };
    });
    // Add any telemetry drones not in config
    for (const d of drones) {
      const inConfig = configDrones.some((c) => String(c.hw_id) === String(d.hw_ID));
      if (!inConfig) {
        merged.push({ ...d, online: true });
      }
    }
    return merged;
  }, [configDrones, drones]);

  // Mission status polling
  useEffect(() => {
    if (!missionId) return;

    const pollStatus = async () => {
      try {
        const status = await sarApi.getMissionStatus(missionId);
        setMissionStatus(status);

        const poisData = await sarApi.getPOIs(missionId);
        setPois(poisData);
      } catch (e) {
        // Mission may not exist yet
      }
    };
    pollStatus();
    const interval = setInterval(pollStatus, 2000);
    return () => clearInterval(interval);
  }, [missionId]);

  const currentMissionSummary = useMemo(
    () => missionCatalog.find((mission) => mission.mission_id === missionId) || null,
    [missionCatalog, missionId]
  );
  const currentMissionState = missionStatus?.state || currentMissionSummary?.state || null;
  const currentMissionDisplayName = currentMissionSummary?.mission_label || missionLabel || missionId;

  // Center map on first drone with GPS
  useEffect(() => {
    if (viewport.zoom > 5) return; // Already positioned
    const droneWithGPS = drones.find(d => d.position_lat && d.position_long);
    if (droneWithGPS) {
      setViewport({
        longitude: droneWithGPS.position_long,
        latitude: droneWithGPS.position_lat,
        zoom: 15,
      });
    }
  }, [drones, viewport.zoom]);

  // Handlers
  const handleAreaChange = useCallback((points, areaSqM) => {
    setSearchArea(points);
    setSearchAreaSqM(areaSqM);
    setCoveragePlan(null); // Reset plan when area changes
  }, []);

  const handleResetArea = useCallback(() => {
    setSearchArea([]);
    setSearchAreaSqM(0);
    setCoveragePlan(null);
    drawControlRef.current?.reset();
  }, []);

  const handleDroneToggle = useCallback((posId) => {
    setSelectedDrones(prev =>
      prev.includes(posId) ? prev.filter(id => id !== posId) : [...prev, posId]
    );
  }, []);

  const handleMissionProfileChange = useCallback((profileId) => {
    const profile = getQuickScoutProfile(profileId);
    if (!profile) {
      return;
    }

    setMissionProfileId(profileId);
    setSurveyConfig({
      ...DEFAULT_SURVEY_CONFIG,
      ...profile.surveyConfig,
    });
  }, []);

  const handleSurveyConfigChange = useCallback((nextConfig) => {
    setSurveyConfig(nextConfig);
    setMissionProfileId(deriveQuickScoutProfileId(nextConfig));
  }, []);

  const handleComputePlan = useCallback(async () => {
    setComputing(true);
    try {
      const request = {
        search_area: {
          type: 'polygon',
          points: searchArea,
          area_sq_m: searchAreaSqM,
        },
        survey_config: surveyConfig,
        pos_ids: selectedDrones.length > 0 ? selectedDrones : null,
        mission_label: missionLabel || null,
        mission_profile: missionProfileId === 'custom' ? 'custom' : missionProfileId,
        mission_brief: missionBrief || null,
        return_behavior: returnBehavior,
      };
      const response = await sarApi.computePlan(request);
      setCoveragePlan(response);
      setMissionId(response.mission_id);
      await refreshMissionCatalog();
      toast.success(`Plan computed: ${response.plans.length} drones, ${(response.total_area_sq_m / 10000).toFixed(1)} ha`);
    } catch (err) {
      if (err.code === 'ECONNABORTED') {
        toast.error('Planning timed out — try disabling terrain following or reducing area size');
      } else {
        const detail = err.response?.data?.detail || err.message;
        toast.error(`Planning failed: ${detail}`);
      }
    } finally {
      setComputing(false);
    }
  }, [missionBrief, missionLabel, missionProfileId, refreshMissionCatalog, returnBehavior, searchArea, searchAreaSqM, selectedDrones, surveyConfig]);

  const handleLaunchMission = useCallback(async () => {
    if (!missionId) return;
    setLaunching(true);
    try {
      await sarApi.launchMission(missionId);
      await refreshMissionCatalog();
      toast.success('Mission launched!');
      setMode('monitor');
    } catch (err) {
      const detail = err.response?.data?.detail || err.message;
      toast.error(`Launch failed: ${detail}`);
    } finally {
      setLaunching(false);
    }
  }, [missionId, refreshMissionCatalog]);

  const handlePause = useCallback(async () => {
    if (!missionId) return;
    try {
      await sarApi.pauseMission(missionId);
      await refreshMissionCatalog();
      toast.info('Mission paused');
    } catch (err) {
      toast.error('Pause failed');
    }
  }, [missionId, refreshMissionCatalog]);

  const handleResume = useCallback(async () => {
    if (!missionId) return;
    try {
      await sarApi.resumeMission(missionId);
      await refreshMissionCatalog();
      toast.success('Mission resumed');
    } catch (err) {
      toast.error('Resume failed');
    }
  }, [missionId, refreshMissionCatalog]);

  const handleAbort = useCallback(async () => {
    if (!missionId) return;
    try {
      await sarApi.abortMission(missionId);
      await refreshMissionCatalog();
      toast.warning('Mission aborted');
    } catch (err) {
      toast.error('Abort failed');
    }
  }, [missionId, refreshMissionCatalog]);

  const handlePOIAdded = useCallback((poi) => {
    setPois(prev => [...prev, poi]);
    setAddingPOI(false);
  }, []);

  // SearchBar location select handler
  const handleLocationSelect = useCallback((longitude, latitude, _altitude) => {
    const zoom = 15;
    setViewport({ longitude, latitude, zoom });
    if (!useLeaflet && mapRef.current) {
      mapRef.current.flyTo({ center: [longitude, latitude], zoom });
    } else {
      setFlyToTarget({ latitude, longitude, zoom });
    }
  }, [useLeaflet]);

  return (
    <div className="quickscout-page">
      {/* Top Bar */}
      <div className="qs-top-bar">
        <div className="qs-top-bar-left">
          <span className="qs-page-title">QuickScout SAR</span>
          <PlanMonitorToggle mode={mode} onModeChange={setMode} />
          <MapProviderToggle />
          {missionId && (
            <div className="qs-page-chip">
              <span className="qs-page-chip-label">Mission</span>
              <span className="qs-page-chip-value" title={currentMissionDisplayName}>
                {currentMissionDisplayName}
              </span>
              {currentMissionState && (
                <span className={`qs-state-badge ${currentMissionState}`}>
                  {currentMissionState}
                </span>
              )}
            </div>
          )}
          <div className="qs-search-wrapper">
            <SearchBar onLocationSelect={handleLocationSelect} />
          </div>
        </div>
        {mode === 'monitor' && missionId && (
          <button
            className={`qs-btn ${addingPOI ? 'qs-btn-warning' : 'qs-btn-primary'}`}
            onClick={() => setAddingPOI(!addingPOI)}
            style={{ fontSize: 12, padding: '4px 12px' }}
          >
            {addingPOI ? 'Cancel POI' : '+ Add POI'}
          </button>
        )}
      </div>

      {/* Stats Bar (monitor mode) */}
      {mode === 'monitor' && <MissionStatsBar missionStatus={missionStatus} />}

      {/* Main Layout */}
      <div className="qs-main-layout">
        {/* Map */}
        <div className="qs-map-container">
          {useLeaflet && <MapFallbackBanner />}
          {!useLeaflet && mapboxLibAvailable ? (
            <Map
              ref={mapRef}
              initialViewState={viewport}
              mapboxAccessToken={mapboxToken}
              mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
              style={{ width: '100%', height: '100%' }}
              onClick={(e) => {
                if (addingPOI && poiClickRef.current) {
                  poiClickRef.current(e);
                }
              }}
            >
              {mode === 'plan' && (
                <DrawControl
                  onAreaChange={handleAreaChange}
                  controlRef={drawControlRef}
                  initialArea={searchArea}
                />
              )}

              <CoveragePreview
                plans={coveragePlan?.plans}
                missionStatus={missionStatus}
              />

              <POIMarkerSystem
                pois={pois}
                missionId={missionId}
                onPOIAdded={handlePOIAdded}
                addingPOI={addingPOI}
                onMapClick={poiClickRef}
              />

              {/* Drone position markers (online drones only) */}
              {mergedDrones.filter(d => d.online && d.position_lat && d.position_long).map((drone) => (
                <Marker
                  key={drone.hw_ID}
                  latitude={drone.position_lat}
                  longitude={drone.position_long}
                  anchor="center"
                >
                  <div className="qs-drone-marker-icon">
                    {drone.hw_ID}
                  </div>
                </Marker>
              ))}
            </Map>
          ) : useLeaflet ? (
            <LeafletMapBase
              center={[viewport.latitude || 0, viewport.longitude || 0]}
              zoom={viewport.zoom || 3}
              defaultLayer="googleSatellite"
              style={{ width: '100%', height: '100%' }}
            >
              <LeafletFlyTo target={flyToTarget} />

              {mode === 'plan' && <LeafletDrawControl onAreaChange={handleAreaChange} />}

              <LeafletCoveragePreview
                plans={coveragePlan?.plans}
                missionStatus={missionStatus}
              />

              <LeafletPOIMarkers
                pois={pois}
                missionId={missionId}
                onPOIAdded={handlePOIAdded}
                addingPOI={addingPOI}
              />

              {/* Drone position markers (online drones only) */}
              {mergedDrones.filter(d => d.online && d.position_lat && d.position_long).map((drone) => (
                <LeafletMarker
                  key={drone.hw_ID}
                  position={[drone.position_lat, drone.position_long]}
                  icon={createDroneIcon(drone.hw_ID)}
                />
              ))}
            </LeafletMapBase>
          ) : (
            <MapboxSetupInstructions />
          )}

          {/* Mapbox draw instruction bar (plan mode) */}
          {!useLeaflet && mode === 'plan' && (
            <MapboxDrawActionBar
              searchArea={searchArea}
              onReset={handleResetArea}
              onTrash={() => drawControlRef.current?.trash()}
            />
          )}

          {/* Action Bar (monitor mode) */}
          {mode === 'monitor' && (
            <MissionActionBar
              missionState={missionStatus?.state}
              returnBehavior={returnBehavior}
              onResume={handleResume}
              onPause={handlePause}
              onAbort={handleAbort}
            />
          )}
        </div>

        {/* Sidebar */}
        {mode === 'plan' ? (
          <MissionPlanSidebar
            drones={mergedDrones}
            selectedDrones={selectedDrones}
            onDroneToggle={handleDroneToggle}
            surveyConfig={surveyConfig}
            onConfigChange={handleSurveyConfigChange}
            onComputePlan={handleComputePlan}
            onLaunchMission={handleLaunchMission}
            coveragePlan={coveragePlan}
            searchArea={searchArea}
            computing={computing}
            launching={launching}
            missionProfileId={missionProfileId}
            onMissionProfileChange={handleMissionProfileChange}
            missionLabel={missionLabel}
            onMissionLabelChange={setMissionLabel}
            missionBrief={missionBrief}
            onMissionBriefChange={setMissionBrief}
            returnBehavior={returnBehavior}
            onReturnBehaviorChange={setReturnBehavior}
            missionCatalog={missionCatalog}
            currentMissionId={missionId}
            recoveringMissionId={recoveringMissionId}
            loadingMissionCatalog={loadingMissionCatalog}
            onRecoverMission={handleRecoverMission}
            onStartFreshPlan={resetWorkspace}
          />
        ) : (
          <MissionMonitorSidebar
            missionStatus={missionStatus}
            pois={pois}
            missionCatalog={missionCatalog}
            currentMissionId={missionId}
            recoveringMissionId={recoveringMissionId}
            loadingMissionCatalog={loadingMissionCatalog}
            onRecoverMission={handleRecoverMission}
            onDroneClick={(hwId) => {
              // Center map on drone
              const drone = mergedDrones.find(d => d.hw_ID === hwId);
              if (drone?.position_lat && drone?.position_long) {
                setViewport({
                  longitude: drone.position_long,
                  latitude: drone.position_lat,
                  zoom: 16,
                });
              }
            }}
            onPOIClick={(poi) => {
              setViewport({ longitude: poi.lng, latitude: poi.lat, zoom: 17 });
            }}
          />
        )}
      </div>
    </div>
  );
};

export default QuickScoutPage;
