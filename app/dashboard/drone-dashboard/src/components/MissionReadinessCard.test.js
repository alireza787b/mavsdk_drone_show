import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import MissionReadinessCard from './MissionReadinessCard';
import { getSwarmClusterStatus } from '../services/droneApiService';

jest.mock('../services/droneApiService', () => ({
  getSwarmClusterStatus: jest.fn(),
}));

describe('MissionReadinessCard', () => {
  test('renders truthful backend cluster readiness instead of heuristic guesses', async () => {
    getSwarmClusterStatus.mockResolvedValue({
      clusters: [
        {
          leader_id: 1,
          follower_ids: [2, 3],
          follower_count: 2,
          expected_drone_count: 3,
          processed_drone_count: 3,
          ready: true,
          has_trajectory: true,
          state: 'ready',
          leader_uploaded: true,
          leader_plot_available: true,
          cluster_plot_available: true,
          issues: [],
          advisories: [],
          missing_follower_ids: [],
          processed_follower_ids: [2, 3],
        },
        {
          leader_id: 5,
          follower_ids: [6],
          follower_count: 1,
          expected_drone_count: 2,
          processed_drone_count: 1,
          ready: false,
          has_trajectory: false,
          state: 'partial_outputs',
          leader_uploaded: true,
          leader_processed: true,
          leader_plot_available: false,
          cluster_plot_available: false,
          issues: ['One or more follower trajectories are missing from processed outputs.'],
          advisories: [],
          missing_follower_ids: [6],
          processed_follower_ids: [],
        },
      ],
      total_leaders: 2,
      total_followers: 3,
      processed_trajectories: 3,
      cluster_summary: {
        cluster_count: 2,
        ready_cluster_count: 1,
        needs_processing_cluster_count: 0,
        missing_upload_cluster_count: 0,
        partial_output_cluster_count: 1,
        overall_state: 'partial',
      },
    });

    const { container } = render(<MissionReadinessCard />);

    await waitFor(() => {
      const overallStatus = container.querySelector('.overall-status');
      expect(overallStatus).not.toBeNull();
      expect(overallStatus.textContent).toContain('50% Clusters Ready');
    });

    await waitFor(() => {
      const indicators = container.querySelectorAll('.csv-indicator');
      expect(indicators.length).toBeGreaterThan(1);
      expect(indicators[1].textContent).toContain('Partial Outputs');
    });

    expect(screen.getByText(/0 missing upload/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Leader 5'));

    expect(screen.getByText(/Cluster outputs incomplete/i)).toBeInTheDocument();
    expect(screen.getByText(/Follower IDs: 6/)).toBeInTheDocument();
    expect(screen.getByText(/Missing outputs: 6/)).toBeInTheDocument();
  });
});
