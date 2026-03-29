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
          routeEntryDelaySeconds: 12,
          maxSpeedStatus: 'marginal',
          timingModeCounts: { auto_speed: 2, manual_time: 3 },
          altitudeReferenceCounts: { msl: 4, agl: 1 },
          headingModeCounts: { auto: 3, manual: 2 },
          authoringBreakdown: {
            routeEntryAnchors: 1,
            speedDrivenLegs: 2,
            timeDrivenLegs: 2,
            entryHeadings: 1,
            autoArrivalHeadings: 3,
            manualArrivalHeadings: 1,
          },
          terrainCoverage: { accurate: 4, estimated: 1, unknown: 0 },
          speedStatusCounts: { feasible: 3, marginal: 1, impossible: 0, unknown: 0 },
        }}
      />
    );

    expect(screen.getByText('Entry +12s · Speed-driven ETA 2 · Time-driven speed 2')).toBeInTheDocument();
    expect(screen.getByText('Entry heading 1 · Auto arrival 3 · Manual arrival 1')).toBeInTheDocument();
    expect(screen.getByText('1320-1450 m MSL')).toBeInTheDocument();
    expect(screen.getByText('Route Time')).toBeInTheDocument();
    expect(screen.getByText('Excludes climb and end behavior')).toBeInTheDocument();
  });
});
