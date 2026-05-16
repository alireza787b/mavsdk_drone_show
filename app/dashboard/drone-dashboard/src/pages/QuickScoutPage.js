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
  getOriginResponse,
  unwrapFleetTelemetryPayload,
} from '../services/gcsApiService';
import { extractServerNowMs, normalizeTelemetryResponse } from '../constants/fieldMappings';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';

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
import { MissionJobProgressDialog, MissionReviewLaunchDialog } from '../components/mission-planning';
import {
  buildCorridorGeoJSON,
  buildCorridorPathGeoJSON,
  buildLastKnownPointGeoJSON,
  calculateCorridorAreaSqM,
  calculateCircularAreaSqM,
  normalizeSearchPath,
} from '../utilities/quickScoutSearchGeometry';
import {
  formatQuickScoutArea,
  formatQuickScoutDuration,
  getQuickScoutMissionTemplateLabel,
} from '../utilities/quickScoutMissionPresentation';
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
const QUICKSCOUT_POSITION_SOURCE_MODES = {
  LIVE_DRONE_POSITIONS: 'live_drone_positions',
  CONFIGURED_ORIGIN: 'configured_origin',
};

const ACTIVE_MISSION_STATES = new Set(['executing', 'paused']);
const MONITOR_MISSION_STATES = new Set(['executing', 'paused', 'completed', 'aborted']);
const PLANNING_JOB_TERMINAL_STATES = new Set(['succeeded', 'failed', 'canceled', 'expired']);
const MAX_QUICKSCOUT_PLANNING_POSITION_AGE_MS = 30_000;
const QUICKSCOUT_POSITION_UNAVAILABLE_CODES = new Set([
  'quickscout_position_unavailable',
  'quickscout_planning_position_unavailable',
]);

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

const getReturnBehaviorLabel = (returnBehavior) => {
  if (returnBehavior === 'hold_position') {
    return 'Hold position';
  }
  if (returnBehavior === 'land_current') {
    return 'Land current';
  }
  return 'Return home';
};

const hasFiniteCoordinate = (value) => (
  value !== null && value !== undefined && value !== '' && Number.isFinite(Number(value))
);

const formatApiErrorDetail = (detail) => {
  if (!detail) {
    return '';
  }
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => item?.msg || item?.message || item?.detail || item?.code || String(item))
      .filter(Boolean)
      .join('; ');
  }
  if (typeof detail === 'object') {
    return detail.message || detail.detail || detail.error || detail.code || JSON.stringify(detail);
  }
  return String(detail);
};

const getApiErrorMessage = (error, fallback = 'Request failed') => (
  formatApiErrorDetail(error?.response?.data?.detail)
  || error?.response?.data?.message
  || error?.message
  || fallback
);

const getApiErrorCode = (error) => {
  const detail = error?.response?.data?.detail;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    return detail.code || detail.error_code || '';
  }
  return error?.response?.data?.code || '';
};

const shouldSuggestOriginSlots = (error, message = '') => {
  const code = getApiErrorCode(error);
  return QUICKSCOUT_POSITION_UNAVAILABLE_CODES.has(code)
    || /fresh valid (drone )?global position/i.test(message)
    || /fresh valid drone global positions/i.test(message)
    || /selected drones do not have fresh/i.test(message);
};

const withOriginSlotSuggestion = (message, error, positionSourceMode) => {
  if (positionSourceMode !== QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS) {
    return message;
  }
  if (!shouldSuggestOriginSlots(error, message)) {
    return message;
  }
  return `${message} Use Origin Slots to draft from the configured launch origin while aircraft are offline, then revalidate live GPS before launch.`;
};

const hasDronePosition = (drone) => (
  hasFiniteCoordinate(drone?.position_lat) && hasFiniteCoordinate(drone?.position_long)
  && drone?.global_position_valid !== false
  && (Math.abs(Number(drone.position_lat)) > 0.000001 || Math.abs(Number(drone.position_long)) > 0.000001)
);

const getGlobalPositionAgeMs = (drone) => {
  const ageMs = Number(drone?.global_position_age_ms);
  return Number.isFinite(ageMs) && ageMs >= 0 ? ageMs : null;
};

