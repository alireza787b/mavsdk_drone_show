import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WaypointModal from './WaypointModal';
import { getTerrainElevation } from '../../services/ElevationService';
import { TIMING_MODES } from '../../utilities/SpeedCalculator';

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
      expect(screen.getByText(/200\.0m msl/i)).toBeInTheDocument();
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
      expect(screen.getByLabelText(/preferred leg speed/i)).toBeInTheDocument();
    });

    const timeInput = screen.getByLabelText(/time from start/i);
    expect(timeInput).toBeDisabled();
    expect(Number(timeInput.value)).toBe(24);

    fireEvent.change(screen.getByLabelText(/preferred leg speed/i), {
      target: { value: '4' },
    });

    await waitFor(() => {
      expect(Number(screen.getByLabelText(/time from start/i).value)).toBe(38);
    });

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
      expect(screen.getByRole('radio', { name: /manual arrival time/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('radio', { name: /manual arrival time/i }));

    const timeInput = screen.getByLabelText(/time from start/i);
    expect(timeInput).not.toBeDisabled();

    fireEvent.change(timeInput, { target: { value: '44' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
      timingMode: TIMING_MODES.MANUAL_TIME,
      timeFromStart: 44,
    }));
  });
});
