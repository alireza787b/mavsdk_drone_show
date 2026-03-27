import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

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
          ready: true,
          has_trajectory: true,
          leader_uploaded: true,
          leader_plot_available: true,
          cluster_plot_available: true,
          missing_follower_ids: [],
          processed_follower_ids: [2, 3],
        },
        {
          leader_id: 5,
          follower_ids: [6],
          follower_count: 1,
          ready: false,
          has_trajectory: false,
          leader_uploaded: true,
          leader_plot_available: false,
          cluster_plot_available: false,
          missing_follower_ids: [6],
          processed_follower_ids: [],
        },
      ],
      total_leaders: 2,
      total_followers: 3,
      processed_trajectories: 3,
    });

    const { container } = render(<MissionReadinessCard />);

    expect(container.querySelector('.overall-status')?.textContent).toContain('50% Clusters Ready');
    expect(container.querySelectorAll('.csv-indicator')[1]?.textContent).toContain('Needs Processing');
    expect(screen.getByText(/0 missing upload/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText('Leader 5'));

    expect(screen.getByText(/Uploaded, processing required/i)).toBeInTheDocument();
    expect(screen.getByText(/Follower IDs: 6/)).toBeInTheDocument();
  });
});
