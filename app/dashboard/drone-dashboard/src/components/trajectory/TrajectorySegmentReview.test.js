import React from 'react';
import { render, screen } from '@testing-library/react';

import TrajectorySegmentReview from './TrajectorySegmentReview';

describe('TrajectorySegmentReview', () => {
  it('shows flagged legs first with operator-readable pacing context', () => {
    render(
      <TrajectorySegmentReview
        segments={[
          {
            id: 'wp-1->wp-2',
            fromIndex: 1,
            toIndex: 2,
            fromWaypointName: 'Waypoint 1',
            toWaypointName: 'Waypoint 2',
            speed: 8,
            speedStatus: 'feasible',
            distanceMeters: 140,
            durationSeconds: 18,
            timingMode: 'auto_speed',
            headingMode: 'auto',
          },
          {
            id: 'wp-2->wp-3',
            fromIndex: 2,
            toIndex: 3,
            fromWaypointName: 'Waypoint 2',
            toWaypointName: 'Waypoint 3',
            speed: 23,
            speedStatus: 'impossible',
            distanceMeters: 480,
            durationSeconds: 20,
            timingMode: 'manual_time',
            headingMode: 'manual',
          },
        ]}
      />
    );

    expect(screen.getByText('Leg Review')).toBeInTheDocument();
    expect(screen.getByText('Unsafe 1')).toBeInTheDocument();
    expect(screen.getByText('Review 0')).toBeInTheDocument();
    expect(screen.getByText('Nominal 1')).toBeInTheDocument();
    expect(screen.getByText(/showing attention legs only/i)).toBeInTheDocument();
    expect(screen.getByText('Leg 2 → 3')).toBeInTheDocument();
    expect(screen.getByText('480 m')).toBeInTheDocument();
    expect(screen.getByText('20s')).toBeInTheDocument();
    expect(screen.getByText('23.0 m/s')).toBeInTheDocument();
    expect(screen.getByText('Time-driven speed')).toBeInTheDocument();
    expect(screen.getByText('Manual heading')).toBeInTheDocument();
  });

  it('shows an empty-state briefing when fewer than two waypoints exist', () => {
    render(<TrajectorySegmentReview segments={[]} />);

    expect(screen.getByText('No route legs yet')).toBeInTheDocument();
    expect(
      screen.getByText(/add at least two waypoints to review leg distance, duration, required speed, and operator intent/i)
    ).toBeInTheDocument();
  });
});
