import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('react-toastify', () => ({
  toast: {
    error: jest.fn(),
    info: jest.fn(),
    success: jest.fn(),
    warning: jest.fn(),
  },
}));

jest.mock('../hooks/useNormalizedTelemetry', () => ({
  __esModule: true,
  default: jest.fn(() => ({ data: {} })),
}));

jest.mock('../components/DroneCard', () => {
  const React = require('react');
  return React.forwardRef(({ drone }, ref) => (
    <button type="button" ref={ref}>
      {drone.title || drone.hw_id}
    </button>
  ));
});

jest.mock('../components/DroneGraph', () => () => <div data-testid="swarm-graph" />);
jest.mock('../components/SwarmPlots', () => () => <div data-testid="swarm-plots" />);
jest.mock('../components/SwarmRuntimeControls', () => () => <div data-testid="swarm-runtime-controls" />);
jest.mock('../components/ClusterScopeBar', () => () => <div data-testid="cluster-scope" />);
jest.mock('../components/IdentityDoctrineStrip', () => () => <div data-testid="identity-doctrine" />);

jest.mock('../services/gcsApiService', () => ({
  GCS_ROUTE_KEYS: {
    fleetTelemetry: 'fleetTelemetry',
  },
  getFleetConfigResponse: jest.fn(),
  getUnifiedGitStatusResponse: jest.fn(),
  getSwarmConfigResponse: jest.fn(),
  saveSwarmConfigResponse: jest.fn(),
  unwrapSwarmConfigPayload: jest.fn((payload) => payload),
}));

const { default: SwarmDesign } = require('./SwarmDesign');
const {
  getFleetConfigResponse,
  getUnifiedGitStatusResponse,
  saveSwarmConfigResponse,
  getSwarmConfigResponse,
  unwrapSwarmConfigPayload,
} = require('../services/gcsApiService');
const { toast } = require('react-toastify');

const renderPage = () => render(
  <MemoryRouter
    future={{
      v7_startTransition: true,
      v7_relativeSplatPath: true,
    }}
  >
    <SwarmDesign />
  </MemoryRouter>
);

describe('SwarmDesign', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
      ],
    });
    getSwarmConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ENU' },
        { hw_id: 2, follow: 1, offset_x: 4, offset_y: 0, offset_z: 0, frame: 'ENU' },
      ],
    });
    getUnifiedGitStatusResponse.mockResolvedValue({
      data: {
        gcs_status: {
          status: 'clean',
          uncommitted_changes: [],
        },
      },
    });
  });

  test('renders compact operator shell, docs link, and assignment surfaces', async () => {
    renderPage();

    expect(screen.getByRole('heading', { name: 'Operational Swarm Design' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /smart swarm guide/i })).toHaveAttribute(
      'href',
      'https://github.com/alireza787b/mavsdk_drone_show/blob/main/docs/features/smart-swarm.md'
    );

    await waitFor(() => {
      expect(getFleetConfigResponse).toHaveBeenCalled();
      expect(getSwarmConfigResponse).toHaveBeenCalled();
      expect(unwrapSwarmConfigPayload).toHaveBeenCalled();
    });

    expect(screen.getByRole('list', { name: 'Smart Swarm topology summary' })).toBeInTheDocument();
    expect(screen.getByTestId('swarm-runtime-controls')).toBeInTheDocument();
    expect(screen.getByTestId('swarm-graph')).toBeInTheDocument();
    const exportButtons = screen.getAllByRole('button', { name: /export smart swarm assignments as csv/i });
    expect(exportButtons.length).toBeGreaterThan(0);
    exportButtons.forEach((button) => expect(button).toBeEnabled());
  });

  test('commits pending swarm sync once and gives operator progress feedback', async () => {
    getFleetConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, pos_id: 1, ip: '10.0.0.11' },
        { hw_id: 2, pos_id: 2, ip: '10.0.0.12' },
        { hw_id: 3, pos_id: 3, ip: '10.0.0.13' },
      ],
    });
    getSwarmConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ENU' },
        { hw_id: 2, follow: 1, offset_x: 4, offset_y: 0, offset_z: 0, frame: 'ENU' },
      ],
    });
    saveSwarmConfigResponse.mockResolvedValue({
      data: {
        message: 'Smart Swarm configuration saved and committed successfully.',
        git_result: { success: true },
      },
    });

    renderPage();

    const commitButton = await screen.findByRole('button', { name: /commit smart swarm assignment changes/i });
    expect(commitButton).toBeEnabled();

    fireEvent.click(commitButton);
    const dialog = await screen.findByRole('dialog', { name: /commit smart swarm assignments/i });
    fireEvent.click(within(dialog).getByRole('button', { name: /^commit$/i }));

    await waitFor(() => expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1));
    expect(saveSwarmConfigResponse).toHaveBeenCalledWith(expect.any(Array), { commit: true });
    expect(toast.info).toHaveBeenCalledWith('Committing Smart Swarm assignments...');
  });

  test('keeps commit available when swarm json is saved but not committed', async () => {
    getFleetConfigResponse.mockResolvedValue({ data: [] });
    getSwarmConfigResponse.mockResolvedValue({
      data: [
        { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
        { hw_id: 2, follow: 1, offset_x: 4, offset_y: 0, offset_z: 0, frame: 'ned' },
      ],
    });
    getUnifiedGitStatusResponse.mockResolvedValue({
      data: {
        gcs_status: {
          status: 'dirty',
          uncommitted_changes: [' M swarm.json'],
        },
      },
    });
    saveSwarmConfigResponse.mockResolvedValue({
      data: {
        message: 'Swarm configuration saved successfully',
        git_result: {
          success: true,
          message: 'Changes pushed to repository successfully.',
          commit_hash: 'abc12345',
          pushed: true,
        },
      },
    });

    renderPage();

    const commitButton = await screen.findByRole('button', { name: /commit smart swarm assignment changes/i });
    await waitFor(() => expect(commitButton).toBeEnabled());
    expect(await screen.findByText(/swarm\.json is saved on this GCS and still needs git commit/i)).toBeInTheDocument();

    fireEvent.click(commitButton);
    const dialog = await screen.findByRole('dialog', { name: /commit smart swarm assignments/i });
    expect(within(dialog).getByText(/saved swarm\.json change pending git commit/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole('button', { name: /^commit$/i }));

    await waitFor(() => expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1));
    expect(saveSwarmConfigResponse).toHaveBeenCalledWith(expect.any(Array), { commit: true });
    expect(await screen.findByText(/Changes pushed to repository successfully/i)).toBeInTheDocument();
  });
});
