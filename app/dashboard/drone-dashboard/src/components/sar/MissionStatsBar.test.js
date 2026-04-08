import React from 'react';
import { render, screen } from '@testing-library/react';

import MissionStatsBar from './MissionStatsBar';

describe('MissionStatsBar', () => {
  it('shows operator phase and guidance', () => {
    render(
      <MissionStatsBar
        missionStatus={{
          state: 'paused',
          operation_phase: 'holding',
          total_coverage_percent: 42.5,
          elapsed_time_s: 185,
          drone_states: {
            '1': { hw_id: '1' },
            '2': { hw_id: '2' },
          },
          status_summary: 'Assigned drones are holding on operator command.',
          recommended_operator_action: 'Generate a follow-up package from current state.',
        }}
      />
    );

    expect(screen.getByText('Holding')).toBeInTheDocument();
    expect(screen.getByText(/Assigned drones are holding on operator command/i)).toBeInTheDocument();
    expect(screen.getByText(/Generate a follow-up package from current state/i)).toBeInTheDocument();
  });
});
