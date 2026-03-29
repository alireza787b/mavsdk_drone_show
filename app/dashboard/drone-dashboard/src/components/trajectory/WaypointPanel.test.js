import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import WaypointPanel from './WaypointPanel';
import { ALTITUDE_REFERENCE, TIMING_MODES, YAW_CONSTANTS } from '../../utilities/SpeedCalculator';

const baseWaypoint = {
  id: 'wp-1',
  name: 'Waypoint 1',
  latitude: 35.7262,
  longitude: 51.2721,
  altitude: 100,
  timeFromStart: 0,
  estimatedSpeed: 0,
  speedFeasible: true,
  heading: 0,
  headingMode: YAW_CONSTANTS.AUTO,
};

const renderPanel = (overrides = {}) => {
  const props = {
    waypoints: [baseWaypoint],
    selectedWaypointId: baseWaypoint.id,
    onSelectWaypoint: jest.fn(),
    onUpdateWaypoint: jest.fn(),
    onDeleteWaypoint: jest.fn(),
    onMoveWaypoint: jest.fn(),
    onFlyTo: jest.fn(),
    ...overrides,
  };

  return {
    ...render(<WaypointPanel {...props} />),
    props,
  };
};

describe('WaypointPanel', () => {
  it('shows inline validation when altitude edits are out of range', () => {
    const { props } = renderPanel();

    fireEvent.click(screen.getByText('100.0m'));
    fireEvent.change(screen.getByPlaceholderText('Altitude MSL (m)'), {
      target: { value: '0' },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(screen.getByText(/altitude must stay between 1 m and 10,000 m msl/i)).toBeInTheDocument();
    expect(props.onUpdateWaypoint).not.toHaveBeenCalled();
  });

  it('updates preferred leg speed for auto-planned segments and derives waypoint arrival time', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      latitude: 35.727,
      longitude: 51.2721,
      altitude: 100,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    const { props } = renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    const legSpeedRow = screen.getByText(/preferred leg speed:/i).closest('.detail-row');
    fireEvent.click(within(legSpeedRow).getByText('8.0m/s'));
    fireEvent.change(screen.getByPlaceholderText(/preferred speed \(m\/s\)/i), {
      target: { value: '4' },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(props.onUpdateWaypoint).toHaveBeenCalledWith('wp-2', expect.objectContaining({
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 4,
      timeFromStart: 23,
    }));
  });

  it('can switch a segment from auto speed planning to manual arrival time', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      latitude: 35.727,
      longitude: 51.2721,
      altitude: 100,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    const { props } = renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    const segmentPlanRow = screen.getByText(/timing mode:/i).closest('.detail-row');
    fireEvent.click(within(segmentPlanRow).getByText(/speed-driven eta/i));
    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: TIMING_MODES.MANUAL_TIME },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(props.onUpdateWaypoint).toHaveBeenCalledWith('wp-2', expect.objectContaining({
      timingMode: TIMING_MODES.MANUAL_TIME,
    }));
  });

  it('shows stored altitude reference and derived AGL context when terrain data exists', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      altitude: 320,
      groundElevation: 200,
      targetAgl: 120,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      terrainAccurate: false,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    expect(screen.getByText('Clearance AGL:')).toBeInTheDocument();
    expect(screen.getByText('120.0m')).toBeInTheDocument();
    expect(screen.getAllByText('Target AGL').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Speed-driven ETA').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Auto heading').length).toBeGreaterThan(0);
    expect(screen.getByText('Terrain estimated')).toBeInTheDocument();
  });

  it('can switch a terrain-backed waypoint from MSL input to Target AGL', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      altitude: 320,
      groundElevation: 200,
      altitudeReference: ALTITUDE_REFERENCE.MSL,
      timeFromStart: 24,
      estimatedSpeed: 8,
    };

    const { props } = renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    const altitudeInputRow = screen.getAllByText(/altitude input:/i)[1].closest('.detail-row');
    fireEvent.click(within(altitudeInputRow).getByText(/msl input/i));
    fireEvent.change(screen.getByRole('combobox'), {
      target: { value: ALTITUDE_REFERENCE.AGL },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(props.onUpdateWaypoint).toHaveBeenCalledWith('wp-2', expect.objectContaining({
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 120,
    }));
  });

  it('updates stored altitude when an AGL-authored waypoint clearance is edited', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      altitude: 320,
      groundElevation: 200,
      targetAgl: 120,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      timeFromStart: 24,
      estimatedSpeed: 8,
    };

    const { props } = renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    const clearanceRow = screen.getByText(/clearance agl:/i).closest('.detail-row');
    fireEvent.click(within(clearanceRow).getByText('120.0m'));
    fireEvent.change(screen.getByPlaceholderText(/target clearance agl \(m\)/i), {
      target: { value: '140' },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(props.onUpdateWaypoint).toHaveBeenCalledWith('wp-2', expect.objectContaining({
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 140,
      altitude: 340,
    }));
  });

  it('marks the first waypoint as the mission start anchor', () => {
    renderPanel();

    expect(screen.getByText('Route Role:')).toBeInTheDocument();
    expect(screen.getAllByText('Mission start anchor').length).toBeGreaterThan(0);
    expect(screen.getByText('Route entry delay:')).toBeInTheDocument();
    expect(screen.getByText('Entry heading:')).toBeInTheDocument();
    expect(screen.getByText(/manual heading/i)).toBeInTheDocument();
  });

  it('shows terrain-refresh feedback while saving coordinate edits', async () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      latitude: 35.727,
      longitude: 51.2721,
      altitude: 320,
      groundElevation: 200,
      targetAgl: 120,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      timeFromStart: 24,
      estimatedSpeed: 8,
    };

    let resolveUpdate;
    const onUpdateWaypoint = jest.fn(() => new Promise((resolve) => {
      resolveUpdate = resolve;
    }));

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
      onUpdateWaypoint,
    });

    const positionRow = screen.getAllByText(/position:/i)[1].closest('.detail-row');
    fireEvent.click(within(positionRow).getByText(/35\.727000,\s*51\.272100/i));
    fireEvent.change(screen.getByPlaceholderText('Latitude'), {
      target: { value: '35.7300' },
    });
    fireEvent.click(screen.getByTitle('Save (Enter)'));

    expect(screen.getByText(/refreshing terrain and clearance at the new coordinates/i)).toBeInTheDocument();
    expect(onUpdateWaypoint).toHaveBeenCalledWith('wp-2', expect.objectContaining({
      latitude: 35.73,
      longitude: 51.2721,
    }));

    resolveUpdate();

    await waitFor(() => {
      expect(screen.queryByText(/refreshing terrain and clearance at the new coordinates/i)).not.toBeInTheDocument();
    });
  });
});
