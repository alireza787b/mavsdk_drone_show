import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WaypointModal from './WaypointModal';
import { getTerrainElevation } from '../../services/ElevationService';
import { ALTITUDE_REFERENCE, TIMING_MODES, suggestOptimalTime } from '../../utilities/SpeedCalculator';

jest.mock('../../services/ElevationService', () => ({
  getTerrainElevation: jest.fn(),
}));

const byTextContent = (text) => (_, element) =>
  element?.textContent?.replace(/\s+/g, ' ').trim() === text;

describe('WaypointModal', () => {
  beforeEach(() => {
    getTerrainElevation.mockResolvedValue({
      elevation: 200,
      source: 'mock-terrain',
      error: null,
    });
  });

  it('shows inline validation instead of submitting an underground altitude', async () => {
    const onConfirm = jest.fn();

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={{ latitude: 35.7262, longitude: 51.2721 }}
        previousWaypoint={{
          latitude: 35.726,
          longitude: 51.272,
          altitude: 350,
          timeFromStart: 10,
          estimatedSpeed: 8,
        }}
        waypointIndex={2}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(byTextContent('Ground elevation: 200.0m MSL'))).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText(/altitude \(msl\)/i), {
      target: { value: '150' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(await screen.findByText(/altitude must stay above ground/i)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('locks confirmation until terrain is resolved or intentionally estimated', async () => {
    const onConfirm = jest.fn();
    let resolveTerrain;
    getTerrainElevation.mockReturnValue(
      new Promise((resolve) => {
        resolveTerrain = resolve;
      })
    );

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={{ latitude: 35.7262, longitude: 51.2721 }}
        previousWaypoint={{
          latitude: 35.726,
          longitude: 51.272,
          altitude: 350,
          timeFromStart: 10,
          estimatedSpeed: 8,
        }}
        waypointIndex={2}
      />
    );

    expect(
      screen.getByText(/waypoint confirmation stays locked until terrain resolves or you choose use estimate/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /add waypoint/i })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /use estimate/i }));

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /add waypoint/i })).not.toBeDisabled();
    });

    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      terrainAccurate: false,
    }));

    resolveTerrain({
      elevation: 200,
      source: 'mock-terrain',
      error: null,
    });
  });

  it('derives waypoint arrival time from preferred leg speed in auto mode', async () => {
    const onConfirm = jest.fn();
    const position = { latitude: 35.727, longitude: 51.272 };
    const previousWaypoint = {
      latitude: 35.726,
      longitude: 51.272,
      altitude: 350,
      timeFromStart: 10,
      estimatedSpeed: 8,
    };

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={position}
        previousWaypoint={previousWaypoint}
        waypointIndex={2}
      />
    );

    await waitFor(() => {
      expect(screen.getByLabelText(/preferred leg speed/i)).toBeInTheDocument();
    });

    const timeInput = screen.getByLabelText(/derived waypoint arrival time/i);
    const expectedInitialTime = suggestOptimalTime(previousWaypoint, position, 8, previousWaypoint.altitude);
    expect(timeInput).toBeDisabled();
    expect(Number(timeInput.value)).toBe(expectedInitialTime);
    expect(screen.getByLabelText(/derived arrival heading/i)).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/preferred leg speed/i), {
      target: { value: '4' },
    });

    const expectedAdjustedTime = suggestOptimalTime(previousWaypoint, position, 4, previousWaypoint.altitude);
    await waitFor(() => {
      expect(Number(screen.getByLabelText(/waypoint arrival time/i).value)).toBe(expectedAdjustedTime);
    });
    const expectedRoundedAdjustedTime = Math.round(expectedAdjustedTime);

    expect(screen.getByText(/leg planning/i)).toBeInTheDocument();
    expect(screen.getAllByText(/speed-driven eta/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText(/operator sets preferred inbound-leg speed 4\.0 m\/s\./i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(/arrival stays derived in this mode\. switch to time-driven speed to pin the mission clock yourself\./i)
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        new RegExp(
          `planner derives arrival at ${expectedRoundedAdjustedTime}s and verifies the leg at 4\\.0 m\\/s\\.`,
          'i'
        )
      )
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 4,
      timeFromStart: expectedAdjustedTime,
    }));
  });

  it('allows manual arrival-time planning when selected', async () => {
    const onConfirm = jest.fn();

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={{ latitude: 35.727, longitude: 51.272 }}
        previousWaypoint={{
          latitude: 35.726,
          longitude: 51.272,
          altitude: 350,
          timeFromStart: 10,
          estimatedSpeed: 8,
        }}
        waypointIndex={2}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole('radio', { name: /time-driven speed/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('radio', { name: /time-driven speed/i }));

    const timeInput = screen.getByLabelText(/waypoint arrival time/i);
    expect(timeInput).not.toBeDisabled();
    expect(
      screen.getByText(/required inbound-leg speed updates live from the arrival time you pin here\./i)
    ).toBeInTheDocument();

    fireEvent.change(timeInput, { target: { value: '44' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      timingMode: TIMING_MODES.MANUAL_TIME,
      timeFromStart: 44,
    }));
  });

  it('blocks non-increasing manual arrival times at the modal boundary', async () => {
    const onConfirm = jest.fn();

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={{ latitude: 35.727, longitude: 51.272 }}
        previousWaypoint={{
          latitude: 35.726,
          longitude: 51.272,
          altitude: 350,
          timeFromStart: 10,
          estimatedSpeed: 8,
        }}
        waypointIndex={2}
      />
    );

    await waitFor(() => {
      expect(screen.getByRole('radio', { name: /time-driven speed/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('radio', { name: /time-driven speed/i }));
    fireEvent.change(screen.getByLabelText(/waypoint arrival time/i), {
      target: { value: '10' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(
      await screen.findByText(/waypoint arrival time must be later than the previous waypoint/i)
    ).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('can author altitude from target AGL while still storing MSL mission altitude', async () => {
    const onConfirm = jest.fn();

    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={onConfirm}
        position={{ latitude: 35.727, longitude: 51.272 }}
        previousWaypoint={null}
        waypointIndex={1}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(byTextContent('Ground elevation: 200.0m MSL'))).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('radio', { name: /target agl/i }));
    fireEvent.change(screen.getByRole('spinbutton', { name: /target clearance \(agl\)|target height \(agl\)/i }), {
      target: { value: '120' },
    });

    expect(screen.getByText(byTextContent('Mission stores altitude as 320.0m MSL'))).toBeInTheDocument();
    expect(screen.queryByText(/estimated terrain/i)).not.toBeInTheDocument();
    expect(screen.getAllByText(/verified terrain/i).length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 120,
      altitude: 320,
    }));
  });

  it('keeps MSL input operator-owned when terrain resolves and offers an explicit safe correction', async () => {
    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={jest.fn()}
        position={{ latitude: 35.727, longitude: 51.272 }}
        previousWaypoint={null}
        waypointIndex={1}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(byTextContent('Ground elevation: 200.0m MSL'))).toBeInTheDocument();
    });

    const altitudeInput = screen.getByLabelText(/altitude \(msl\)/i);
    expect(altitudeInput).toHaveValue(100);
    expect(
      screen.getByText(/stored altitude is below terrain here/i)
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /use 300\.0m msl/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /use 300\.0m msl/i }));

    expect(screen.getByLabelText(/altitude \(msl\)/i)).toHaveValue(300);
    expect(screen.getByText(byTextContent('Mission stores altitude as 300.0m MSL'))).toBeInTheDocument();
  });

  it('explains that the first waypoint is the mission start anchor', async () => {
    render(
      <WaypointModal
        isOpen
        onClose={jest.fn()}
        onConfirm={jest.fn()}
        position={{ latitude: 35.727, longitude: 51.272 }}
        previousWaypoint={null}
        waypointIndex={1}
      />
    );

    await waitFor(() => {
      expect(screen.getByText(/mission start anchor/i)).toBeInTheDocument();
    });

    expect(
      screen.getAllByText(/this first waypoint anchors the route-entry delay after mission start/i).length
    ).toBeGreaterThan(0);
    expect(screen.queryByRole('radio', { name: /auto \(arrival leg\)/i })).not.toBeInTheDocument();
    expect(screen.getByText('Manual heading')).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: /entry heading/i })).not.toBeDisabled();
    expect(screen.getByLabelText(/route entry delay/i)).toHaveValue(10);
    expect(screen.getByText(/default route-entry delay starts at 10s/i)).toBeInTheDocument();
    expect(screen.getByText(/first waypoint: set the initial route-entry heading explicitly/i)).toBeInTheDocument();
  });
});
