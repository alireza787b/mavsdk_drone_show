import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

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
            arrivalTimeFromStart: 18,
            timingMode: 'auto_speed',
            preferredSpeed: 8,
            headingMode: 'auto',
            calculatedHeading: 34,
            toAltitude: 1285,
            toAltitudeReference: 'msl',
            toTargetAgl: 25,
            toGroundElevation: 1260,
            terrainAccurate: true,
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
            arrivalTimeFromStart: 38,
            timingMode: 'manual_time',
            preferredSpeed: 12,
            headingMode: 'manual',
            heading: 92,
            toAltitude: 1302,
            toAltitudeReference: 'agl',
            toTargetAgl: 24,
            toGroundElevation: 1278,
            terrainAccurate: false,
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
    expect(screen.getByText('38s → 23.0 m/s')).toBeInTheDocument();
    expect(screen.getByText('Manual 92°')).toBeInTheDocument();
    expect(screen.getByText('24.0m AGL → 1302.0m MSL')).toBeInTheDocument();
    expect(screen.getByText('Estimated terrain')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /show all 2 legs/i })).toBeInTheDocument();
  });

  it('lets the operator jump from a flagged leg into the referenced arrival waypoint', () => {
    const onSelectSegment = jest.fn();

    render(
      <TrajectorySegmentReview
        segments={[
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
            arrivalTimeFromStart: 38,
            timingMode: 'manual_time',
            headingMode: 'manual',
            heading: 92,
            toAltitude: 1302,
            toAltitudeReference: 'agl',
            toTargetAgl: 24,
            toGroundElevation: 1278,
            terrainAccurate: false,
          },
        ]}
        onSelectSegment={onSelectSegment}
        activeSegmentId="wp-2->wp-3"
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /leg 2 → 3/i }));
    expect(onSelectSegment).toHaveBeenCalledWith(
      expect.objectContaining({ id: 'wp-2->wp-3', toWaypointName: 'Waypoint 3' })
    );
  });

  it('can expand from condensed nominal review into a full-route audit', () => {
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
            arrivalTimeFromStart: 18,
            timingMode: 'auto_speed',
            preferredSpeed: 8,
            headingMode: 'auto',
            calculatedHeading: 34,
            toAltitude: 1285,
            toAltitudeReference: 'msl',
            toTargetAgl: 25,
            toGroundElevation: 1260,
            terrainAccurate: true,
          },
          {
            id: 'wp-2->wp-3',
            fromIndex: 2,
            toIndex: 3,
            fromWaypointName: 'Waypoint 2',
            toWaypointName: 'Waypoint 3',
            speed: 8,
            speedStatus: 'feasible',
            distanceMeters: 150,
            durationSeconds: 18,
            arrivalTimeFromStart: 36,
            timingMode: 'auto_speed',
            preferredSpeed: 8,
            headingMode: 'auto',
            calculatedHeading: 40,
            toAltitude: 1286,
            toAltitudeReference: 'msl',
            toTargetAgl: 26,
            toGroundElevation: 1260,
            terrainAccurate: true,
          },
          {
            id: 'wp-3->wp-4',
            fromIndex: 3,
            toIndex: 4,
            fromWaypointName: 'Waypoint 3',
            toWaypointName: 'Waypoint 4',
            speed: 8,
            speedStatus: 'feasible',
            distanceMeters: 160,
            durationSeconds: 20,
            arrivalTimeFromStart: 56,
            timingMode: 'auto_speed',
            preferredSpeed: 8,
            headingMode: 'auto',
            calculatedHeading: 44,
            toAltitude: 1288,
            toAltitudeReference: 'msl',
            toTargetAgl: 28,
            toGroundElevation: 1260,
            terrainAccurate: true,
          },
          {
            id: 'wp-4->wp-5',
            fromIndex: 4,
            toIndex: 5,
            fromWaypointName: 'Waypoint 4',
            toWaypointName: 'Waypoint 5',
            speed: 8,
            speedStatus: 'feasible',
            distanceMeters: 170,
            durationSeconds: 20,
            arrivalTimeFromStart: 76,
            timingMode: 'auto_speed',
            preferredSpeed: 8,
            headingMode: 'auto',
            calculatedHeading: 48,
            toAltitude: 1290,
            toAltitudeReference: 'msl',
            toTargetAgl: 30,
            toGroundElevation: 1260,
            terrainAccurate: true,
          },
        ]}
      />
    );

    expect(screen.getByText(/showing the first 3 nominal legs/i)).toBeInTheDocument();
    expect(screen.queryByText('Leg 4 → 5')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /show all 4 legs/i }));
    expect(screen.getByText('Leg 4 → 5')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /show condensed view/i })).toBeInTheDocument();
  });

  it('shows an empty-state briefing when fewer than two waypoints exist', () => {
    render(<TrajectorySegmentReview segments={[]} />);

    expect(screen.getByText('No route legs yet')).toBeInTheDocument();
    expect(
      screen.getByText(/add at least two waypoints to review leg distance, duration, required speed, and operator intent/i)
    ).toBeInTheDocument();
  });
});
