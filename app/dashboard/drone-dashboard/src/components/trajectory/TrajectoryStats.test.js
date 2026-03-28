import React from 'react';
import { render, screen } from '@testing-library/react';

import TrajectoryStats from './TrajectoryStats';

describe('TrajectoryStats', () => {
  test('renders the mission brief with operator-facing timing, terrain, and speed context', () => {
    render(
      <TrajectoryStats
        stats={{
          totalDistance: 1425,
          totalTime: 186,
          maxSpeed: 14.6,
          speedWarnings: 1,
          maxAltitude: 220,
          minAltitude: 110,
          maxAgl: 160,
          minAgl: 35,
          maxSpeedStatus: 'marginal',
          timingModeCounts: {
            auto_speed: 3,
            manual_time: 2,
          },
          altitudeReferenceCounts: {
            msl: 2,
            agl: 3,
          },
          headingModeCounts: {
            auto: 4,
            manual: 1,
          },
          terrainCoverage: {
            accurate: 3,
            estimated: 2,
            unknown: 0,
          },
          speedStatusCounts: {
            feasible: 3,
            marginal: 1,
            impossible: 0,
            unknown: 0,
          },
        }}
      />
    );

    expect(screen.getByLabelText('Trajectory mission brief')).toBeInTheDocument();
    expect(screen.getByText('1.43 km')).toBeInTheDocument();
    expect(screen.getByText('3m 6s')).toBeInTheDocument();
    expect(screen.getByText('110-220 m MSL')).toBeInTheDocument();
    expect(screen.getByText('35-160 m AGL')).toBeInTheDocument();
    expect(screen.getByText('MSL 2 · AGL 3')).toBeInTheDocument();
    expect(screen.getByText('Accurate 3 · Estimated 2')).toBeInTheDocument();
    expect(screen.getByText('1 leg requires elevated speed review.')).toBeInTheDocument();
    expect(screen.getByText('AGL entries are stored as MSL after applying the current ground estimate.')).toBeInTheDocument();
  });
});