const hasFreshDronePosition = (drone) => {
  if (!hasDronePosition(drone)) {
    return false;
  }
  const ageMs = getGlobalPositionAgeMs(drone);
  return ageMs === null || ageMs <= MAX_QUICKSCOUT_PLANNING_POSITION_AGE_MS;
};

const buildQuickScoutDroneStatus = (drone, nowMs = Date.now()) => {
  if (!drone) {
    return {
      key: 'offline',
      label: 'Offline',
      className: 'offline',
      title: 'No telemetry row is available.',
      gpsReady: false,
      linkReady: false,
    };
  }

  const runtimeStatus = getDroneRuntimeStatus(drone, nowMs);
  const linkReady = runtimeStatus.level === 'online' || runtimeStatus.level === 'degraded';
  const ageMs = getGlobalPositionAgeMs(drone);
  const hasPosition = hasDronePosition(drone);

  if (!linkReady) {
    return {
      key: runtimeStatus.level === 'unknown' ? 'offline' : runtimeStatus.level,
      label: runtimeStatus.label === 'Never seen' ? 'Offline' : runtimeStatus.label,
      className: 'offline',
      title: runtimeStatus.tooltip || 'No recent telemetry or heartbeat.',
      gpsReady: false,
      linkReady: false,
    };
  }

  if (!hasPosition) {
    return {
      key: 'no-gps',
      label: 'No GPS',
      className: 'no-gps',
      title: 'Connected, but no valid non-default global GPS position is available for Live GPS planning.',
      gpsReady: false,
      linkReady,
    };
  }

  if (ageMs !== null && ageMs > MAX_QUICKSCOUT_PLANNING_POSITION_AGE_MS) {
    return {
      key: 'stale-gps',
      label: 'Stale GPS',
      className: 'stale',
      title: `Global position is ${Math.round(ageMs / 1000)}s old. Live GPS planning requires a fresh position.`,
      gpsReady: false,
      linkReady,
    };
  }

  return {
    key: 'live-gps',
    label: 'Live GPS',
    className: 'online',
    title: runtimeStatus.tooltip || 'Fresh global GPS position is available.',
    gpsReady: true,
    linkReady,
  };
};

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
  const [positionSourceMode, setPositionSourceMode] = useState(QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS);
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [coveragePlan, setCoveragePlan] = useState(null);
  const [computing, setComputing] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [loadingMissionCatalog, setLoadingMissionCatalog] = useState(false);
  const [missionCatalog, setMissionCatalog] = useState([]);
  const [recoveringMissionId, setRecoveringMissionId] = useState(null);
  const [originStatus, setOriginStatus] = useState({ state: 'checking', message: 'Checking origin' });
  const [lastPlannedSignature, setLastPlannedSignature] = useState(null);
  const [planningJob, setPlanningJob] = useState(null);
  const [planningJobDialogOpen, setPlanningJobDialogOpen] = useState(false);
  const [launchReviewOpen, setLaunchReviewOpen] = useState(false);

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
  const planningJobPollRef = useRef(null);
  const planningJobRequestRef = useRef(null);
  const [flyToTarget, setFlyToTarget] = useState(null);
  const autoRecoveryCheckedRef = useRef(false);

  const clearPlanningJobPoll = useCallback(() => {
    if (planningJobPollRef.current) {
      clearInterval(planningJobPollRef.current);
      planningJobPollRef.current = null;
    }
  }, []);

  const focusMap = useCallback((longitude, latitude, zoom = 15) => {
    const nextViewport = { longitude, latitude, zoom };
    setViewport(nextViewport);
    const mapboxMap = mapRef.current?.getMap?.() || mapRef.current;
    if (!useLeaflet && mapboxMap?.flyTo) {
      mapboxMap.flyTo({ center: [longitude, latitude], zoom });
      return;
    }
    setFlyToTarget({ latitude, longitude, zoom });
  }, [useLeaflet]);

  const handleMapboxMove = useCallback((event) => {
    const nextViewState = event?.viewState || {};
    if (
      Number.isFinite(Number(nextViewState.latitude))
      && Number.isFinite(Number(nextViewState.longitude))
    ) {
      setViewport({
        latitude: Number(nextViewState.latitude),
        longitude: Number(nextViewState.longitude),
        zoom: Number.isFinite(Number(nextViewState.zoom)) ? Number(nextViewState.zoom) : viewport.zoom,
      });
    }
  }, [viewport.zoom]);

  const handleLeafletMoveEnd = useCallback((event) => {
    const map = event?.target;
    const center = map?.getCenter?.();
    if (!center) {
      return;
    }
    setViewport({
      latitude: Number(center.lat),
      longitude: Number(center.lng),
      zoom: Number.isFinite(Number(map?.getZoom?.())) ? Number(map.getZoom()) : viewport.zoom,
    });
  }, [viewport.zoom]);

  const getCurrentMapCenter = useCallback(() => {
    if (!useLeaflet) {
      const mapboxMap = mapRef.current?.getMap?.() || mapRef.current;
      const center = mapboxMap?.getCenter?.();
      if (
        center
        && Number.isFinite(Number(center.lat))
        && Number.isFinite(Number(center.lng))
      ) {
        return {
          lat: Number(center.lat),
          lng: Number(center.lng),
        };
      }
    }

    if (Number.isFinite(Number(viewport.latitude)) && Number.isFinite(Number(viewport.longitude))) {
      return {
        lat: Number(viewport.latitude),
        lng: Number(viewport.longitude),
      };
    }
    return null;
  }, [useLeaflet, viewport.latitude, viewport.longitude]);

  const resetWorkspace = useCallback(() => {
    clearPlanningJobPoll();
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
    setPositionSourceMode(QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS);
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
    setComputing(false);
    setPlanningJob(null);
    setPlanningJobDialogOpen(false);
    setLaunchReviewOpen(false);
    planningJobRequestRef.current = null;
    drawControlRef.current?.reset();
  }, [clearPlanningJobPoll]);

  useEffect(() => () => clearPlanningJobPoll(), [clearPlanningJobPoll]);

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
    setPositionSourceMode(operation.position_source_mode || QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS);
    setSelectedDrones(recoveredSelectedDrones);
    setCoveragePlan({
      mission_id: operation.mission_id,
      plans: operation.plans || [],
      total_area_sq_m: operation.total_area_sq_m || 0,
      estimated_coverage_time_s: operation.estimated_coverage_time_s || 0,
      algorithm_used: operation.algorithm_used || DEFAULT_SURVEY_CONFIG.algorithm,
      warnings: operation.planning_warnings || [],
      position_source_mode: operation.position_source_mode || QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS,
      position_sources: operation.position_sources || [],
      planning_origin: operation.planning_origin || null,
      launchable: operation.launchable ?? true,
      requires_revalidation: operation.requires_revalidation ?? false,
      terrain_summary: operation.terrain_summary || null,
    });
    setLastPlannedSignature(buildQuickScoutPlanningSignature({
      missionTemplate: operation.mission_template || 'area_sweep',
      positionSourceMode: operation.position_source_mode || QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS,
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
        const telemetry = normalizeTelemetryResponse(
          unwrapFleetTelemetryPayload(response.data),
          {
            receivedAtMs: Date.now(),
            serverNowMs: extractServerNowMs(response.headers || {}),
          }
        );
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

  // Configured origin polling for staged/offline planning guidance
  useEffect(() => {
    let active = true;

    const fetchOriginStatus = async () => {
      try {
        const response = await getOriginResponse();
        const origin = response?.data || {};
        const lat = Number(origin.lat);
        const lon = Number(origin.lon);
        const originReady = Number.isFinite(lat)
          && Number.isFinite(lon)
          && (Math.abs(lat) > 0.000001 || Math.abs(lon) > 0.000001);

        if (!active) {
          return;
        }

        setOriginStatus(originReady
          ? {
            state: 'ready',
            message: `Origin ${lat.toFixed(5)}, ${lon.toFixed(5)}`,
          }
          : {
            state: 'missing',
            message: 'Set an origin before using Origin Slots.',
          });
      } catch (error) {
        if (!active) {
          return;
        }
        setOriginStatus({
          state: 'unavailable',
          message: 'Origin status unavailable.',
        });
      }
    };

    fetchOriginStatus();
    const interval = setInterval(fetchOriginStatus, 10000);
    return () => {
      active = false;
      clearInterval(interval);
    };
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
      const quickScoutStatus = buildQuickScoutDroneStatus(telemetry || null);
      return {
        hw_ID: hwId,
        hw_id: hwId,
        pos_id: cfg.pos_id,
        pos_ID: cfg.pos_id,
        ip: cfg.ip,
        ...(telemetry || {}),
        online: quickScoutStatus.gpsReady,
        linkReady: quickScoutStatus.linkReady,
        gpsReady: quickScoutStatus.gpsReady,
        quickScoutStatus,
      };
    });
    // Add any telemetry drones not in config
    for (const d of drones) {
      const inConfig = configDrones.some((c) => String(c.hw_id) === String(d.hw_ID));
      if (!inConfig) {
        const quickScoutStatus = buildQuickScoutDroneStatus(d);
        merged.push({
          ...d,
          online: quickScoutStatus.gpsReady,
          linkReady: quickScoutStatus.linkReady,
          gpsReady: quickScoutStatus.gpsReady,
          quickScoutStatus,
        });
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
      positionSourceMode,
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
    [corridorWidthM, missionBrief, missionLabel, missionProfileId, missionTemplate, positionSourceMode, returnBehavior, searchArea, searchCenter, searchPath, searchRadiusM, selectedDrones, surveyConfig],
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
  const launchReviewMission = useMemo(() => ({
    Mission: missionLabel || 'Untitled QuickScout',
    Template: getQuickScoutMissionTemplateLabel(missionTemplate),
    Aircraft: `${activePlanTargetHwIds.length || 0} assigned`,
    Area: formatQuickScoutArea(coveragePlan?.total_area_sq_m),
    Duration: formatQuickScoutDuration(coveragePlan?.estimated_coverage_time_s),
    Altitude: surveyConfig.use_terrain_following
      ? `${surveyConfig.survey_altitude_agl} m AGL terrain`
      : `${surveyConfig.cruise_altitude_msl} m MSL fixed`,
    Planning: coveragePlan?.position_source_mode === QUICKSCOUT_POSITION_SOURCE_MODES.CONFIGURED_ORIGIN
      ? 'Configured origin'
      : 'Live GPS',
    End: getReturnBehaviorLabel(returnBehavior),
  }), [
    activePlanTargetHwIds.length,
    coveragePlan?.estimated_coverage_time_s,
    coveragePlan?.position_source_mode,
    coveragePlan?.total_area_sq_m,
    missionLabel,
    missionTemplate,
    returnBehavior,
    surveyConfig.cruise_altitude_msl,
    surveyConfig.survey_altitude_agl,
    surveyConfig.use_terrain_following,
  ]);
  const launchReviewBlockers = useMemo(() => [
    ...(planNeedsRecompute ? ['Mission inputs changed after compute; recompute before launch.'] : []),
    ...((launchReadiness?.blockers || []).map((issue) => (
      `${issue.label || 'Launch blocker'}${issue.detail ? `: ${issue.detail}` : ''}`
    ))),
  ], [launchReadiness?.blockers, planNeedsRecompute]);
  const launchReviewWarnings = useMemo(() => [
    ...(coveragePlan?.requires_revalidation
      ? ['Configured-origin package: live GPS revalidation runs immediately before launch.']
      : []),
    ...((launchReadiness?.warnings || []).map((issue) => (
      `${issue.label || 'Advisory'}${issue.detail ? `: ${issue.detail}` : ''}`
    ))),
    ...((coveragePlan?.warnings || []).map((warning) => warning.message || warning.code).filter(Boolean)),
    ...(coveragePlan?.terrain_summary?.status && coveragePlan.terrain_summary.status !== 'ok'
      ? [coveragePlan.terrain_summary.message || `Terrain status: ${coveragePlan.terrain_summary.status}`]
      : []),
  ], [coveragePlan?.requires_revalidation, coveragePlan?.terrain_summary, coveragePlan?.warnings, launchReadiness?.warnings]);
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

  const handlePositionSourceModeChange = useCallback((nextMode) => {
    setPositionSourceMode(nextMode || QUICKSCOUT_POSITION_SOURCE_MODES.LIVE_DRONE_POSITIONS);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, []);

  const handleMissionTemplateChange = useCallback((templateId) => {
    setMissionTemplate(templateId);
    setCoveragePlan(null);
    setLastPlannedSignature(null);
    if ((templateId === 'last_known_point' || templateId === 'point_dispatch') && !searchCenter) {
      const onlineDrone = mergedDrones.find((drone) => drone.gpsReady && hasFreshDronePosition(drone));
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
    const mapCenter = getCurrentMapCenter();
    if (!mapCenter) {
      return;
    }

    setSearchCenter({
      lat: mapCenter.lat,
      lng: mapCenter.lng,
    });
    setCoveragePlan(null);
    setLastPlannedSignature(null);
  }, [getCurrentMapCenter]);

  const handlePlanMapPointClick = useCallback((latitude, longitude) => {
    if (mode !== 'plan' || markingFinding) {
      return;
    }
    if (missionTemplate !== 'last_known_point' && missionTemplate !== 'point_dispatch') {
      return;
    }
    if (!Number.isFinite(Number(latitude)) || !Number.isFinite(Number(longitude))) {
      return;
    }

    handleSearchCenterChange({
      lat: Number(latitude),
      lng: Number(longitude),
    });
    toast.info(missionTemplate === 'point_dispatch'
      ? 'Dispatch point set from map'
      : 'Last-known point set from map');
  }, [handleSearchCenterChange, markingFinding, missionTemplate, mode]);

  const handleAppendMapCenterToPath = useCallback(() => {
    const mapCenter = getCurrentMapCenter();
    if (!mapCenter) {
      return;
    }

    handleSearchPathChange([
      ...searchPath,
      {
        lat: mapCenter.lat,
        lng: mapCenter.lng,
      },
    ]);
  }, [getCurrentMapCenter, handleSearchPathChange, searchPath]);

  const handleUndoSearchPathPoint = useCallback(() => {
    handleSearchPathChange(searchPath.slice(0, -1));
  }, [handleSearchPathChange, searchPath]);

  const handleClearSearchPath = useCallback(() => {
    handleSearchPathChange([]);
  }, [handleSearchPathChange]);

  const buildMissionPlanRequest = useCallback(() => {
    const requestSearchArea = missionTemplate === 'point_dispatch'
      ? {
        type: 'point',
        center: searchCenter,
        area_sq_m: 0,
      }
      : missionTemplate === 'last_known_point'
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
      position_source_mode: positionSourceMode,
      mission_template: missionTemplate,
      mission_label: missionLabel || null,
      mission_profile: missionProfileId === 'custom' ? 'custom' : missionProfileId,
      mission_brief: missionBrief || null,
      return_behavior: returnBehavior,
    };

    const signature = buildQuickScoutPlanningSignature({
      missionTemplate,
      positionSourceMode,
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
    });

    return { request, signature };
  }, [corridorWidthM, missionBrief, missionLabel, missionProfileId, missionTemplate, positionSourceMode, returnBehavior, searchArea, searchAreaSqM, searchCenter, searchPath, searchRadiusM, selectedDrones, surveyConfig]);

  const applyPlanningJobResult = useCallback(async (job, signature) => {
    const response = job?.result;
    if (!response) {
      throw new Error('Planning job completed without a coverage plan.');
    }

    setCoveragePlan(response);
    setMissionId(response.mission_id);
    setLastPlannedSignature(signature);
    await refreshMissionCatalog();
    toast.success(`Plan computed: ${response.plans.length} drones, ${(response.total_area_sq_m / 10000).toFixed(1)} ha`);
  }, [refreshMissionCatalog]);

  const startPlanningJob = useCallback(async (request, signature) => {
    clearPlanningJobPoll();
    planningJobRequestRef.current = { request, signature };
    setComputing(true);
    setPlanningJobDialogOpen(true);
    setPlanningJob({
      status: 'queued',
      phase: 'submitting',
      progress_percent: 0,
      message: 'Submitting QuickScout planning job.',
      warnings: [],
    });

    const finishWithJob = async (job) => {
      clearPlanningJobPoll();
      setComputing(false);

      if (job.status === 'succeeded') {
        try {
          await applyPlanningJobResult(job, signature);
        } catch (error) {
          const message = withOriginSlotSuggestion(error.message, error, request.position_source_mode);
          setPlanningJob((current) => ({
            ...(current || job),
            status: 'failed',
            phase: 'finalizing',
            error_message: message,
          }));
          toast.error(`Planning failed: ${message}`);
        }
        return;
      }

      if (job.status === 'canceled') {
        toast.warning(job.message || 'Planning canceled');
        return;
      }

      const message = withOriginSlotSuggestion(
        job.error_message || job.message || 'Planning job failed',
        null,
        request.position_source_mode
      );
      toast.error(`Planning failed: ${message}`);
    };

    try {
      const createdJob = await sarApi.createPlanningJob(request);
      setPlanningJob(createdJob);

      if (PLANNING_JOB_TERMINAL_STATES.has(createdJob.status)) {
        await finishWithJob(createdJob);
        return;
      }

      const pollJob = async () => {
        try {
          const currentJob = await sarApi.getPlanningJob(createdJob.job_id);
          setPlanningJob(currentJob);
          if (PLANNING_JOB_TERMINAL_STATES.has(currentJob.status)) {
            await finishWithJob(currentJob);
          }
        } catch (error) {
          clearPlanningJobPoll();
          setComputing(false);
          const message = withOriginSlotSuggestion(
            getApiErrorMessage(error, 'Unable to read planning job status'),
            error,
            request.position_source_mode
          );
          setPlanningJob((current) => ({
            ...(current || createdJob),
            status: 'failed',
            phase: 'status_unavailable',
            error_message: message,
          }));
          toast.error(`Planning failed: ${message}`);
        }
      };

      planningJobPollRef.current = setInterval(pollJob, 900);
      pollJob();
    } catch (error) {
      clearPlanningJobPoll();
      setComputing(false);
      const message = withOriginSlotSuggestion(
        getApiErrorMessage(error, 'Unable to start planning job'),
        error,
        request.position_source_mode
      );
      setPlanningJob((current) => ({
        ...(current || {}),
        status: 'failed',
        phase: 'submit_failed',
        progress_percent: 0,
        error_message: message,
      }));
      toast.error(`Planning failed: ${message}`);
    }
  }, [applyPlanningJobResult, clearPlanningJobPoll]);

  const handleComputePlan = useCallback(async () => {
    const { request, signature } = buildMissionPlanRequest();
    await startPlanningJob(request, signature);
  }, [buildMissionPlanRequest, startPlanningJob]);

  const handleCancelPlanningJob = useCallback(async () => {
    const jobId = planningJob?.job_id;
    if (!jobId) {
      clearPlanningJobPoll();
      setComputing(false);
      setPlanningJobDialogOpen(false);
      return;
    }

    try {
      const canceledJob = await sarApi.cancelPlanningJob(jobId);
      clearPlanningJobPoll();
      setPlanningJob(canceledJob);
      setComputing(false);
      toast.warning(canceledJob.message || 'Planning canceled');
    } catch (error) {
      const message = getApiErrorMessage(error, 'Unable to cancel planning job');
      toast.error(`Cancel failed: ${message}`);
    }
  }, [clearPlanningJobPoll, planningJob?.job_id]);

  const handleRetryPlanningJob = useCallback(async () => {
    const retry = planningJobRequestRef.current || buildMissionPlanRequest();
    await startPlanningJob(retry.request, retry.signature);
  }, [buildMissionPlanRequest, startPlanningJob]);

  const planningJobDialogData = useMemo(() => ({
    status: planningJob?.status || (computing ? 'running' : 'queued'),
    progressPercent: planningJob?.progress_percent ?? 0,
    phase: planningJob?.phase,
    message: planningJob?.message,
    error: planningJob?.error_message,
    warnings: (planningJob?.warnings || [])
      .map((warning) => warning?.message || warning?.code || String(warning))
      .filter(Boolean),
  }), [computing, planningJob]);

  const handleOpenLaunchReview = useCallback(() => {
    if (!coveragePlan || planNeedsRecompute || !(launchReadiness?.canLaunch ?? true)) {
      return;
    }
    setLaunchReviewOpen(true);
  }, [coveragePlan, launchReadiness?.canLaunch, planNeedsRecompute]);

  const handleConfirmLaunchMission = useCallback(async () => {
    if (!missionId) return;
    setLaunching(true);
    try {
      let revalidationToken = null;
      if (coveragePlan?.requires_revalidation) {
        const revalidation = await sarApi.revalidateLaunch(missionId);
        if (!revalidation?.launchable) {
          const blockerText = (revalidation?.blockers || [])
            .map((blocker) => blocker?.message || blocker?.code)
            .filter(Boolean)
            .join('; ');
          throw new Error(blockerText || revalidation?.message || 'Live revalidation failed');
        }
        revalidationToken = revalidation?.token || null;
      }
      const response = revalidationToken
        ? await sarApi.launchMission(missionId, { revalidationToken })
        : await sarApi.launchMission(missionId);
      await refreshMissionCatalog();
      toast.success(response?.message || 'Mission launched');
      setLaunchReviewOpen(false);
      setMode('monitor');
    } catch (err) {
      const detail = getApiErrorMessage(err, 'Launch request failed');
      toast.error(`Launch failed: ${detail}`);
    } finally {
      setLaunching(false);
    }
  }, [coveragePlan?.requires_revalidation, missionId, refreshMissionCatalog]);

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
      const response = await sarApi.abortMission(missionId, null, returnBehavior);
      await refreshMissionCatalog();
      if (response?.success) {
        toast.warning(response?.message || 'Mission aborted');
      } else {
        toast.error(response?.message || 'Abort was not accepted by the targeted drones');
      }
    } catch (err) {
      toast.error('Abort failed');
    }
  }, [missionId, refreshMissionCatalog, returnBehavior]);

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
    if (missionTemplate === 'last_known_point' || missionTemplate === 'point_dispatch') {
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
              onMove={handleMapboxMove}
              onClick={(e) => {
                if (markingFinding && findingClickRef.current) {
                  findingClickRef.current(e);
                  return;
                }
                handlePlanMapPointClick(e?.lngLat?.lat, e?.lngLat?.lng);
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

              {mode === 'plan' && (missionTemplate === 'last_known_point' || missionTemplate === 'point_dispatch') && searchCenter && (
                <>
                  {missionTemplate === 'last_known_point' && Source && Layer && pointSearchPreview && (
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

              {/* Drone position markers (fresh live-GPS drones only) */}
              {mergedDrones.filter((d) => d.gpsReady && hasFreshDronePosition(d)).map((drone) => (
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
              eventHandlers={{
                moveend: handleLeafletMoveEnd,
                zoomend: handleLeafletMoveEnd,
              }}
              onClick={(event) => {
                handlePlanMapPointClick(event?.latlng?.lat, event?.latlng?.lng);
              }}
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

              {mode === 'plan' && (missionTemplate === 'last_known_point' || missionTemplate === 'point_dispatch') && searchCenter && (
                <>
                  {missionTemplate === 'last_known_point' && Number(searchRadiusM) > 0 && (
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

              {/* Drone position markers (fresh live-GPS drones only) */}
              {mergedDrones.filter((d) => d.gpsReady && hasFreshDronePosition(d)).map((drone) => (
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
            onLaunchMission={handleOpenLaunchReview}
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
            positionSourceMode={positionSourceMode}
            onPositionSourceModeChange={handlePositionSourceModeChange}
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
            originStatus={originStatus}
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
      <MissionJobProgressDialog
        open={planningJobDialogOpen}
        title="Compute QuickScout Plan"
        job={planningJobDialogData}
        onCancel={handleCancelPlanningJob}
        onRetry={handleRetryPlanningJob}
        onClose={() => setPlanningJobDialogOpen(false)}
      />
      <MissionReviewLaunchDialog
        open={launchReviewOpen}
        title="Review QuickScout Launch"
        confirmLabel="Launch Mission"
        mission={launchReviewMission}
        blockers={launchReviewBlockers}
        warnings={launchReviewWarnings}
        busy={launching}
        onConfirm={handleConfirmLaunchMission}
        onCancel={() => setLaunchReviewOpen(false)}
      />
    </div>
  );
};

export default QuickScoutPage;
