import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  Circle: () => <div data-testid="leaflet-circle" />,
  Marker: ({ children }) => <div data-testid="leaflet-marker">{children}</div>,
  Polygon: () => <div data-testid="leaflet-polygon" />,
  Polyline: () => <div data-testid="leaflet-polyline" />,
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
    <div data-testid="plan-template">{props.missionTemplate}</div>
    <div data-testid="plan-return-behavior">{props.returnBehavior}</div>
    <div data-testid="plan-label">{props.missionLabel}</div>
    <div data-testid="plan-brief">{props.missionBrief}</div>
    <div data-testid="plan-needs-recompute">{String(props.planNeedsRecompute)}</div>
    <div data-testid="plan-launch-ready">{String(props.launchReadiness?.canLaunch ?? false)}</div>
    <div data-testid="plan-target-count">{props.targetHwIds?.length || 0}</div>
    <button
      type="button"
      onClick={() => props.onRecoverMission(props.missionCatalog[0]?.mission_id)}
      disabled={!props.missionCatalog.length}
    >
      Recover first mission
    </button>
    <button type="button" onClick={() => props.onMissionProfileChange('detailed_sweep')}>
      Use detailed profile
    </button>
    <button type="button" onClick={() => props.onMissionTemplateChange('last_known_point')}>
      Use last known point
    </button>
    <button type="button" onClick={() => props.onMissionTemplateChange('corridor_search')}>
      Use corridor search
    </button>
    <button
      type="button"
      onClick={() => props.onSearchCenterChange({ lat: 37.25, lng: -122.15 })}
    >
      Set search center
    </button>
    <button type="button" onClick={() => props.onSearchRadiusChange(180)}>
      Set search radius
    </button>
    <button
      type="button"
      onClick={() => props.onSearchPathChange([
        { lat: 37.25, lng: -122.15 },
        { lat: 37.255, lng: -122.145 },
        { lat: 37.26, lng: -122.14 },
      ])}
    >
      Set corridor path
    </button>
    <button type="button" onClick={() => props.onCorridorWidthChange(110)}>
      Set corridor width
    </button>
    <button type="button" onClick={() => props.onReturnBehaviorChange('hold_position')}>
      Set hold return
    </button>
    <button type="button" onClick={() => props.onMissionLabelChange('Harbor sweep')}>
      Set mission label
    </button>
    <button type="button" onClick={() => props.onMissionLabelChange('Updated label')}>
      Change mission label
    </button>
    <button type="button" onClick={() => props.onMissionBriefChange('Search quay perimeter')}>
      Set mission brief
    </button>
    <button type="button" onClick={() => props.onDroneToggle(1)}>
      Select drone 1
    </button>
    <button type="button" onClick={props.onComputePlan}>
      Compute plan
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
  mission_label: 'Recovered mission',
  mission_profile: 'rapid_search',
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
      mission_label: 'Recovered mission',
      mission_profile: 'rapid_search',
      mission_brief: 'Recovered operator brief',
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

const renderPage = async () => {
  await act(async () => {
    render(<QuickScoutPage />);
  });
};

const flushAsyncState = async () => {
  await act(async () => {
    await Promise.resolve();
  });
};

