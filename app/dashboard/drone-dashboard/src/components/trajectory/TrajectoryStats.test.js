import React from 'react';
import { render, screen } from '@testing-library/react';

import TrajectoryStats from './TrajectoryStats';

describe('TrajectoryStats', () => {
  test('uses operator-facing timing and heading wording in the mission brief', () => {
    render(
      <TrajectoryStats
        stats={{
          totalDistance: 1450,
          totalTime: 95,
          maxSpeed: 11.2,
          speedWarnings: 1,
          maxAltitude: 1450,
          minAltitude: 1320,
          maxAgl: 120,
          minAgl: 40,
          maxSpeedStatus: 'marginal',
          timingModeCounts: { auto_speed: 2, manual_time: 3 },
          altitudeReferenceCounts: { msl: 4, agl: 1 },
          headingModeCounts: { auto: 3, manual: 2 },
          terrainCoverage: { accurate: 4, estimated: 1, unknown: 0 },
          speedStatusCounts: { feasible: 3, marginal: 1, impossible: 0, unknown: 0 },
        }}
      />
    );

    expect(screen.getByText('Speed-driven ETA 2 · Time-driven speed 3')).toBeInTheDocument();
    expect(screen.getByText('Auto heading 3 · Manual heading 2')).toBeInTheDocument();
    expect(screen.getByText('1320-1450 m MSL')).toBeInTheDocument();
  });
});
