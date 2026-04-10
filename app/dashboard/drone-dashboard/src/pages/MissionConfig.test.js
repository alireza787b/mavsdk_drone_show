import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import MissionConfig from './MissionConfig';
import useFetch from '../hooks/useFetch';
import { useNormalizedTelemetry } from '../hooks/useNormalizedTelemetry';

jest.mock('../hooks/useFetch');
jest.mock('../hooks/useNormalizedTelemetry', () => ({
  useNormalizedTelemetry: jest.fn(),
}));
jest.mock('../utilities/missionConfigUtilities', () => ({
  handleSaveChangesToServer: jest.fn(),
  handleRevertChanges: jest.fn(),
  handleFileChange: jest.fn(),
  exportConfigJSON: jest.fn(),
  exportConfigCSV: jest.fn(),
  validateConfigWithBackend: jest.fn(() => Promise.resolve({
    data: {
      warnings: {
        duplicate_hw_ids: [],
        duplicates: [],
        missing_trajectories: [],
        role_swaps: [],
      },
      changes: [],
      summary: {},
    },
  })),
}));

jest.mock('../components/PositionTabs', () => () => <div data-testid="position-tabs" />);
jest.mock('../components/DroneConfigCard', () => ({ drone }) => (
  <div data-testid="drone-config-card">{drone.hw_id}</div>
));
jest.mock('../components/ControlButtons', () => () => <div data-testid="control-buttons" />);
jest.mock('../components/MissionLayout', () => () => <div data-testid="mission-layout" />);
jest.mock('../components/GcsConfigModal', () => () => <div data-testid="gcs-config-modal" />);
jest.mock('../components/DronePositionMap', () => () => <div data-testid="drone-position-map" />);
jest.mock('../components/SaveReviewDialog', () => () => <div data-testid="save-review-dialog" />);
jest.mock('../components/ReplaceDroneWizard', () => () => <div data-testid="replace-drone-wizard" />);
jest.mock('../components/ClusterScopeBar', () => () => <div data-testid="cluster-scope-bar" />);
jest.mock('../components/OriginModal', () => {
  function MockOriginModal({ isOpen }) {
    return isOpen ? <div data-testid="origin-modal">Origin modal</div> : null;
  }

  return MockOriginModal;
});

jest.mock('../services/gcsApiService', () => ({
  GCS_ROUTE_KEYS: {
    fleetConfig: 'fleetConfig',
    origin: 'origin',
    gcsConfig: 'gcsConfig',
    positionDeviations: 'positionDeviations',
    fleetTelemetry: 'fleetTelemetry',
    gitStatus: 'gitStatus',
    networkInfo: 'networkInfo',
    fleetHeartbeats: 'fleetHeartbeats',
    dronePositions: 'dronePositions',
    swarmConfig: 'swarmConfig',
  },
  getPositionDeviationsResponse: jest.fn(),
  getTrajectoryFirstRowResponse: jest.fn(() => Promise.resolve({ data: { x: 0, y: 0 } })),
  saveGcsConfigResponse: jest.fn(),
  setOriginResponse: jest.fn(),
  unwrapSwarmConfigPayload: jest.fn(() => []),
}));

const renderMissionConfig = () => render(
  <MemoryRouter
    future={{
      v7_startTransition: true,
      v7_relativeSplatPath: true,
    }}
  >
    <MissionConfig />
  </MemoryRouter>
);

const buildFetchResponseMap = (originResponse, overrides = {}) => ({
  fleetConfig: {
    data: [],
    loading: false,
    error: null,
  },
  origin: originResponse,
  gcsConfig: {
    data: { data: { gcs_ip: '127.0.0.1' } },
    loading: false,
    error: null,
  },
  positionDeviations: { data: {}, loading: false, error: null },
  fleetTelemetry: { data: {}, loading: false, error: null },
  networkInfo: { data: [], loading: false, error: null },
  fleetHeartbeats: { data: { heartbeats: [] }, loading: false, error: null },
  dronePositions: { data: [], loading: false, error: null },
  swarmConfig: { data: [], loading: false, error: null },
  ...overrides,
});

describe('MissionConfig origin review surface', () => {
  const originalScrollIntoView = Element.prototype.scrollIntoView;

  beforeAll(() => {
    Element.prototype.scrollIntoView = jest.fn();
  });

  beforeEach(() => {
    useNormalizedTelemetry.mockReturnValue({ data: { git_status: {}, gcs_status: null } });
  });

  afterEach(() => {
    jest.clearAllMocks();
  });

  afterAll(() => {
    Element.prototype.scrollIntoView = originalScrollIntoView;
  });

  test('does not show origin-needed warning while origin status is still loading', () => {
    const fetchResponses = buildFetchResponseMap({
      data: null,
      loading: true,
      error: null,
    });

    useFetch.mockImplementation((endpoint) => fetchResponses[endpoint] || { data: null, loading: false, error: null });

    renderMissionConfig();

    expect(screen.queryByText(/origin needed/i)).not.toBeInTheDocument();
    expect(screen.getByText('Checking')).toBeInTheDocument();
  });

  test('opens the origin workflow when the origin warning is clicked', () => {
    const fetchResponses = buildFetchResponseMap({
      data: null,
      loading: false,
      error: null,
    });

    useFetch.mockImplementation((endpoint) => fetchResponses[endpoint] || { data: null, loading: false, error: null });

    renderMissionConfig();

    fireEvent.click(
      screen
        .getByText(/set the origin before using deviation-based launch review/i)
        .closest('button')
    );

    expect(screen.getByTestId('origin-modal')).toBeInTheDocument();
  });

  test('keeps origin status reviewable even when the origin is already ready', () => {
    const fetchResponses = buildFetchResponseMap({
      data: { lat: 35.7, lon: 51.2 },
      loading: false,
      error: null,
    });

    useFetch.mockImplementation((endpoint) => fetchResponses[endpoint] || { data: null, loading: false, error: null });

    renderMissionConfig();

    fireEvent.click(
      screen.getByRole('button', { name: /origin ready review/i })
    );

    expect(screen.getByTestId('origin-modal')).toBeInTheDocument();
  });

  test('shows heartbeat-only nodes as pending enrollment instead of injecting assignment cards', () => {
    const now = Date.now();
    const fetchResponses = buildFetchResponseMap(
      {
        data: { lat: 35.7, lon: 51.2 },
        loading: false,
        error: null,
      },
      {
        fleetConfig: {
          data: [
            {
              hw_id: 1,
              pos_id: 1,
              ip: '10.0.0.1',
              mavlink_port: 14551,
              serial_port: '',
              baudrate: 0,
            },
          ],
          loading: false,
          error: null,
        },
        fleetHeartbeats: {
          data: {
            heartbeats: [
              { hw_id: 1, last_heartbeat: now - 3_000, ip: '10.0.0.1' },
              { hw_id: 99, last_heartbeat: now - 5_000, ip: '10.0.0.99', mavlink_port: 14599 },
            ],
          },
          loading: false,
          error: null,
        },
        dronePositions: {
          data: [{ pos_id: 1, x: 0, y: 0 }],
          loading: false,
          error: null,
        },
      }
    );

    useFetch.mockImplementation((endpoint) => fetchResponses[endpoint] || { data: null, loading: false, error: null });

    renderMissionConfig();

    expect(screen.getAllByTestId('drone-config-card')).toHaveLength(1);
    expect(screen.getByText(/1 detected, not enrolled/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Drone 99/).length).toBeGreaterThan(0);
  });
});