describe('QuickScoutPage', () => {
  let realConsoleError;

  beforeEach(() => {
    jest.useFakeTimers();
    jest.spyOn(console, 'warn').mockImplementation(() => {});
    realConsoleError = console.error;
    jest.spyOn(console, 'error').mockImplementation((...args) => {
      if (typeof args[0] === 'string' && args[0].includes('not wrapped in act')) {
        return;
      }
      realConsoleError(...args);
    });

    getFleetTelemetryResponse.mockResolvedValue({ data: {} });
    unwrapFleetTelemetryPayload.mockReturnValue({});
    getFleetConfigResponse.mockResolvedValue({ data: [] });
    sarApi.computePlan.mockResolvedValue({
      mission_id: 'mission-ready',
      plans: [],
      total_area_sq_m: 1200,
      estimated_coverage_time_s: 180,
      algorithm_used: 'boustrophedon',
    });
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

    await renderPage();
    await flushAsyncState();

    await waitFor(() => expect(screen.getByTestId('plan-catalog')).toHaveTextContent('1'));
    fireEvent.click(screen.getByRole('button', { name: 'Recover first mission' }));

    await waitFor(() => {
      expect(sarApi.getMissionWorkspace).toHaveBeenCalledWith('mission-ready');
      expect(screen.getByTestId('plan-current')).toHaveTextContent('mission-ready');
      expect(screen.getByTestId('plan-label')).toHaveTextContent('Recovered mission');
      expect(screen.getByTestId('plan-brief')).toHaveTextContent('Recovered operator brief');
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

    await renderPage();
    await flushAsyncState();

    await waitFor(() => {
      expect(sarApi.getMissionWorkspace).toHaveBeenCalledWith('mission-exec');
      expect(screen.getByTestId('monitor-sidebar')).toBeInTheDocument();
      expect(screen.getByTestId('monitor-current')).toHaveTextContent('mission-exec');
    });
  });

  it('includes the configured return behavior when computing a plan', async () => {
    getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: '1', pos_id: 1 }],
    });
    sarApi.listMissions.mockResolvedValue({ missions: [], count: 0 });

    await renderPage();
    await flushAsyncState();

    await waitFor(() => expect(screen.getByTestId('plan-sidebar')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Set hold return' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set mission label' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set mission brief' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Select drone 1' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Compute plan' }));

    await waitFor(() =>
      expect(sarApi.computePlan).toHaveBeenCalledWith(
        expect.objectContaining({
          return_behavior: 'hold_position',
          mission_label: 'Harbor sweep',
          mission_brief: 'Search quay perimeter',
          mission_profile: 'rapid_search',
        })
      )
    );
    expect(screen.getByTestId('plan-return-behavior')).toHaveTextContent('hold_position');
    expect(screen.getByTestId('plan-label')).toHaveTextContent('Harbor sweep');
    expect(screen.getByTestId('plan-brief')).toHaveTextContent('Search quay perimeter');
  });

  it('sends a point-centered request for last known point missions', async () => {
    getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: '1', pos_id: 1 }],
    });
    sarApi.listMissions.mockResolvedValue({ missions: [], count: 0 });

    await renderPage();
    await flushAsyncState();

    await waitFor(() => expect(screen.getByTestId('plan-sidebar')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Use last known point' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set search center' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set search radius' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Select drone 1' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Compute plan' }));

    await waitFor(() =>
      expect(sarApi.computePlan).toHaveBeenCalledWith(
        expect.objectContaining({
          mission_template: 'last_known_point',
          search_area: expect.objectContaining({
            type: 'point',
            center: { lat: 37.25, lng: -122.15 },
            radius_m: 180,
          }),
        })
      )
    );
    expect(sarApi.computePlan.mock.calls[0][0].search_area.area_sq_m).toBeCloseTo(Math.PI * 180 * 180, 6);
    expect(screen.getByTestId('plan-template')).toHaveTextContent('last_known_point');
  });

  it('sends a corridor-search request with route geometry and width', async () => {
    getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: '1', pos_id: 1 }],
    });
    sarApi.listMissions.mockResolvedValue({ missions: [], count: 0 });

    await renderPage();
    await flushAsyncState();

    await waitFor(() => expect(screen.getByTestId('plan-sidebar')).toBeInTheDocument());
    fireEvent.click(screen.getByRole('button', { name: 'Use corridor search' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set corridor path' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Set corridor width' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Select drone 1' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Compute plan' }));

    await waitFor(() =>
      expect(sarApi.computePlan).toHaveBeenCalledWith(
        expect.objectContaining({
          mission_template: 'corridor_search',
          search_area: expect.objectContaining({
            type: 'line',
            corridor_width_m: 110,
            path: [
              { lat: 37.25, lng: -122.15 },
              { lat: 37.255, lng: -122.145 },
              { lat: 37.26, lng: -122.14 },
            ],
          }),
        })
      )
    );
    expect(sarApi.computePlan.mock.calls[0][0].search_area.area_sq_m).toBeGreaterThan(0);
    expect(screen.getByTestId('plan-template')).toHaveTextContent('corridor_search');
  });

  it('marks the launch package stale when planning inputs change after compute', async () => {
    getFleetConfigResponse.mockResolvedValue({
      data: [{ hw_id: '1', pos_id: 1 }],
    });
    sarApi.listMissions.mockResolvedValue({ missions: [], count: 0 });
    sarApi.computePlan.mockResolvedValue({
      mission_id: 'mission-ready',
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
    });
    getFleetTelemetryResponse.mockResolvedValue({
      data: {
        '1': {
          hw_ID: '1',
          hw_id: '1',
          pos_id: 1,
          position_lat: 37.0,
          position_long: -122.0,
          last_seen: Date.now(),
          readiness_status: 'ready',
          readiness_summary: 'Ready to fly',
          is_ready_to_arm: true,
          is_armed: false,
          readiness_checks: [],
          preflight_blockers: [],
          preflight_warnings: [],
          status_messages: [],
        },
      },
    });
    unwrapFleetTelemetryPayload.mockImplementation((payload) => payload);

    await renderPage();
    await flushAsyncState();

    fireEvent.click(screen.getByRole('button', { name: 'Select drone 1' }));
    await flushAsyncState();
    fireEvent.click(screen.getByRole('button', { name: 'Compute plan' }));

    await waitFor(() => {
      expect(screen.getByTestId('plan-needs-recompute')).toHaveTextContent('false');
      expect(screen.getByTestId('plan-target-count')).toHaveTextContent('1');
    });

    fireEvent.click(screen.getByRole('button', { name: 'Change mission label' }));

    await waitFor(() => {
      expect(screen.getByTestId('plan-needs-recompute')).toHaveTextContent('true');
    });
  });
});
