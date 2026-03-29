import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectoryTransferDialog from './SwarmTrajectoryTransferDialog';

describe('SwarmTrajectoryTransferDialog', () => {
  test('summarizes timing and heading intent without duplicating posture in the summary grid', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectoryTransferDialog
          isOpen
          onClose={jest.fn()}
          onSubmit={jest.fn()}
          clusters={[
            {
              leader_id: 1,
              follower_ids: [2, 3],
              follower_count: 2,
              expected_drone_count: 3,
              processed_drone_count: 0,
              ready: false,
              state: 'needs_processing',
              leader_uploaded: true,
              issues: [],
              advisories: [],
            },
          ]}
          loading={false}
          submitting={false}
          selectedLeaderId={1}
          onSelectLeaderId={jest.fn()}
          error=""
          successMessage=""
          onOpenSwarmTrajectory={jest.fn()}
          onOpenSwarmDesign={jest.fn()}
          trajectoryName="Demo Path"
          waypointCount={3}
          totalDistance={1200}
          totalTime={90}
          stats={{
            routeEntryDelaySeconds: 12,
            routeMotionTime: 78,
            altitudeReferenceCounts: { msl: 2, agl: 1 },
            timingModeCounts: { auto_speed: 1, manual_time: 2 },
            headingModeCounts: { auto: 2, manual: 1 },
            authoringBreakdown: {
              routeEntryAnchors: 1,
              speedDrivenLegs: 1,
              timeDrivenLegs: 1,
              entryHeadings: 1,
              autoArrivalHeadings: 2,
              manualArrivalHeadings: 0,
            },
            terrainCoverage: { accurate: 2, estimated: 1, unknown: 0 },
          }}
          missionReadiness={{
            posture: {
              tone: 'warning',
              label: 'Review required',
              summary: 'Operator review is still required before processing and mission launch.',
              transferLabel: 'Assign for Review',
            },
            blockers: [],
            advisories: [],
            notes: [],
          }}
        />
      </MemoryRouter>
    );

    expect(screen.getByText('Timing Plan')).toBeInTheDocument();
    expect(screen.getByText('Mission Clock')).toBeInTheDocument();
    expect(screen.getByText('Route Motion')).toBeInTheDocument();
    expect(screen.getByText('1m 18s')).toBeInTheDocument();
    expect(screen.getByText('Entry +12s · Speed-driven ETA 1 · Time-driven speed 1')).toBeInTheDocument();
    expect(screen.getByText('Heading Plan')).toBeInTheDocument();
    expect(screen.getByText('Entry heading 1 · Auto arrival 2 · Manual arrival 0')).toBeInTheDocument();
    expect(screen.getByText(/mission still stores and executes canonical msl altitude/i)).toBeInTheDocument();
    expect(screen.getByText(/Waypoint 1 sets route-entry delay and heading/i)).toBeInTheDocument();
    expect(screen.queryByText('Transfer Posture')).not.toBeInTheDocument();
    expect(screen.getByText('Review required')).toBeInTheDocument();
  });
});
