import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WaypointModal from './WaypointModal';
import { getTerrainElevation } from '../../services/ElevationService';

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
});
