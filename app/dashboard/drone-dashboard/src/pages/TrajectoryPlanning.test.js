import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import TrajectoryPlanning from './TrajectoryPlanning';
import {
  getSwarmClusterStatus,
  getSwarmTrajectoryPolicy,
  getSwarmTrajectoryElevationBatch,
  uploadSwarmTrajectory,
} from '../services/droneApiService';
import { suggestOptimalTime } from '../utilities/SpeedCalculator';
import { TrajectoryStorage } from '../utilities/TrajectoryStorage';
import {
  resetTrajectoryMissionPolicy,
  TRAJECTORY_SPEED_POLICY,
} from '../constants/trajectoryMissionPolicy';

let mockMapClickIndex = 0;
const originalMapboxToken = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN;

jest.mock('react-map-gl', () => {
  const React = require('react');
  const clickPoints = [
    { lng: 51.2721, lat: 35.7262 },
    { lng: 51.2733, lat: 35.7274 },
    { lng: 51.2745, lat: 35.7286 },
  ];
  const MockMap = React.forwardRef(({ children, onClick, latitude, longitude, zoom }, ref) => (
    <div ref={ref} data-testid="map-viewport" data-latitude={latitude} data-longitude={longitude} data-zoom={zoom}>
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
  ));

  return {
    Map: MockMap,
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
  useMap: () => ({
    invalidateSize: jest.fn(),
    flyTo: jest.fn(),
  }),
}));
jest.mock('leaflet', () => ({
  divIcon: jest.fn(() => ({})),
}));

