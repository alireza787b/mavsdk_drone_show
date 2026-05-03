// src/pages/QuickScoutPage.js
/**
 * QuickScout SAR - Main page composition.
 * Plan mode: draw polygon, select drones, configure, compute plan, launch.
 * Monitor mode: watch mission progress, manage findings, control drones.
 */

import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { toast } from 'react-toastify';
import { FaFlag, FaSearchLocation } from 'react-icons/fa';
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
import FindingMarkerSystem from '../components/sar/FindingMarkerSystem';
import DrawControl, { MapboxSetupInstructions, MapboxDrawActionBar } from '../components/sar/SearchAreaDrawer';

// SearchBar
import SearchBar from '../components/trajectory/SearchBar';

// Leaflet fallback components
import { useMapContext } from '../contexts/MapContext';
import LeafletMapBase from '../components/map/LeafletMapBase';
import LeafletDrawControl from '../components/map/LeafletDrawControl';
import LeafletCoveragePreview from '../components/map/LeafletCoveragePreview';
import LeafletFindingMarkers from '../components/map/LeafletFindingMarkers';
import MapFallbackBanner from '../components/map/MapFallbackBanner';
import MapProviderToggle from '../components/map/MapProviderToggle';
import {
  Circle as LeafletCircle,
  Marker as LeafletMarker,
  Polygon as LeafletPolygon,
  Polyline as LeafletPolyline,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import {
  DEFAULT_QUICKSCOUT_PROFILE_ID,
  deriveQuickScoutProfileId,
  getQuickScoutProfile,
} from '../utilities/quickScoutProfiles';
import { buildQuickScoutPlanningSignature } from '../utilities/quickScoutPlanningSignature';
import { buildQuickScoutLaunchReadiness } from '../utilities/quickScoutLaunchReadiness';
import { ActionIconButton, DocsLink, StatusBadge } from '../components/ui/OperatorPrimitives';
import {
  buildCorridorGeoJSON,
  buildCorridorPathGeoJSON,
  buildLastKnownPointGeoJSON,
  calculateCorridorAreaSqM,
  calculateCircularAreaSqM,
  normalizeSearchPath,
} from '../utilities/quickScoutSearchGeometry';
import { getPlotThemeColors } from '../utilities/plotThemeColors';

// Styles
import '../styles/QuickScout.css';

// Conditional Mapbox imports — only checks if npm package exists;
// actual token/connectivity detection is handled by MapContext.
let Map, Marker, Source, Layer;
let mapboxLibAvailable = false;

try {
  const rgl = require('react-map-gl');
  Map = rgl.Map || rgl.default;
  Marker = rgl.Marker;
  Source = rgl.Source;
  Layer = rgl.Layer;
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
const DEFAULT_LAST_KNOWN_POINT_RADIUS_M = 120;
const DEFAULT_CORRIDOR_WIDTH_M = 90;

const ACTIVE_MISSION_STATES = new Set(['executing', 'paused']);
const MONITOR_MISSION_STATES = new Set(['executing', 'paused', 'completed', 'aborted']);

const getMissionStateTone = (state) => {
  switch (state) {
    case 'executing':
      return 'success';
    case 'paused':
      return 'warning';
    case 'aborted':
      return 'danger';
    case 'completed':
      return 'info';
    default:
      return 'muted';
  }
};

const hasFiniteCoordinate = (value) => Number.isFinite(Number(value));

const hasDronePosition = (drone) => (
  hasFiniteCoordinate(drone?.position_lat) && hasFiniteCoordinate(drone?.position_long)
);

// Create simple drone icon for Leaflet markers
const createDroneIcon = (hwId) =>
  L.divIcon({
    html: `<div class="qs-drone-marker-icon">${hwId}</div>`,
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
  const mapThemeColors = getPlotThemeColors();

  // Mode
  const [mode, setMode] = useState('plan');

  // Plan state
  const [searchArea, setSearchArea] = useState([]);
  const [searchAreaSqM, setSearchAreaSqM] = useState(0);
  const [missionTemplate, setMissionTemplate] = useState('area_sweep');
  const [searchCenter, setSearchCenter] = useState(null);
  const [searchRadiusM, setSearchRadiusM] = useState(DEFAULT_LAST_KNOWN_POINT_RADIUS_M);
  const [searchPath, setSearchPath] = useState([]);
  const [corridorWidthM, setCorridorWidthM] = useState(DEFAULT_CORRIDOR_WIDTH_M);
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
  const [lastPlannedSignature, setLastPlannedSignature] = useState(null);

  // Monitor state
  const [missionId, setMissionId] = useState(null);
  const [missionStatus, setMissionStatus] = useState(null);
  const [findings, setFindings] = useState([]);
  const [markingFinding, setMarkingFinding] = useState(false);
  const [selectedFinding, setSelectedFinding] = useState(null);
  const [savingFinding, setSavingFinding] = useState(false);
  const [deletingFinding, setDeletingFinding] = useState(false);
  const [missionHandoff, setMissionHandoff] = useState(null);
  const [loadingMissionHandoff, setLoadingMissionHandoff] = useState(false);

  // Telemetry
  const [drones, setDrones] = useState([]);

  // Config drones (from config.json)
  const [configDrones, setConfigDrones] = useState([]);

  // Map
  const [viewport, setViewport] = useState({
    longitude: 0, latitude: 0, zoom: 3,
  });
  const findingClickRef = useRef(null);
  const mapRef = useRef(null);
  const drawControlRef = useRef(null);
  const [flyToTarget, setFlyToTarget] = useState(null);
  const autoRecoveryCheckedRef = useRef(false);

  const focusMap = useCallback((longitude, latitude, zoom = 15) => {
    const nextViewport = { longitude, latitude, zoom };
    setViewport(nextViewport);
    if (!useLeaflet && mapRef.current?.flyTo) {
      mapRef.current.flyTo({ center: [longitude, latitude], zoom });
      return;
    }
    setFlyToTarget({ latitude, longitude, zoom });
  }, [useLeaflet]);

  const resetWorkspace = useCallback(() => {
    setMode('plan');
    setSearchArea([]);
    setSearchAreaSqM(0);
    setMissionTemplate('area_sweep');
    setSearchCenter(null);
    setSearchRadiusM(DEFAULT_LAST_KNOWN_POINT_RADIUS_M);
    setSearchPath([]);
    setCorridorWidthM(DEFAULT_CORRIDOR_WIDTH_M);
    setSurveyConfig({ ...DEFAULT_SURVEY_CONFIG });
    setMissionProfileId(DEFAULT_QUICKSCOUT_PROFILE_ID);
    setMissionLabel('');
    setMissionBrief('');
    setReturnBehavior('return_home');
    setSelectedDrones([]);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
    setMissionId(null);
    setMissionStatus(null);
    setFindings([]);
    setMarkingFinding(false);
    setSelectedFinding(null);
    setSavingFinding(false);
    setDeletingFinding(false);
    setMissionHandoff(null);
    setLoadingMissionHandoff(false);
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

    const recoveredSelectedDrones = Array.isArray(operation.pos_ids) && operation.pos_ids.length > 0
      ? operation.pos_ids
      : (operation.plans || []).map((plan) => plan.pos_id);
    const recoveredFindings = status.findings || [];
    setMissionId(operation.mission_id);
    setMissionStatus(status);
    setFindings(recoveredFindings);
    setMissionHandoff(null);
    setSelectedFinding(recoveredFindings[0] || null);
    setSearchArea(operation.search_area?.points || []);
    setSearchAreaSqM(operation.search_area?.area_sq_m || operation.total_area_sq_m || 0);
    setMissionTemplate(operation.mission_template || 'area_sweep');
    setSearchCenter(operation.search_area?.center || null);
    setSearchRadiusM(operation.search_area?.radius_m || DEFAULT_LAST_KNOWN_POINT_RADIUS_M);
    setSearchPath(operation.search_area?.path || []);
    setCorridorWidthM(operation.search_area?.corridor_width_m || DEFAULT_CORRIDOR_WIDTH_M);
    const recoveredSurveyConfig = {
      ...DEFAULT_SURVEY_CONFIG,
      ...(operation.survey_config || {}),
    };
    setSurveyConfig(recoveredSurveyConfig);
    setMissionProfileId(operation.mission_profile || deriveQuickScoutProfileId(recoveredSurveyConfig));
    setMissionLabel(operation.mission_label || '');
    setMissionBrief(operation.mission_brief || '');
    setReturnBehavior(operation.return_behavior || 'return_home');
    setSelectedDrones(recoveredSelectedDrones);
    setCoveragePlan({
      mission_id: operation.mission_id,
      plans: operation.plans || [],
      total_area_sq_m: operation.total_area_sq_m || 0,
      estimated_coverage_time_s: operation.estimated_coverage_time_s || 0,
      algorithm_used: operation.algorithm_used || DEFAULT_SURVEY_CONFIG.algorithm,
    });
    setLastPlannedSignature(buildQuickScoutPlanningSignature({
      missionTemplate: operation.mission_template || 'area_sweep',
      searchArea: operation.search_area?.points || [],
      searchCenter: operation.search_area?.center || null,
      searchRadiusM: operation.search_area?.radius_m || DEFAULT_LAST_KNOWN_POINT_RADIUS_M,
      searchPath: operation.search_area?.path || [],
      corridorWidthM: operation.search_area?.corridor_width_m || DEFAULT_CORRIDOR_WIDTH_M,
      surveyConfig: recoveredSurveyConfig,
      selectedDrones: recoveredSelectedDrones,
      missionProfileId: operation.mission_profile || deriveQuickScoutProfileId(recoveredSurveyConfig),
      missionLabel: operation.mission_label || '',
      missionBrief: operation.mission_brief || '',
      returnBehavior: operation.return_behavior || 'return_home',
    }));

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
        const findingsData = status?.findings || [];
        setMissionStatus(status);
        setFindings(findingsData);
        setSelectedFinding((current) => {
          if (!current) {
            return findingsData[0] || null;
          }
          return findingsData.find((finding) => finding.id === current.id) || null;
        });
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
  const currentPlanningSignature = useMemo(
    () => buildQuickScoutPlanningSignature({
      missionTemplate,
      searchArea,
      searchCenter,
      searchRadiusM,
      searchPath,
      corridorWidthM,
      surveyConfig,
      selectedDrones,
      missionProfileId,
      missionLabel,
      missionBrief,
      returnBehavior,
    }),
    [corridorWidthM, missionBrief, missionLabel, missionProfileId, missionTemplate, returnBehavior, searchArea, searchCenter, searchPath, searchRadiusM, selectedDrones, surveyConfig],
  );
  const activePlanTargetHwIds = useMemo(
    () => (coveragePlan?.plans || [])
      .map((plan) => String(plan?.hw_id || '').trim())
      .filter(Boolean),
    [coveragePlan],
  );
  const activePlanTargetDrones = useMemo(() => {
    const targetLookup = new Set(activePlanTargetHwIds);
    return mergedDrones.filter((drone) => targetLookup.has(String(drone?.hw_ID || drone?.hw_id || '').trim()));
  }, [activePlanTargetHwIds, mergedDrones]);
  const launchReadiness = useMemo(
    () => buildQuickScoutLaunchReadiness({
      drones: mergedDrones,
      targetHwIds: activePlanTargetHwIds,
    }),
    [activePlanTargetHwIds, mergedDrones],
  );
  const pointSearchPreview = useMemo(
    () => buildLastKnownPointGeoJSON(searchCenter, searchRadiusM),
    [searchCenter, searchRadiusM],
  );
  const corridorSearchPreview = useMemo(
    () => buildCorridorGeoJSON(searchPath, corridorWidthM),
    [corridorWidthM, searchPath],
  );
  const corridorPathPreview = useMemo(
    () => buildCorridorPathGeoJSON(searchPath),
    [searchPath],
  );
  const planNeedsRecompute = Boolean(
    coveragePlan
    && lastPlannedSignature
    && currentPlanningSignature !== lastPlannedSignature
  );
  const currentMissionState = missionStatus?.state || currentMissionSummary?.state || null;
  const currentMissionDisplayName = currentMissionSummary?.mission_label || missionLabel || missionId;
  const missionHandoffRefreshKey = useMemo(() => {
    const findingSignature = findings
      .map((finding) => [
        finding.id,
        finding.status,
        finding.updated_at || finding.timestamp || '',
        (finding.evidence_refs || []).length,
      ].join(':'))
      .sort()
      .join('|');
    const lastCommandSignature = [
      missionStatus?.last_command_summary?.command_id || '',
      missionStatus?.last_command_summary?.action || '',
      missionStatus?.last_command_summary?.effect || '',
    ].join(':');
    return [
      missionId || '',
      missionStatus?.state || '',
      missionStatus?.operation_phase || '',
      lastCommandSignature,
      findingSignature,
    ].join('|');
  }, [
    findings,
    missionId,
    missionStatus?.last_command_summary?.action,
    missionStatus?.last_command_summary?.command_id,
    missionStatus?.last_command_summary?.effect,
    missionStatus?.operation_phase,
    missionStatus?.state,
  ]);

  // Center map on first drone with GPS
  useEffect(() => {
    if (viewport.zoom > 5) return; // Already positioned
    const droneWithGPS = drones.find((d) => hasDronePosition(d));
    if (droneWithGPS) {
      setViewport({
        longitude: droneWithGPS.position_long,
        latitude: droneWithGPS.position_lat,
        zoom: 15,
      });
    }
  }, [drones, viewport.zoom]);

  useEffect(() => {
    let active = true;

    const fetchMissionHandoff = async () => {
      if (!missionId) {
        setMissionHandoff(null);
        setLoadingMissionHandoff(false);
        return;
      }

      setLoadingMissionHandoff(true);
      try {
        const handoff = await sarApi.getMissionHandoff(missionId);
        if (active) {
          setMissionHandoff(handoff);
        }
      } catch (error) {
        if (active) {
          setMissionHandoff(null);
        }
      } finally {
        if (active) {
          setLoadingMissionHandoff(false);
        }
      }
    };

    fetchMissionHandoff();
    return () => {
      active = false;
    };
  }, [missionHandoffRefreshKey, missionId]);

  // Handlers
  const handleAreaChange = useCallback((points, areaSqM) => {
    setSearchArea(points);
    setSearchAreaSqM(areaSqM);
    setCoveragePlan(null); // Reset plan when area changes
    setLastPlannedSignature(null);
  }, []);

  const handleResetDrawGeometry = useCallback(() => {
    if (missionTemplate === 'corridor_search') {
      setSearchPath([]);
    } else {
      setSearchArea([]);
      setSearchAreaSqM(0);
    }
    setCoveragePlan(null);
    setLastPlannedSignature(null);
    drawControlRef.current?.reset();
  }, [missionTemplate]);

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

  const handleMissionTemplateChange = useCallback((templateId) => {
    setMissionTemplate(templateId);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
    if (templateId === 'last_known_point' && !searchCenter) {
      const onlineDrone = mergedDrones.find((drone) => drone.online && hasDronePosition(drone));
      if (onlineDrone) {
        setSearchCenter({
          lat: onlineDrone.position_lat,
          lng: onlineDrone.position_long,
        });
      }
    }
  }, [mergedDrones, searchCenter]);

  const handleSearchCenterChange = useCallback((nextCenter) => {
    setSearchCenter(nextCenter);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, []);

  const handleSearchRadiusChange = useCallback((nextRadiusM) => {
    setSearchRadiusM(nextRadiusM);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, []);

  const handleSearchPathChange = useCallback((nextPath) => {
    setSearchPath(normalizeSearchPath(nextPath));
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, []);

  const handleCorridorWidthChange = useCallback((nextWidthM) => {
    setCorridorWidthM(nextWidthM);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, []);

  const handleUseMapCenter = useCallback(() => {
    if (!Number.isFinite(Number(viewport.latitude)) || !Number.isFinite(Number(viewport.longitude))) {
      return;
    }

    setSearchCenter({
      lat: Number(viewport.latitude),
      lng: Number(viewport.longitude),
    });
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, [viewport.latitude, viewport.longitude]);

  const handleAppendMapCenterToPath = useCallback(() => {
    if (!Number.isFinite(Number(viewport.latitude)) || !Number.isFinite(Number(viewport.longitude))) {
      return;
    }

    handleSearchPathChange([
      ...searchPath,
      {
        lat: Number(viewport.latitude),
        lng: Number(viewport.longitude),
      },
    ]);
  }, [handleSearchPathChange, searchPath, viewport.latitude, viewport.longitude]);

  const handleUndoSearchPathPoint = useCallback(() => {
    handleSearchPathChange(searchPath.slice(0, -1));
  }, [handleSearchPathChange, searchPath]);

  const handleClearSearchPath = useCallback(() => {
    handleSearchPathChange([]);
  }, [handleSearchPathChange]);

  const handleComputePlan = useCallback(async () => {
    setComputing(true);
    try {
      const requestSearchArea = missionTemplate === 'last_known_point'
        ? {
          type: 'point',
          center: searchCenter,
          radius_m: searchRadiusM,
          area_sq_m: calculateCircularAreaSqM(searchRadiusM),
        }
        : missionTemplate === 'corridor_search'
          ? {
            type: 'line',
            path: searchPath,
            corridor_width_m: corridorWidthM,
            area_sq_m: calculateCorridorAreaSqM(searchPath, corridorWidthM),
          }
        : {
          type: 'polygon',
          points: searchArea,
          area_sq_m: searchAreaSqM,
        };
      const request = {
        search_area: requestSearchArea,
        survey_config: surveyConfig,
        pos_ids: selectedDrones.length > 0 ? selectedDrones : null,
        mission_template: missionTemplate,
        mission_label: missionLabel || null,
        mission_profile: missionProfileId === 'custom' ? 'custom' : missionProfileId,
        mission_brief: missionBrief || null,
        return_behavior: returnBehavior,
      };
      const response = await sarApi.computePlan(request);
      setCoveragePlan(response);
      setMissionId(response.mission_id);
      setLastPlannedSignature(buildQuickScoutPlanningSignature({
        missionTemplate,
        searchArea,
        searchCenter,
        searchRadiusM,
        searchPath,
        corridorWidthM,
        surveyConfig,
        selectedDrones,
        missionProfileId,
        missionLabel,
        missionBrief,
        returnBehavior,
      }));
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
  }, [corridorWidthM, missionBrief, missionLabel, missionProfileId, missionTemplate, refreshMissionCatalog, returnBehavior, searchArea, searchAreaSqM, searchCenter, searchPath, searchRadiusM, selectedDrones, surveyConfig]);

  const handleLaunchMission = useCallback(async () => {
    if (!missionId) return;
    setLaunching(true);
    try {
      const response = await sarApi.launchMission(missionId);
      await refreshMissionCatalog();
      toast.success(response?.message || 'Mission launched');
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
      const response = await sarApi.pauseMission(missionId);
      await refreshMissionCatalog();
      if (response?.success) {
        toast.info(response?.message || 'Mission paused');
      } else {
        toast.warning(response?.message || 'Pause was not accepted by the targeted drones');
      }
    } catch (err) {
      toast.error('Pause failed');
    }
  }, [missionId, refreshMissionCatalog]);

  const handleReplanFromCurrentState = useCallback(() => {
    setMode('plan');
    toast.info('Plan a follow-up QuickScout package from the current mission state.');
  }, []);

  const handleAbort = useCallback(async () => {
    if (!missionId) return;
    try {
      const response = await sarApi.abortMission(missionId);
      await refreshMissionCatalog();
      if (response?.success) {
        toast.warning(response?.message || 'Mission aborted');
      } else {
        toast.error(response?.message || 'Abort was not accepted by the targeted drones');
      }
    } catch (err) {
      toast.error('Abort failed');
    }
  }, [missionId, refreshMissionCatalog]);

  const handleFindingAdded = useCallback((finding) => {
    setFindings((prev) => [...prev, finding]);
    setSelectedFinding(finding);
    setMarkingFinding(false);
  }, []);

  const handleFindingUpdated = useCallback((updatedFinding) => {
    setFindings((prev) => prev.map((finding) => (
      finding.id === updatedFinding.id ? updatedFinding : finding
    )));
    setSelectedFinding(updatedFinding);
  }, []);

  const handleFindingDeleted = useCallback((findingId) => {
    setFindings((prev) => prev.filter((finding) => finding.id !== findingId));
    setSelectedFinding((current) => (current?.id === findingId ? null : current));
  }, []);

  const handleSaveFinding = useCallback(async (findingId, updates) => {
    setSavingFinding(true);
    try {
      const updated = await sarApi.updateFinding(findingId, updates);
      handleFindingUpdated(updated);
      toast.success('Finding updated');
    } catch (error) {
      toast.error('Unable to update finding');
    } finally {
      setSavingFinding(false);
    }
  }, [handleFindingUpdated]);

  const handleDeleteFinding = useCallback(async (findingId) => {
    setDeletingFinding(true);
    try {
      await sarApi.deleteFinding(findingId);
      handleFindingDeleted(findingId);
      toast.success('Finding removed');
    } catch (error) {
      toast.error('Unable to remove finding');
    } finally {
      setDeletingFinding(false);
    }
  }, [handleFindingDeleted]);

  const handleCopyMissionHandoff = useCallback(async () => {
    if (!missionHandoff?.brief_text) {
      return;
    }

    try {
      await navigator.clipboard.writeText(missionHandoff.brief_text);
      toast.success('Mission handoff brief copied');
    } catch (error) {
      toast.error('Unable to copy mission handoff brief');
    }
  }, [missionHandoff]);

  const handleExportMissionHandoff = useCallback(() => {
    if (!missionHandoff) {
      return;
    }

    try {
      const exportBase = missionHandoff.mission_label || missionHandoff.mission_id || 'quickscout-handoff';
      const exportName = exportBase
        .trim()
        .replace(/[^a-z0-9]+/gi, '-')
        .replace(/^-+|-+$/g, '')
        .toLowerCase() || 'quickscout-handoff';
      const blob = new Blob([JSON.stringify(missionHandoff, null, 2)], {
        type: 'application/json',
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${exportName}-handoff.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      toast.success('Mission handoff package exported');
    } catch (error) {
      toast.error('Unable to export mission handoff package');
    }
  }, [missionHandoff]);

  // SearchBar location select handler
  const handleLocationSelect = useCallback((longitude, latitude, _altitude) => {
    const zoom = 15;
    focusMap(longitude, latitude, zoom);
    if (missionTemplate === 'last_known_point') {
      handleSearchCenterChange({ lat: latitude, lng: longitude });
    }
    if (missionTemplate === 'corridor_search') {
      handleSearchPathChange([
        ...searchPath,
        { lat: latitude, lng: longitude },
      ]);
    }
  }, [focusMap, handleSearchCenterChange, handleSearchPathChange, missionTemplate, searchPath]);

  const handleFocusFinding = useCallback((finding) => {
    if (!finding) {
      return;
    }
    setSelectedFinding(finding);
    focusMap(finding.lng, finding.lat, 17);
  }, [focusMap]);

  const handleSeedFollowUpFromFinding = useCallback((finding) => {
    if (!finding) {
      return;
    }

    const preservedTargets = selectedDrones.length > 0
      ? [...selectedDrones]
      : (coveragePlan?.plans || []).map((plan) => plan.pos_id);
    const catalogFallbackMission = missionCatalog.length === 1 ? missionCatalog[0] : null;
    const nextLabelBase = missionLabel
      || currentMissionDisplayName
      || catalogFallbackMission?.mission_label
      || catalogFallbackMission?.mission_id
      || 'QuickScout';
    const nextSummary = finding.summary || 'operator observation';

    setMode('plan');
    setMissionId(null);
    setMissionStatus(null);
    setFindings([]);
    setMarkingFinding(false);
    setSelectedFinding(null);
    setSavingFinding(false);
    setDeletingFinding(false);
    setRecoveringMissionId(null);
    setCoveragePlan(null);
    setLastPlannedSignature(null);

    setMissionTemplate('last_known_point');
    setSearchArea([]);
    setSearchAreaSqM(0);
    setSearchPath([]);
    setCorridorWidthM(DEFAULT_CORRIDOR_WIDTH_M);
    setSearchCenter({ lat: finding.lat, lng: finding.lng });
    setSearchRadiusM(DEFAULT_LAST_KNOWN_POINT_RADIUS_M);
    setMissionLabel(`${nextLabelBase} follow-up`);
    setMissionBrief(`Follow-up search seeded from finding: ${nextSummary}.`);
    setSelectedDrones(preservedTargets);
    drawControlRef.current?.reset();
    focusMap(finding.lng, finding.lat, 17);
    toast.info('Follow-up search seeded from the selected finding');
  }, [coveragePlan?.plans, currentMissionDisplayName, focusMap, missionCatalog, missionLabel, selectedDrones]);

  return (
    <div className="quickscout-page">
      {/* Top Bar */}
      <div className="qs-top-bar">
        <div className="qs-top-bar-left">
          <span className="qs-page-title">
            <FaSearchLocation aria-hidden="true" />
            <span>QuickScout</span>
          </span>
          <PlanMonitorToggle mode={mode} onModeChange={setMode} />
          <DocsLink route="/quickscout" compact className="qs-page-docs" />
          <MapProviderToggle />
          {missionId && (
            <div className="qs-page-chip">
              <span className="qs-page-chip-label">Mission</span>
              <span className="qs-page-chip-value" aria-label={currentMissionDisplayName}>
                {currentMissionDisplayName}
              </span>
              {currentMissionState && (
                <StatusBadge tone={getMissionStateTone(currentMissionState)} className="qs-page-state">
                  {currentMissionState}
                </StatusBadge>
              )}
            </div>
          )}
          <div className="qs-search-wrapper">
            <SearchBar onLocationSelect={handleLocationSelect} />
          </div>
        </div>
        {mode === 'monitor' && missionId && (
          <ActionIconButton
            icon={<FaFlag />}
            label={markingFinding ? 'Cancel finding mark mode' : 'Mark finding on map'}
            onClick={() => setMarkingFinding(!markingFinding)}
            tone={markingFinding ? 'warning' : 'info'}
            size="sm"
            active={markingFinding}
          >
            {markingFinding ? 'Cancel' : 'Finding'}
          </ActionIconButton>
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
                if (markingFinding && findingClickRef.current) {
                  findingClickRef.current(e);
                }
              }}
            >
              {mode === 'plan' && (missionTemplate === 'area_sweep' || missionTemplate === 'corridor_search') && (
                <DrawControl
                  key={`qs-mapbox-draw-${missionTemplate}`}
                  onAreaChange={missionTemplate === 'corridor_search' ? handleSearchPathChange : handleAreaChange}
                  controlRef={drawControlRef}
                  geometryMode={missionTemplate === 'corridor_search' ? 'line' : 'polygon'}
                  initialArea={searchArea}
                  initialPoints={searchPath}
                />
              )}

              {mode === 'plan' && missionTemplate === 'last_known_point' && searchCenter && (
                <>
                  {Source && Layer && pointSearchPreview && (
                    <Source id="qs-point-search-preview" type="geojson" data={pointSearchPreview}>
                      <Layer
                        id="qs-point-search-fill"
                        type="fill"
                        paint={{
                          'fill-color': mapThemeColors.primary,
                          'fill-opacity': 0.08,
                        }}
                      />
                      <Layer
                        id="qs-point-search-outline"
                        type="line"
                        paint={{
                          'line-color': mapThemeColors.primary,
                          'line-width': 2,
                          'line-opacity': 0.75,
                        }}
                      />
                    </Source>
                  )}
                  <Marker
                    latitude={searchCenter.lat}
                    longitude={searchCenter.lng}
                    anchor="center"
                  >
                    <div className="qs-search-center-marker" />
                  </Marker>
                </>
              )}

              {mode === 'plan' && missionTemplate === 'corridor_search' && (
                <>
                  {Source && Layer && corridorSearchPreview && (
                    <Source id="qs-corridor-search-preview" type="geojson" data={corridorSearchPreview}>
                      <Layer
                        id="qs-corridor-fill"
                        type="fill"
                        paint={{
                          'fill-color': mapThemeColors.primary,
                          'fill-opacity': 0.08,
                        }}
                      />
                      <Layer
                        id="qs-corridor-outline"
                        type="line"
                        paint={{
                          'line-color': mapThemeColors.primary,
                          'line-width': 2,
                          'line-opacity': 0.72,
                        }}
                      />
                    </Source>
                  )}
                  {Source && Layer && corridorPathPreview && (
                    <Source id="qs-corridor-path-preview" type="geojson" data={corridorPathPreview}>
                      <Layer
                        id="qs-corridor-path"
                        type="line"
                        paint={{
                          'line-color': mapThemeColors.warning,
                          'line-width': 3,
                          'line-opacity': 0.88,
                        }}
                      />
                    </Source>
                  )}
                </>
              )}

              <CoveragePreview
                plans={coveragePlan?.plans}
                missionStatus={missionStatus}
              />

              <FindingMarkerSystem
                findings={findings}
                missionId={missionId}
                onFindingAdded={handleFindingAdded}
                markingFinding={markingFinding}
                onMapClick={findingClickRef}
                selectedFindingId={selectedFinding?.id || null}
                onFindingSelect={setSelectedFinding}
              />

              {/* Drone position markers (online drones only) */}
              {mergedDrones.filter((d) => d.online && hasDronePosition(d)).map((drone) => (
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
              defaultLayer="esriSatellite"
              style={{ width: '100%', height: '100%' }}
            >
              <LeafletFlyTo target={flyToTarget} />

              {mode === 'plan' && (missionTemplate === 'area_sweep' || missionTemplate === 'corridor_search') && (
                <LeafletDrawControl
                  key={`qs-leaflet-draw-${missionTemplate}`}
                  onAreaChange={missionTemplate === 'corridor_search' ? handleSearchPathChange : handleAreaChange}
                  geometryMode={missionTemplate === 'corridor_search' ? 'line' : 'polygon'}
                  initialPoints={missionTemplate === 'corridor_search' ? searchPath : searchArea}
                />
              )}

              {mode === 'plan' && missionTemplate === 'last_known_point' && searchCenter && (
                <>
                  {Number(searchRadiusM) > 0 && (
                    <LeafletCircle
                      center={[searchCenter.lat, searchCenter.lng]}
                      radius={Number(searchRadiusM)}
                      pathOptions={{
                        color: mapThemeColors.primary,
                        weight: 2,
                        opacity: 0.75,
                        fillColor: mapThemeColors.primary,
                        fillOpacity: 0.08,
                      }}
                    />
                  )}
                  <LeafletMarker
                    position={[searchCenter.lat, searchCenter.lng]}
                    icon={L.divIcon({
                      html: '<div class="qs-search-center-marker"></div>',
                      className: '',
                      iconSize: [20, 20],
                      iconAnchor: [10, 10],
                    })}
                  />
                </>
              )}

              {mode === 'plan' && missionTemplate === 'corridor_search' && corridorSearchPreview?.features?.[0]?.geometry?.coordinates?.[0] && (
                <>
                  <LeafletPolygon
                    positions={corridorSearchPreview.features[0].geometry.coordinates[0].map(([lng, lat]) => [lat, lng])}
                    pathOptions={{
                      color: mapThemeColors.primary,
                      weight: 2,
                      opacity: 0.72,
                      fillColor: mapThemeColors.primary,
                      fillOpacity: 0.08,
                    }}
                  />
                  {corridorPathPreview?.features?.[0]?.geometry?.coordinates && (
                    <LeafletPolyline
                      positions={corridorPathPreview.features[0].geometry.coordinates.map(([lng, lat]) => [lat, lng])}
                      pathOptions={{
                        color: mapThemeColors.warning,
                        weight: 3,
                        opacity: 0.88,
                      }}
                    />
                  )}
                </>
              )}

              <LeafletCoveragePreview
                plans={coveragePlan?.plans}
                missionStatus={missionStatus}
              />

              <LeafletFindingMarkers
                findings={findings}
                missionId={missionId}
                onFindingAdded={handleFindingAdded}
                markingFinding={markingFinding}
                selectedFindingId={selectedFinding?.id || null}
                onFindingSelect={setSelectedFinding}
              />

              {/* Drone position markers (online drones only) */}
              {mergedDrones.filter((d) => d.online && hasDronePosition(d)).map((drone) => (
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
          {!useLeaflet && mode === 'plan' && (missionTemplate === 'area_sweep' || missionTemplate === 'corridor_search') && (
            <MapboxDrawActionBar
              geometryMode={missionTemplate === 'corridor_search' ? 'line' : 'polygon'}
              searchArea={searchArea}
              searchPath={searchPath}
              onReset={handleResetDrawGeometry}
              onTrash={() => drawControlRef.current?.trash()}
            />
          )}

          {/* Action Bar (monitor mode) */}
          {mode === 'monitor' && (
            <MissionActionBar
              missionState={missionStatus?.state}
              controlAvailability={missionStatus?.control_availability}
              returnBehavior={returnBehavior}
              onReplan={handleReplanFromCurrentState}
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
            missionTemplate={missionTemplate}
            onMissionTemplateChange={handleMissionTemplateChange}
            searchCenter={searchCenter}
            onSearchCenterChange={handleSearchCenterChange}
            searchRadiusM={searchRadiusM}
            onSearchRadiusChange={handleSearchRadiusChange}
            onUseMapCenter={handleUseMapCenter}
            searchPath={searchPath}
            onSearchPathChange={handleSearchPathChange}
            corridorWidthM={corridorWidthM}
            onCorridorWidthChange={handleCorridorWidthChange}
            onAppendMapCenterToPath={handleAppendMapCenterToPath}
            onUndoSearchPathPoint={handleUndoSearchPathPoint}
            onClearSearchPath={handleClearSearchPath}
            targetHwIds={activePlanTargetHwIds}
            targetDrones={activePlanTargetDrones}
            targetSummaryLabel={`${activePlanTargetHwIds.length || 0} assigned drone${activePlanTargetHwIds.length === 1 ? '' : 's'}`}
            launchReadiness={launchReadiness}
            planNeedsRecompute={planNeedsRecompute}
            currentMissionState={currentMissionState}
          />
        ) : (
          <MissionMonitorSidebar
            missionStatus={missionStatus}
            findings={findings}
            missionCatalog={missionCatalog}
            currentMissionId={missionId}
            recoveringMissionId={recoveringMissionId}
            loadingMissionCatalog={loadingMissionCatalog}
            onRecoverMission={handleRecoverMission}
            missionLabel={missionLabel}
            missionTemplate={missionTemplate}
            missionBrief={missionBrief}
            totalAreaSqM={coveragePlan?.total_area_sq_m || currentMissionSummary?.total_area_sq_m || searchAreaSqM}
            estimatedCoverageTimeS={coveragePlan?.estimated_coverage_time_s || currentMissionSummary?.estimated_coverage_time_s || 0}
            searchArea={searchArea}
            searchCenter={searchCenter}
            searchRadiusM={searchRadiusM}
            searchPath={searchPath}
            corridorWidthM={corridorWidthM}
            onDroneClick={(hwId) => {
              // Center map on drone
              const drone = mergedDrones.find(d => d.hw_ID === hwId);
              if (hasDronePosition(drone)) {
                focusMap(drone.position_long, drone.position_lat, 16);
              }
            }}
            onFindingClick={handleFocusFinding}
            selectedFinding={selectedFinding}
            onFindingSelect={setSelectedFinding}
            savingFinding={savingFinding}
            deletingFinding={deletingFinding}
            onSaveFinding={handleSaveFinding}
            onDeleteFinding={handleDeleteFinding}
            onFocusFinding={handleFocusFinding}
            onSeedFollowUpFromFinding={handleSeedFollowUpFromFinding}
            missionHandoff={missionHandoff}
            loadingMissionHandoff={loadingMissionHandoff}
            onCopyMissionHandoff={handleCopyMissionHandoff}
            onExportMissionHandoff={handleExportMissionHandoff}
          />
        )}
      </div>
    </div>
  );
};

export default QuickScoutPage;
