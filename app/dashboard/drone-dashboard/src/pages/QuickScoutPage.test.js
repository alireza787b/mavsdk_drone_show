import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import QuickScoutPage from './QuickScoutPage';
import * as sarApi from '../services/sarApiService';
import {
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
} from '../services/gcsApiService';

jest.mock('react-toastify', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
  },
}));

jest.mock('leaflet', () => ({
  divIcon: jest.fn(() => ({})),
}));

jest.mock('react-leaflet', () => ({
  Marker: ({ children }) => <div data-testid="leaflet-marker">{children}</div>,
  useMap: () => ({ flyTo: jest.fn() }),
}));

jest.mock('../services/sarApiService', () => ({
  computePlan: jest.fn(),
  listMissions: jest.fn(),
  launchMission: jest.fn(),
  getMissionWorkspace: jest.fn(),
  getMissionStatus: jest.fn(),
  pauseMission: jest.fn(),
  resumeMission: jest.fn(),
  abortMission: jest.fn(),
  createPOI: jest.fn(),
  getPOIs: jest.fn(),
  updatePOI: jest.fn(),
  deletePOI: jest.fn(),
  batchElevation: jest.fn(),
}));

jest.mock('../services/gcsApiService', () => ({
  getFleetConfigResponse: jest.fn(),
  getFleetTelemetryResponse: jest.fn(),
  unwrapFleetTelemetryPayload: jest.fn(),
}));

jest.mock('../contexts/MapContext', () => ({
  useMapContext: () => ({
    provider: 'leaflet',
    isMapboxAvailable: false,
    mapboxToken: '',
  }),
}));

jest.mock('../components/sar/PlanMonitorToggle', () => ({ mode, onModeChange }) => (
  <div>
    <button type="button" onClick={() => onModeChange('plan')}>Plan</button>
    <button type="button" onClick={() => onModeChange('monitor')}>Monitor</button>
    <span data-testid="mode-toggle">{mode}</span>
  </div>
));

jest.mock('../components/sar/MissionStatsBar', () => ({ missionStatus }) => (
  <div data-testid="mission-stats">{missionStatus?.mission_id || 'none'}</div>
));

jest.mock('../components/sar/MissionPlanSidebar', () => (props) => (
  <div data-testid="plan-sidebar">
    <div data-testid="plan-current">{props.currentMissionId || ''}</div>
    <div data-testid="plan-catalog">{props.missionCatalog.length}</div>
    <div data-testid="plan-loading">{String(props.loadingMissionCatalog)}</div>
    <button
      type="button"
      onClick={() => props.onRecoverMission(props.missionCatalog[0]?.mission_id)}
      disabled={!props.missionCatalog.length}
    >
      Recover first mission
    </button>
    <button type="button" onClick={props.onStartFreshPlan}>New Search</button>
  </div>
));

jest.mock('../components/sar/MissionMonitorSidebar', () => (props) => (
  <div data-testid="monitor-sidebar">
    <div data-testid="monitor-current">{props.currentMissionId || ''}</div>
    <div data-testid="monitor-catalog">{props.missionCatalog.length}</div>
  </div>
));

jest.mock('../components/sar/MissionActionBar', () => () => <div data-testid="mission-action-bar" />);
jest.mock('../components/sar/CoveragePreview', () => () => <div data-testid="coverage-preview" />);
jest.mock('../components/sar/POIMarkerSystem', () => () => <div data-testid="poi-marker-system" />);
jest.mock('../components/sar/SearchAreaDrawer', () => {
  const DrawControl = () => <div data-testid="draw-control" />;
  const MapboxSetupInstructions = () => <div data-testid="mapbox-setup" />;
  const MapboxDrawActionBar = () => <div data-testid="mapbox-action-bar" />;
  return {
    __esModule: true,
    default: DrawControl,
    MapboxSetupInstructions,
    MapboxDrawActionBar,
  };
});
jest.mock('../components/trajectory/SearchBar', () => () => <div data-testid="search-bar" />);
jest.mock('../components/map/LeafletMapBase', () => ({ children }) => <div data-testid="leaflet-map">{children}</div>);
jest.mock('../components/map/LeafletDrawControl', () => () => <div data-testid="leaflet-draw" />);
jest.mock('../components/map/LeafletCoveragePreview', () => () => <div data-testid="leaflet-coverage" />);
jest.mock('../components/map/LeafletPOIMarkers', () => () => <div data-testid="leaflet-poi" />);
jest.mock('../components/map/MapFallbackBanner', () => () => <div data-testid="map-fallback" />);
jest.mock('../components/map/MapProviderToggle', () => () => <div data-testid="map-provider-toggle" />);

