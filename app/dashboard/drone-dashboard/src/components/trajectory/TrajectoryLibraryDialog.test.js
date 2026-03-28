import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';

import TrajectoryLibraryDialog from './TrajectoryLibraryDialog';

describe('TrajectoryLibraryDialog', () => {
  it('saves the current planner trajectory with the edited name', () => {
    const onSave = jest.fn();

    render(
      <TrajectoryLibraryDialog
        mode="save"
        isOpen
        onClose={jest.fn()}
        onSave={onSave}
        initialName="ridge-pass"
        currentWaypointCount={4}
        currentStats={{
          totalDistance: 1250,
          totalTime: 92,
          maxSpeed: 8.6,
        }}
      />
    );

    expect(screen.getByText('1.25 km')).toBeInTheDocument();
    expect(screen.getByText('1m 32s')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/enter trajectory name/i), {
      target: { value: 'coastal-search-alpha' },
    });
    fireEvent.click(screen.getByRole('button', { name: /save trajectory/i }));

    expect(onSave).toHaveBeenCalledWith('coastal-search-alpha');
  });

  it('shows saved trajectory metadata, prioritizes manual saves, and loads the selected route', () => {
    const onLoad = jest.fn();

    render(
      <TrajectoryLibraryDialog
        mode="load"
        isOpen
        onClose={jest.fn()}
        onLoad={onLoad}
        trajectories={[
          {
            id: 'autosave-1',
            name: '_autosave_2026-03-28',
            waypoints: [{}, {}],
            metadata: {
              isAutoSave: true,
              modifiedAt: 100,
              stats: {
                totalDistance: 400,
                totalTime: 40,
                maxSpeed: 6.2,
              },
            },
          },
          {
            id: 'manual-1',
            name: 'coastal-sweep',
            waypoints: [{}, {}, {}],
            metadata: {
              modifiedAt: 200,
              stats: {
                totalDistance: 1425,
                totalTime: 186,
                maxSpeed: 14.6,
              },
            },
          },
        ]}
      />
    );

    const items = screen.getAllByText(/load/i).map((button) => button.closest('.trajectory-library-dialog__item'));
    expect(within(items[0]).getByText('coastal-sweep')).toBeInTheDocument();
    expect(within(items[0]).getByText('1.43 km', { exact: false })).toBeInTheDocument();
    expect(within(items[0]).getByText(/max 14\.6 m\/s/i)).toBeInTheDocument();

    expect(screen.getByText('Autosave')).toBeInTheDocument();

    fireEvent.click(within(items[0]).getByRole('button', { name: /load/i }));

    expect(onLoad).toHaveBeenCalledWith('manual-1');
  });
});
