import React from 'react';
import { render, screen } from '@testing-library/react';

import GlobeView from './GlobeView';
import {
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
} from '../services/gcsApiService';
import {
  buildGlobeDroneViewModels,
  calculateGlobeTelemetryIntervalMs,
} from '../utilities/globeTelemetryViewModel';

jest.mock('../components/Globe', () => ({
  __esModule: true,
  default: ({ drones }) => <div data-testid="globe-scene">{drones.length} drones in 3D scene</div>,
}));

jest.mock('../components/GlobeMapView', () => ({
  __esModule: true,
  default: ({ drones }) => <div data-testid="globe-map">{drones.length} drones on map</div>,
}));

jest.mock('../components/IdentityDoctrineStrip', () => ({
  __esModule: true,
  default: () => <div data-testid="identity-doctrine" />,
}));

jest.mock('../services/gcsApiService', () => {
  const actual = jest.requireActual('../services/gcsApiService');
  return {
    ...actual,
    buildTelemetryWebSocketUrl: jest.fn(() => 'ws://localhost/ws/telemetry'),
    getFleetConfigResponse: jest.fn(),
    getFleetTelemetryResponse: jest.fn(),
    unwrapFleetTelemetryPayload: jest.fn((payload) => payload),
  };
});

jest.mock('../utilities/globeTelemetryViewModel', () => ({
  buildGlobeDroneViewModels: jest.fn(),
  calculateGlobeTelemetryIntervalMs: jest.fn(() => 1000),
}));

describe('GlobeView', () => {
  const originalWebSocket = window.WebSocket;

  beforeEach(() => {
    jest.clearAllMocks();
    window.WebSocket = undefined;
    calculateGlobeTelemetryIntervalMs.mockReturnValue(1000);
    getFleetConfigResponse.mockResolvedValue({ data: [] });
    getFleetTelemetryResponse.mockResolvedValue({ data: { drones: [] } });
    unwrapFleetTelemetryPayload.mockImplementation((payload) => payload);
    buildGlobeDroneViewModels.mockReturnValue([]);
  });

  afterAll(() => {
    window.WebSocket = originalWebSocket;
  });

  test('uses the operator shell and compact loading state while telemetry connects', () => {
    getFleetTelemetryResponse.mockReturnValue(new Promise(() => {}));

    render(<GlobeView />);

    expect(screen.getByRole('heading', { name: /fleet map/i })).toBeInTheDocument();
    expect(screen.getByText(/loading telemetry/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /map setup/i })).toHaveAttribute(
      'href',
      'docs/guides/mapbox-setup.md',
    );
  });

  test('shows a compact no-targets state for empty telemetry', async () => {
    render(<GlobeView />);

    expect(await screen.findByText(/no telemetry targets/i)).toBeInTheDocument();
    expect(screen.getByText(/no configured or live drones/i)).toBeInTheDocument();
  });

  test('renders 3D scene and selection chips for live drones', async () => {
    buildGlobeDroneViewModels.mockReturnValue([
      {
        hw_id: '1',
        pos_id: 1,
        marker_color: '#ffaa00',
        runtime_indicator_class: 'ready',
      },
    ]);

    render(<GlobeView />);

    expect(await screen.findByTestId('globe-scene')).toHaveTextContent('1 drones in 3D scene');
    expect(screen.getByRole('button', { name: /select.*h1/i })).toBeInTheDocument();
    expect(screen.getByText('HTTP · 1.0s')).toBeInTheDocument();
  });
});
