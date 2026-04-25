import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import useFetch from '../hooks/useFetch';
import {
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import Overview from './Overview';

jest.mock('../hooks/useFetch', () => ({
  __esModule: true,
  default: jest.fn(),
}));

jest.mock('../services/gcsApiService', () => ({
  GCS_ROUTE_KEYS: {
    swarmConfig: '/api/v1/swarm/config',
  },
  getFleetConfigResponse: jest.fn(),
  getFleetTelemetryResponse: jest.fn(),
  unwrapFleetTelemetryPayload: jest.fn((payload) => payload || {}),
  unwrapSwarmConfigPayload: jest.fn(() => []),
}));

jest.mock('../components/CommandSender', () => {
  const React = require('react');
  return function MockCommandSender() {
    return React.createElement('section', { 'aria-label': 'Command dispatch' }, 'Command dispatch');
  };
});
jest.mock('../components/ClusterScopeBar', () => jest.fn(() => null));
jest.mock('../components/DroneWidget', () => {
  const React = require('react');
  return function MockDroneWidget({ drone }) {
    return React.createElement('article', null, `Drone ${drone.hw_ID}`);
  };
});
jest.mock('../components/ExpandedDronePortal', () => jest.fn(() => null));

const renderOverview = () => render(
  <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <Overview setSelectedDrone={jest.fn()} />
  </MemoryRouter>
);

describe('Overview', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useFetch.mockReturnValue({ data: [] });
    unwrapFleetTelemetryPayload.mockImplementation((payload) => payload || {});
    unwrapSwarmConfigPayload.mockReturnValue([]);
    getFleetConfigResponse.mockResolvedValue({ data: [] });
  });

  test('renders shared empty state when telemetry has no valid drones', async () => {
    getFleetTelemetryResponse.mockResolvedValue({ data: {}, headers: {} });

    renderOverview();

    expect(await screen.findByRole('heading', { name: 'No valid drone data' })).toBeInTheDocument();
    expect(screen.getByText('When telemetry resumes, aircraft cards will populate here automatically.')).toBeInTheDocument();
    expect(screen.getByLabelText('Command dispatch')).toBeInTheDocument();
  });

  test('renders compact fleet metrics and commandable drone cards', async () => {
    const nowSeconds = Math.floor(Date.now() / 1000);
    getFleetTelemetryResponse.mockResolvedValue({
      data: {
        1: {
          hw_id: '1',
          pos_id: 1,
          position_lat: 47.1,
          position_long: 8.1,
          position_alt: 12,
          battery_voltage: 15.8,
          timestamp: nowSeconds,
          update_time: nowSeconds,
          telemetry_available: true,
        },
      },
      headers: {},
    });

    renderOverview();

    expect(await screen.findByText('Drone 1')).toBeInTheDocument();
    expect(screen.getByRole('list', { name: 'Fleet overview' })).toBeInTheDocument();
    expect(screen.getByText('1/1 card visible')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /currently visible commandable fleet/i })).toHaveTextContent('Visible in dispatch');
  });
});
