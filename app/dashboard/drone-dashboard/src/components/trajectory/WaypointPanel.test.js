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

    expect(screen.getByText('Derived waypoint arrival time:')).toBeInTheDocument();
    expect(screen.getByText('Derived required speed:')).toBeInTheDocument();
    expect(screen.getByText('Clearance AGL:')).toBeInTheDocument();
    expect(screen.getByText('120.0m')).toBeInTheDocument();
    expect(screen.getAllByText('Target AGL').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Speed-driven ETA').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Auto heading').length).toBeGreaterThan(0);
    expect(screen.getByText('Estimated terrain')).toBeInTheDocument();
    const operatorBrief = screen.getByLabelText(/waypoint 2 operator brief/i);
    expect(operatorBrief).toBeInTheDocument();
    expect(within(operatorBrief).getByText('Altitude Logic')).toBeInTheDocument();
    expect(within(operatorBrief).getByText('Timing Logic')).toBeInTheDocument();
    expect(within(operatorBrief).getByText('Heading Logic')).toBeInTheDocument();
  });

  it('keeps stored altitude read-only for AGL-authored waypoints and explains how to change it', () => {
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
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    const storedAltitudeRow = screen.getByText(/stored altitude \(msl\):/i).closest('.detail-row');
    fireEvent.click(within(storedAltitudeRow).getByText('320.0m'));

    expect(screen.queryByPlaceholderText(/altitude msl \(m\)/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/stored mission altitude is derived from target agl and current terrain/i)
    ).toBeInTheDocument();
  });

  it('keeps auto-arrival heading read-only until heading mode switches to manual', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      heading: 90,
      headingMode: YAW_CONSTANTS.AUTO,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    expect(screen.getByText('Derived arrival heading:')).toBeInTheDocument();

    const headingRow = screen.getByText('Derived arrival heading:').closest('.detail-row');
    fireEvent.click(within(headingRow).getByText('090°'));

    expect(screen.queryByPlaceholderText(/heading \(0-360°\)/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/arrival heading is derived from the inbound leg\. switch heading mode to manual/i)
    ).toBeInTheDocument();
  });

  it('keeps terrain confidence and AGL context visible when ground elevation is exactly sea level', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      altitude: 120,
      groundElevation: 0,
      targetAgl: 120,
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      terrainAccurate: true,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    expect(screen.getByText('Terrain:')).toBeInTheDocument();
    expect(screen.getByText('Verified terrain • 0.0m MSL')).toBeInTheDocument();
    expect(screen.getByText('Clearance AGL:')).toBeInTheDocument();
    expect(screen.getAllByText('120.0m').length).toBeGreaterThan(0);
    expect(screen.getByText('Verified terrain')).toBeInTheDocument();
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

    const altitudeInputRow = screen.getByText(/altitude input:/i).closest('.detail-row');
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

  it('labels summary timing as mission clock with separate route entry and motion values', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      timeFromStart: 42,
      estimatedSpeed: 8,
    };
    const firstWaypoint = {
      ...baseWaypoint,
      timeFromStart: 12,
    };

    renderPanel({
      waypoints: [firstWaypoint, secondWaypoint],
      selectedWaypointId: secondWaypoint.id,
    });

    expect(screen.getByText('Mission clock:')).toBeInTheDocument();
    const missionClockRow = screen.getByText('Mission clock:').closest('.summary-item');
    expect(within(missionClockRow).getByText('42.0s')).toBeInTheDocument();
    expect(screen.getByText('Route entry:')).toBeInTheDocument();
    const routeEntryRow = screen.getByText('Route entry:').closest('.summary-item');
    expect(within(routeEntryRow).getByText('12.0s')).toBeInTheDocument();
    expect(screen.getByText('Route motion:')).toBeInTheDocument();
    const routeMotionRow = screen.getByText('Route motion:').closest('.summary-item');
    expect(within(routeMotionRow).getByText('30.0s')).toBeInTheDocument();
    expect(
      screen.getByText(/derived timing and speed checks stay locked so the panel always shows what the planner is calculating/i)
    ).toBeInTheDocument();
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

    const positionRow = screen.getByText(/position:/i).closest('.detail-row');
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

  it('keeps non-selected waypoints in a compact review state until they are focused', () => {
    const secondWaypoint = {
      ...baseWaypoint,
      id: 'wp-2',
      name: 'Waypoint 2',
      latitude: 35.727,
      longitude: 51.2721,
      altitude: 120,
      timeFromStart: 24,
      estimatedSpeed: 8,
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 8,
    };

    renderPanel({
      waypoints: [baseWaypoint, secondWaypoint],
      selectedWaypointId: baseWaypoint.id,
    });

    expect(screen.getByText(/select this waypoint to review or edit the full authoring details/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/waypoint 2 operator brief/i)).not.toBeInTheDocument();
    expect(screen.getByText(/stored 120.0m msl/i)).toBeInTheDocument();
  });
});