jest.mock('../components/trajectory/SearchBar', () => () => <div data-testid="search-bar" />);
jest.mock('../components/trajectory/TrajectoryStats', () => ({ stats }) => (
  <div data-testid="trajectory-stats">{stats.totalTime}</div>
));
jest.mock('../components/trajectory/TrajectorySegmentReview', () => ({ segments }) => (
  <div data-testid="trajectory-segment-review">{segments.length}</div>
));
jest.mock('../components/trajectory/TrajectoryToolbar', () => (props) => (
  <div data-testid="trajectory-toolbar">
    <button type="button" onClick={props.onToggleAddWaypoint}>
      Toggle Add
    </button>
    <button type="button" onClick={props.onSendToSwarm} disabled={!props.canSendToSwarm}>
      Assign to Cluster
    </button>
    <button type="button" onClick={props.onUndo} disabled={!props.canUndo}>Undo</button>
    <button type="button" onClick={props.onRedo} disabled={!props.canRedo}>Redo</button>
    <button type="button" onClick={props.onLoad}>Open library</button>
    <span data-testid="toolbar-waypoint-count">{props.waypointCount}</span>
  </div>
));
jest.mock('../components/trajectory/WaypointPanel', () => ({ waypoints, onUpdateWaypoint, onMoveWaypoint }) => (
  <div>
    <div data-testid="waypoint-panel-state">
      {JSON.stringify(
        waypoints.map((waypoint) => ({
          id: waypoint.id,
          name: waypoint.name,
          latitude: waypoint.latitude,
          longitude: waypoint.longitude,
          headingMode: waypoint.headingMode,
          estimatedSpeed: waypoint.estimatedSpeed,
          altitudeReference: waypoint.altitudeReference,
          targetAgl: waypoint.targetAgl,
          altitude: waypoint.altitude,
          timeFromStart: waypoint.timeFromStart,
          timingMode: waypoint.timingMode,
          preferredSpeed: waypoint.preferredSpeed,
          groundElevation: waypoint.groundElevation,
          terrainAccurate: waypoint.terrainAccurate,
          terrainError: waypoint.terrainError,
          terrainSource: waypoint.terrainSource,
        }))
      )}
    </div>
    {waypoints[1] && (
      <button type="button" onClick={() => onMoveWaypoint(waypoints[1].id, 'up')}>Move waypoint 2 up</button>
    )}
    {waypoints[1] && (
      <button
        type="button"
        onClick={() =>
          onUpdateWaypoint(waypoints[1].id, {
            latitude: 35.73,
            longitude: 51.28,
          })
        }
      >
        Refresh terrain on waypoint 2
      </button>
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
        altitudeReference: 'msl',
        targetAgl: 0,
        timeFromStart: 12,
        timingMode: 'manual_time',
        preferredSpeed: 0,
        heading: 45,
        headingMode: 'manual',
        calculatedHeading: 45,
        terrainInfo: null,
        groundElevation: 0,
        terrainAccurate: true,
        terrainError: '',
        terrainSource: 'backend',
      }
    : {
        altitude: 160,
        altitudeReference: 'agl',
        targetAgl: 120,
        timeFromStart: 30,
        timingMode: 'auto_speed',
        preferredSpeed: 8,
        heading: 0,
        headingMode: 'auto',
        calculatedHeading: 0,
        terrainInfo: null,
        groundElevation: 40,
        terrainAccurate: true,
        terrainError: '',
        terrainSource: 'backend',
      };

  return (
    <div data-testid="waypoint-modal">
      <button type="button" onClick={() => props.onConfirm(payload)}>
        Confirm waypoint {props.waypointIndex}
      </button>
    </div>
  );
});
jest.mock('../components/trajectory/SwarmTrajectoryTransferDialog', () => (props) => {
  if (!props.isOpen) {
    return null;
  }

  return (
    <div data-testid="swarm-transfer-dialog">
      <div data-testid="transfer-clusters">{props.clusters.map((cluster) => cluster.leader_id).join(',')}</div>
      <div data-testid="transfer-leader">{props.selectedLeaderId}</div>
      <div data-testid="transfer-lock">{props.lockedLeaderId}</div>
      <div role="alert">{props.error}</div>
      <button type="button" onClick={() => props.onSelectLeaderId(99)}>Select unrelated leader</button>
      <button type="button" onClick={() => props.onSubmit()}>
        Submit transfer
      </button>
    </div>
  );
});
jest.mock('../components/trajectory/TrajectoryExportDialog', () => () => null);
jest.mock('../components/trajectory/TrajectoryLibraryDialog', () => (props) => (
  props.isOpen && props.mode === 'load'
    ? <button type="button" onClick={() => props.onLoad('legacy-route')}>Load legacy route</button>
    : null
));

jest.mock('../services/droneApiService', () => ({
  getSwarmClusterStatus: jest.fn().mockResolvedValue({ clusters: [] }),
  getSwarmTrajectoryPolicy: jest.fn().mockResolvedValue({ success: true, policy: {} }),
  getSwarmTrajectoryElevationBatch: jest.fn(),
  uploadSwarmTrajectory: jest.fn().mockResolvedValue({ success: true, message: 'uploaded' }),
}));

describe('TrajectoryPlanning', () => {
  beforeEach(() => {
    mockMapClickIndex = 0;
    process.env.REACT_APP_MAPBOX_ACCESS_TOKEN = 'test-mapbox-token';
    window.localStorage.clear();
    resetTrajectoryMissionPolicy();
    getSwarmTrajectoryElevationBatch.mockImplementation(async (points) => ({
      success: true,
      results: points.map((point) => ({ ...point, status: 'ok', elevation_m: 0, source: 'backend' })),
    }));
    getSwarmClusterStatus.mockResolvedValue({
      clusters: [
        {
          leader_id: 1,
          follower_count: 2,
          follower_ids: [2, 3],
          issues: [],
          advisories: [],
        },
      ],
    });
    getSwarmTrajectoryPolicy.mockResolvedValue({ success: true, policy: {} });
    uploadSwarmTrajectory.mockResolvedValue({ success: true, message: 'uploaded' });
  });

  afterAll(() => {
    process.env.REACT_APP_MAPBOX_ACCESS_TOKEN = originalMapboxToken;
    resetTrajectoryMissionPolicy();
  });

  afterEach(() => {
    window.innerWidth = 1024;
    jest.useRealTimers();
    jest.restoreAllMocks();
  });

  it('moves from an empty planner to draft and then ready posture as waypoints are authored', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    await waitFor(() => expect(getSwarmTrajectoryPolicy).toHaveBeenCalled());

    expect(screen.getByText('Not ready')).toBeInTheDocument();
    expect(screen.getByText('No path yet')).toBeInTheDocument();
    expect(screen.getByText('Top leaders • Global MSL')).toBeInTheDocument();
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('0');
    expect(screen.getByTestId('trajectory-segment-review')).toHaveTextContent('0');
    expect(screen.getByText('Author top-leader path')).toBeInTheDocument();
    expect(screen.getByText(/Waypoint 1 anchors route-entry delay and heading/i)).toBeInTheDocument();
    expect(screen.getByText(/all current waypoints use direct msl altitude input/i)).toBeInTheDocument();
    expect(screen.getByText(/Waypoint 1 will define route-entry delay and heading/i)).toBeInTheDocument();
    expect(screen.getByText(/authored in global latitude\/longitude with stored MSL altitude/i)).toBeInTheDocument();
    expect(screen.getByText(/instantaneous global position using the current swarm offsets/i)).toBeInTheDocument();

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
    expect(screen.getAllByText(/1 speed-driven leg/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/1 terrain-assisted waypoint/i)).toBeInTheDocument();
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('2');
    expect(screen.getByTestId('trajectory-segment-review')).toHaveTextContent('1');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"altitudeReference":"agl"');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"targetAgl":120');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"terrainSource":"backend"');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"terrainError":""');
  });

  it('uses the compact workflow brief on small viewports so the map stays primary', async () => {
    window.innerWidth = 640;

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    await waitFor(() => expect(getSwarmTrajectoryPolicy).toHaveBeenCalled());

    expect(screen.getByText('Route review & policy', { selector: 'span' })).toBeInTheDocument();
    expect(screen.getByText(/No route yet .* Not ready/i)).toBeInTheDocument();
    expect(screen.getByTestId('trajectory-toolbar')).toBeInTheDocument();
  });

  it('hydrates planner policy from the backend runtime contract', async () => {
    getSwarmTrajectoryPolicy.mockResolvedValue({
      success: true,
      policy: {
        speed: {
          optimal_max: 10,
          absolute_max: 16,
        },
      },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    await waitFor(() => expect(getSwarmTrajectoryPolicy).toHaveBeenCalled());
    await waitFor(() => expect(TRAJECTORY_SPEED_POLICY.ABSOLUTE_MAX).toBe(16));
    expect(TRAJECTORY_SPEED_POLICY.OPTIMAL_MAX).toBe(10);
  });

  it('refreshes terrain context when a waypoint is moved and preserves target AGL intent', async () => {
    getSwarmTrajectoryElevationBatch.mockImplementation(async (points) => ({
      success: true,
      results: points.map((point) => ({ ...point, status: 'ok', elevation_m: 85, source: 'backend' })),
    }));

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    await waitFor(() => expect(getSwarmTrajectoryPolicy).toHaveBeenCalled());

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 1'));

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 2'));

    fireEvent.click(screen.getByRole('button', { name: /refresh terrain on waypoint 2/i }));

    const expectedArrivalTime = suggestOptimalTime(
      {
        latitude: 35.7262,
        longitude: 51.2721,
        altitude: 150,
        timeFromStart: 12,
      },
      {
        latitude: 35.73,
        longitude: 51.28,
      },
      8,
      205
    );

    await waitFor(() => {
      expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"groundElevation":85');
    });

    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"targetAgl":120');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"altitude":205');
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent(`"timeFromStart":${expectedArrivalTime}`);
    expect(screen.getByTestId('waypoint-panel-state')).toHaveTextContent('"terrainAccurate":true');
  });

  it('offers a direct handoff into Swarm Trajectory after assigning the current leader path', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <TrajectoryPlanning />
      </MemoryRouter>
    );

    await waitFor(() => expect(getSwarmTrajectoryPolicy).toHaveBeenCalled());

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 1'));

    fireEvent.click(screen.getByText('Toggle Add'));
    fireEvent.click(screen.getByTestId('mock-map'));
    fireEvent.click(await screen.findByText('Confirm waypoint 2'));

    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));
    fireEvent.click(await screen.findByRole('button', { name: /submit transfer/i }));

    expect(await screen.findByRole('button', { name: /open swarm trajectory/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /stay in planner/i })).toBeInTheDocument();
  });

  const draft = [
    { id: 'a', name: 'Waypoint 1', latitude: 0, longitude: 0, altitude: 100, timeFromStart: 5, timingMode: 'manual_time', headingMode: 'manual', heading: 0, altitudeReference: 'msl' },
    { id: 'b', name: 'Waypoint 2', latitude: 0.001, longitude: 0, altitude: 100, timeFromStart: 30, timingMode: 'auto_speed', preferredSpeed: 5, headingMode: 'auto', altitudeReference: 'msl' },
    { id: 'c', name: 'Waypoint 3', latitude: 0.002, longitude: 0, altitude: 100, timeFromStart: 60, timingMode: 'auto_speed', preferredSpeed: 5, headingMode: 'auto', altitudeReference: 'msl' },
  ];
  const renderEditor = (props) => render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TrajectoryPlanning {...props} />
    </MemoryRouter>
  );

  it('hydrates the scoped draft once, preserves zero coordinates, and reports edits without resetting history', async () => {
    const onWaypointsChange = jest.fn();
    const { rerender } = renderEditor({ embedded: true, scopedLeaderId: 1, initialWaypoints: draft, onWaypointsChange });
    expect(screen.queryByRole('heading', { name: 'Advanced Route Editor' })).not.toBeInTheDocument();
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('3');
    expect(screen.getByTestId('map-viewport')).toHaveAttribute('data-latitude', '0');
    expect(screen.getByTestId('map-viewport')).toHaveAttribute('data-longitude', '0');
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();

    fireEvent.click(screen.getByText('Move waypoint 2 up'));
    await waitFor(() => expect(onWaypointsChange).toHaveBeenLastCalledWith(expect.arrayContaining([
      expect.objectContaining({ id: 'b', name: 'Waypoint 1', timeFromStart: 5 }),
    ])));
    const reordered = onWaypointsChange.mock.calls.at(-1)[0];
    expect(reordered.map((waypoint) => waypoint.id)).toEqual(['b', 'a', 'c']);
    expect(reordered[0].estimatedSpeed).toBe(0);
    expect(reordered[2].timeFromStart).toBeGreaterThan(reordered[1].timeFromStart);

    rerender(<MemoryRouter><TrajectoryPlanning embedded scopedLeaderId={1} initialWaypoints={[]} onWaypointsChange={onWaypointsChange} /></MemoryRouter>);
    expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('3');
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(onWaypointsChange.mock.calls.at(-1)[0].map((waypoint) => waypoint.id)).toEqual(['a', 'b', 'c']));
    fireEvent.click(screen.getByRole('button', { name: 'Redo' }));
    await waitFor(() => expect(onWaypointsChange.mock.calls.at(-1)[0].map((waypoint) => waypoint.id)).toEqual(['b', 'a', 'c']));
  });

  it('uses a neutral world view for an empty route instead of an arbitrary mission location', () => {
    renderEditor({});
    expect(screen.getByTestId('map-viewport')).toHaveAttribute('data-latitude', '0');
    expect(screen.getByTestId('map-viewport')).toHaveAttribute('data-longitude', '0');
    expect(screen.getByTestId('map-viewport')).toHaveAttribute('data-zoom', '2');
  });

  it('does not write a scoped leader draft into the global autosave library', async () => {
    jest.useFakeTimers();
    const autoSave = jest.spyOn(TrajectoryStorage.prototype, 'autoSave');
    renderEditor({ scopedLeaderId: 1, initialWaypoints: draft });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(autoSave).not.toHaveBeenCalled();
  });

  it('preserves standalone library autosave', async () => {
    jest.useFakeTimers();
    const autoSave = jest.spyOn(TrajectoryStorage.prototype, 'autoSave').mockResolvedValue({ success: true });
    renderEditor({ initialWaypoints: draft });
    await act(async () => { await Promise.resolve(); });
    await act(async () => { jest.advanceTimersByTime(30000); });
    expect(autoSave).toHaveBeenCalledWith(expect.any(Array), expect.any(Object));
  });

  it('locks assignment to its mission leader and acknowledges success without standalone navigation', async () => {
    const onAssigned = jest.fn();
    getSwarmClusterStatus.mockResolvedValue({ clusters: [
      { leader_id: 1, follower_ids: [2], follower_count: 1 },
      { leader_id: 99, follower_ids: [], follower_count: 0 },
    ] });
    renderEditor({ embedded: true, scopedLeaderId: 1, initialWaypoints: draft, onAssigned });
    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));
    await waitFor(() => expect(screen.getByTestId('transfer-clusters')).toHaveTextContent(/^1$/));
    fireEvent.click(screen.getByText('Select unrelated leader'));
    expect(screen.getByTestId('transfer-leader')).toHaveTextContent(/^1$/);
    expect(screen.getByTestId('transfer-lock')).toHaveTextContent(/^1$/);
    fireEvent.click(screen.getByText('Submit transfer'));
    await waitFor(() => expect(onAssigned).toHaveBeenCalledWith(1, expect.objectContaining({ success: true })));
    expect(uploadSwarmTrajectory).toHaveBeenLastCalledWith(1, expect.any(Blob), 'Drone 1.csv');
    expect(screen.queryByRole('button', { name: /open swarm trajectory/i })).not.toBeInTheDocument();
  });

  it.each([
    { terrainAccurate: false },
    { terrainAccurate: undefined },
    { terrainAccurate: true, terrainError: 'Provider unavailable' },
  ])('blocks scoped AGL assignment without verified terrain (%o)', async (terrainContext) => {
    const onAssigned = jest.fn();
    const uploadsBefore = uploadSwarmTrajectory.mock.calls.length;
    renderEditor({ scopedLeaderId: 1, initialWaypoints: draft.map((waypoint) => ({ ...waypoint, altitudeReference: 'agl', ...terrainContext })), onAssigned });
    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));
    await waitFor(() => expect(screen.getByTestId('transfer-clusters')).toHaveTextContent(/^1$/));
    fireEvent.click(screen.getByText('Submit transfer'));
    expect(await screen.findByText(/Resolve terrain elevation for all AGL waypoints/i)).toBeInTheDocument();
    expect(uploadSwarmTrajectory.mock.calls).toHaveLength(uploadsBefore);
    expect(onAssigned).not.toHaveBeenCalled();
  });

  it('does not acknowledge assignment when the server rejects its upload', async () => {
    const onAssigned = jest.fn();
    uploadSwarmTrajectory.mockResolvedValue({ success: false, message: 'Route rejected' });
    renderEditor({ scopedLeaderId: 1, initialWaypoints: draft, onAssigned });
    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));
    await waitFor(() => expect(screen.getByTestId('transfer-clusters')).toHaveTextContent(/^1$/));
    fireEvent.click(screen.getByText('Submit transfer'));
    expect(await screen.findByText('Route rejected')).toBeInTheDocument();
    expect(onAssigned).not.toHaveBeenCalled();
  });

  it('re-resolves legacy verified AGL from the library and cannot assign it when backend terrain is unavailable', async () => {
    const storage = new TrajectoryStorage();
    const onWaypointsChange = jest.fn();
    const uploadsBefore = uploadSwarmTrajectory.mock.calls.length;
    await storage.saveTrajectory('legacy-route', draft.map((waypoint) => ({
      ...waypoint, altitudeReference: 'AGL', targetAgl: 80, groundElevation: 20, terrainAccurate: true,
    })));
    getSwarmTrajectoryElevationBatch.mockResolvedValue({ success: true, results: [] });
    renderEditor({ embedded: true, scopedLeaderId: 1, onWaypointsChange });
    fireEvent.click(screen.getByText('Open library'));
    fireEvent.click(await screen.findByText('Load legacy route'));
    await waitFor(() => expect(screen.getByTestId('toolbar-waypoint-count')).toHaveTextContent('3'));
    expect(onWaypointsChange.mock.calls.at(-1)[0]).toEqual(expect.arrayContaining([
      expect.objectContaining({ altitude: 100, altitudeReference: 'agl', terrainAccurate: false, terrainError: 'Terrain elevation unavailable.' }),
    ]));
    fireEvent.click(screen.getByRole('button', { name: /assign to cluster/i }));
    await waitFor(() => expect(screen.getByTestId('transfer-clusters')).toHaveTextContent(/^1$/));
    fireEvent.click(screen.getByText('Submit transfer'));
    expect(await screen.findByText(/Resolve terrain elevation for all AGL waypoints/i)).toBeInTheDocument();
    expect(uploadSwarmTrajectory.mock.calls).toHaveLength(uploadsBefore);
  });
});
