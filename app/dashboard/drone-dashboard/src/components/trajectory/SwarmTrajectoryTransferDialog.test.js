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
            altitudeReferenceCounts: { msl: 2, agl: 1 },
            timingModeCounts: { auto_speed: 1, manual_time: 2 },
            headingModeCounts: { auto: 2, manual: 1 },
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
    expect(screen.getByText('Speed-driven ETA 1 · Time-driven speed 2')).toBeInTheDocument();
    expect(screen.getByText('Heading Plan')).toBeInTheDocument();
    expect(screen.getByText('Auto heading 2 · Manual heading 1')).toBeInTheDocument();
    expect(screen.queryByText('Transfer Posture')).not.toBeInTheDocument();
    expect(screen.getByText('Review required')).toBeInTheDocument();
  });
});
