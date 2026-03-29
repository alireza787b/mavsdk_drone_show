import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WaypointModal from './WaypointModal';
import { getTerrainElevation } from '../../services/ElevationService';
import { ALTITUDE_REFERENCE, TIMING_MODES } from '../../utilities/SpeedCalculator';

jest.mock('../../services/ElevationService', () => ({
  getTerrainElevation: jest.fn(),
}));

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
      expect(screen.getByText(/ground elevation:/i)).toBeInTheDocument();
      expect(screen.getAllByText(/200\.0m msl/i).length).toBeGreaterThan(0);
    });

    fireEvent.change(screen.getByLabelText(/altitude \(msl\)/i), {
      target: { value: '150' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(await screen.findByText(/altitude must stay above ground/i)).toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('derives arrival time from preferred leg speed in auto mode', async () => {
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
      expect(screen.getByLabelText(/target arrival speed/i)).toBeInTheDocument();
    });

    const timeInput = screen.getByLabelText(/time from start/i);
    expect(timeInput).toBeDisabled();
    expect(Number(timeInput.value)).toBe(24);

    fireEvent.change(screen.getByLabelText(/target arrival speed/i), {
      target: { value: '4' },
    });

    await waitFor(() => {
      expect(Number(screen.getByLabelText(/time from start/i).value)).toBe(38);
    });

    expect(screen.getAllByText(/segment plan/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/speed-driven eta/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/4\.0 m\/s target -> 38s arrival/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      timingMode: TIMING_MODES.AUTO_SPEED,
      preferredSpeed: 4,
      timeFromStart: 38,
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

    const timeInput = screen.getByLabelText(/time from start/i);
    expect(timeInput).not.toBeDisabled();

    fireEvent.change(timeInput, { target: { value: '44' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      timingMode: TIMING_MODES.MANUAL_TIME,
      timeFromStart: 44,
    }));
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
      expect(screen.getByText(/ground elevation:/i)).toBeInTheDocument();
      expect(screen.getAllByText(/200\.0m msl/i).length).toBeGreaterThan(0);
    });

    fireEvent.click(screen.getByRole('radio', { name: /target agl/i }));
    fireEvent.change(screen.getByRole('spinbutton', { name: /target clearance \(agl\)|target height \(agl\)/i }), {
      target: { value: '120' },
    });

    expect(screen.getByText(/stored as 320\.0m msl/i)).toBeInTheDocument();
    expect(screen.queryByText(/estimated terrain/i)).not.toBeInTheDocument();
    expect(screen.getByText(/accurate terrain/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      altitudeReference: ALTITUDE_REFERENCE.AGL,
      targetAgl: 120,
      altitude: 320,
    }));
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

    expect(screen.getByText(/this first waypoint anchors when the leader should reach the route after mission start/i)).toBeInTheDocument();
    expect(screen.queryByRole('radio', { name: /auto \(arrival leg\)/i })).not.toBeInTheDocument();
    expect(screen.getByText('Manual heading')).toBeInTheDocument();
    expect(screen.getByRole('spinbutton', { name: /heading/i })).not.toBeDisabled();
    expect(screen.getByText(/first waypoint: set the initial route-entry heading explicitly/i)).toBeInTheDocument();
  });
});
