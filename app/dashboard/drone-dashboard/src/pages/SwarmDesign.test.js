import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('react-toastify', () => ({
  toast: {
    error: jest.fn(),
    info: jest.fn(),
    success: jest.fn(),
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
  getSwarmConfigResponse: jest.fn(),
  saveSwarmConfigResponse: jest.fn(),
  unwrapSwarmConfigPayload: jest.fn((payload) => payload),
}));

const { default: SwarmDesign } = require('./SwarmDesign');
const {
  getFleetConfigResponse,
  getSwarmConfigResponse,
  unwrapSwarmConfigPayload,
} = require('../services/gcsApiService');

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
});
