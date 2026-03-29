import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import TrajectoryPlanning from './TrajectoryPlanning';
import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from '../utilities/SpeedCalculator';

let mockMapClickIndex = 0;

jest.mock('react-map-gl', () => {
  const React = require('react');
  const clickPoints = [
    { lng: 51.2721, lat: 35.7262 },
    { lng: 51.2733, lat: 35.7274 },
    { lng: 51.2745, lat: 35.7286 },
  ];

  return {
    Map: ({ children, onClick }) => (
      <div>
        <button
          type="button"
          data-testid="mock-map"
          onClick={() => {
            const point = clickPoints[mockMapClickIndex] || clickPoints[clickPoints.length - 1];
            mockMapClickIndex += 1;
            onClick?.({ lngLat: point });
          }}
        >
          Mock Map
        </button>
        {children}
      </div>
    ),
    Source: ({ children }) => <div>{children}</div>,
    Layer: () => null,
    Marker: ({ children, onClick }) => (
      <div role="button" tabIndex={0} onClick={onClick} onKeyDown={() => {}}>
        {children}
      </div>
    ),
  };
});

jest.mock('../contexts/MapContext', () => ({
  useMapContext: () => ({ provider: 'mapbox', isMapboxAvailable: true }),
}));

jest.mock('../components/map/MapProviderToggle', () => () => <div data-testid="map-provider-toggle" />);
jest.mock('../components/map/MapFallbackBanner', () => () => null);
jest.mock('../components/map/LeafletMapBase', () => ({ children }) => <div>{children}</div>);
jest.mock('react-leaflet', () => ({
  Marker: ({ children }) => <div>{children}</div>,
  Polyline: () => null,
  useMapEvents: () => null,
}));
jest.mock('leaflet', () => ({
  divIcon: jest.fn(() => ({})),
}));

jest.mock('../components/trajectory/SearchBar', () => () => <div data-testid="search-bar" />);
jest.mock('../components/trajectory/TrajectoryStats', () => ({ stats }) => (
  <div data-testid="trajectory-stats">{stats.totalTime}</div>
));
jest.mock('../components/trajectory/TrajectoryToolbar', () => (props) => (
  <div data-testid="trajectory-toolbar">
    <button type="button" onClick={props.onToggleAddWaypoint}>
      Toggle Add
    </button>
    <button type="button" onClick={props.onSendToSwarm} disabled={!props.canSendToSwarm}>
      Send to Swarm
    </button>
    <span data-testid="toolbar-waypoint-count">{props.waypointCount}</span>
  </div>
));
jest.mock('../components/trajectory/WaypointPanel', () => ({ waypoints }) => (
  <div data-testid="waypoint-panel-state">
    {JSON.stringify(
      waypoints.map((waypoint) => ({
        headingMode: waypoint.headingMode,
        estimatedSpeed: waypoint.estimatedSpeed,
        altitudeReference: waypoint.altitudeReference,
        targetAgl: waypoint.targetAgl,
      }))
    )}
  </div>
));
jest.mock('../components/trajectory/WaypointModal', () => (props) => {
  if (!props.isOpen) {
    return null;
  }

  const payload = props.waypointIndex === 1
    ? {
        altitude: 150,
        altitudeReference: ALTITUDE_REFERENCE.MSL,
        targetAgl: 0,
        timeFromStart: 12,
        timingMode: TIMING_MODES.MANUAL_TIME,
        preferredSpeed: 0,
        heading: 45,
        headingMode: YAW_CONSTANTS.MANUAL,
        calculatedHeading: 45,
        terrainInfo: null,
        groundElevation: 0,
        terrainAccurate: true,
      }
    : {
        altitude: 160,
        altitudeReference: ALTITUDE_REFERENCE.AGL,
        targetAgl: 120,
        timeFromStart: 30,
        timingMode: TIMING_MODES.AUTO_SPEED,
        preferredSpeed: 8,
        heading: 0,
        headingMode: YAW_CONSTANTS.AUTO,
        calculatedHeading: 0,
        terrainInfo: null,
        groundElevation: 40,
        terrainAccurate: true,
      };

  return (
    <div data-testid="waypoint-modal">
      <button type="button" onClick={() => props.onConfirm(payload)}>
        Confirm waypoint {props.waypointIndex}
      </button>
    </div>
  );
});
jest.mock('../components/trajectory/SwarmTrajectoryTransferDialog', () => () => null);
jest.mock('../components/trajectory/TrajectoryExportDialog', () => () => null);
jest.mock('../components/trajectory/TrajectoryLibraryDialog', () => () => null);

jest.mock('../services/droneApiService', () => ({
  getSwarmClusterStatus: jest.fn().mockResolvedValue({ clusters: [] }),
  uploadSwarmTrajectory: jest.fn().mockResolvedValue({ success: true, message: 'uploaded' }),
}));

jest.mock('../utilities/TrajectoryStorage', () => ({
  TrajectoryStorage: jest.fn().mockImplementation(() => ({
    getAllTrajectories: jest.fn(() => []),
    autoSave: jest.fn().mockResolvedValue({ success: true }),
    saveTrajectory: jest.fn().mockResolvedValue({ success: true, message: 'saved' }),
    loadTrajectory: jest.fn(),
    importTrajectory: jest.fn(),
    exportCurrentTrajectory: jest.fn().mockResolvedValue({ success: true, message: 'exported' }),
    convertToCSV: jest.fn(() => 'csv'),
  })),
}));

describe('TrajectoryPlanning', () => {
  beforeEach(() => {
    mockMapClickIndex = 0;
  });

  it('moves from an empty planner to draft and then ready posture as waypoints are authored', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    expect(screen.getByText('Not ready')).toBeInTheDocument();
    expect(screen.getByText('No path yet')).toBeInTheDocument();
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('0');

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 1'));

    await waitFor(() => {
      expect(screen.getAllByText('Draft only').length).toBeGreaterThan(0);
    });
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('1');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"headingMode":"manual"');

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 2'));

    await waitFor(() => {
      expect(screen.getAllByText('Ready to process').length).toBeGreaterThan(0);
    });

    expect(screen.getByText('2 waypoints')).toBeInTheDocument();
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('2');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"altitudeReference":"agl"');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"targetAgl":120');
  });
});