const buildMissionSummary = (overrides = {}) => ({
  mission_id: 'mission-ready',
  state: 'ready',
  created_at: 1_700_000_000,
  updated_at: 1_700_000_100,
  started_at: null,
  drone_count: 1,
  pos_ids: [1],
  total_area_sq_m: 1200,
  estimated_coverage_time_s: 180,
  algorithm_used: 'boustrophedon',
  return_behavior: 'return_home',
  total_coverage_percent: 0,
  poi_count: 0,
  last_command_summary: null,
  ...overrides,
});

const buildWorkspace = (overrides = {}) => {
  const missionId = overrides.mission_id || 'mission-ready';
  const state = overrides.state || 'ready';

  return {
    operation: {
      mission_id: missionId,
      state,
      search_area: {
        type: 'polygon',
        points: [
          { lat: 37.0, lng: -122.0 },
          { lat: 37.001, lng: -122.0 },
          { lat: 37.001, lng: -122.001 },
        ],
        area_sq_m: 1200,
      },
      survey_config: {
        algorithm: 'boustrophedon',
        sweep_width_m: 30,
        overlap_percent: 10,
        cruise_altitude_msl: 50,
        survey_altitude_agl: 40,
        cruise_speed_ms: 10,
        survey_speed_ms: 5,
        use_terrain_following: true,
        camera_interval_s: 2,
      },
      pos_ids: [1],
      plans: [
        {
          hw_id: '1',
          pos_id: 1,
          assigned_area_sq_m: 1200,
          estimated_duration_s: 180,
          total_distance_m: 500,
          waypoints: [{ lat: 37.0, lng: -122.0, alt_msl: 50, speed_ms: 5, sequence: 0 }],
        },
      ],
      total_area_sq_m: 1200,
      estimated_coverage_time_s: 180,
      algorithm_used: 'boustrophedon',
      created_at: 1_700_000_000,
      updated_at: 1_700_000_100,
    },
    status: {
      mission_id: missionId,
      state,
      drone_states: {},
      pois: [],
      total_coverage_percent: state === 'executing' ? 22 : 0,
      elapsed_time_s: state === 'executing' ? 45 : 0,
      started_at: state === 'executing' ? 1_700_000_110 : null,
    },
  };
};

describe('QuickScoutPage', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.spyOn(console, 'warn').mockImplementation(() => {});

    getFleetTelemetryResponse.mockResolvedValue({ data: {} });
    unwrapFleetTelemetryPayload.mockReturnValue({});
    getFleetConfigResponse.mockResolvedValue({ data: [] });
    sarApi.getMissionStatus.mockResolvedValue({
      mission_id: 'mission-exec',
      state: 'executing',
      drone_states: {},
      pois: [],
      total_coverage_percent: 22,
      elapsed_time_s: 45,
      started_at: 1_700_000_110,
    });
    sarApi.getPOIs.mockResolvedValue([]);
  });

  afterEach(() => {
    jest.clearAllTimers();
    jest.useRealTimers();
    jest.restoreAllMocks();
    jest.clearAllMocks();
  });

  it('reopens a saved ready mission from the mission catalog', async () => {
    sarApi.listMissions.mockResolvedValue({
      missions: [buildMissionSummary()],
      count: 1,
    });
    sarApi.getMissionWorkspace.mockResolvedValue(buildWorkspace());

    render(<QuickScoutPage />);

    await waitFor(() => expect(screen.getByTestId('plan-catalog')).toHaveTextContent('1'));
    fireEvent.click(screen.getByRole('button', { name: 'Recover first mission' }));

    await waitFor(() => {
      expect(sarApi.getMissionWorkspace).toHaveBeenCalledWith('mission-ready');
      expect(screen.getByTestId('plan-current')).toHaveTextContent('mission-ready');
    });
  });

  it('auto-recovers an active mission into monitor mode after refresh', async () => {
    sarApi.listMissions.mockResolvedValue({
      missions: [buildMissionSummary({ mission_id: 'mission-exec', state: 'executing' })],
      count: 1,
    });
    sarApi.getMissionWorkspace.mockResolvedValue(buildWorkspace({
      mission_id: 'mission-exec',
      state: 'executing',
    }));

    render(<QuickScoutPage />);

    await waitFor(() => {
      expect(sarApi.getMissionWorkspace).toHaveBeenCalledWith('mission-exec');
      expect(screen.getByTestId('monitor-sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('monitor-current')).toHaveTextContent('mission-exec');
    });
  });
});
