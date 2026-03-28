import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import MissionReadinessCard from './MissionReadinessCard';
import { getSwarmClusterStatus } from '../services/droneApiService';

jest.mock('../services/droneApiService', () => ({
  getSwarmClusterStatus: jest.fn(),
}));

describe('MissionReadinessCard', () => {
  test('shows processed package summary and operator next actions for Swarm Trajectory launch', async () => {
    getSwarmClusterStatus.mockResolvedValue({
      clusters: [
        {
          leader_id: 1,
          follower_count: 2,
          follower_ids: [2, 3],
          expected_drone_count: 3,
          processed_drone_count: 3,
          ready: true,
          leader_uploaded: true,
          state: 'ready',
          cluster_plot_available: false,
          leader_plot_available: false,
          issues: [],
          advisories: [],
        },
        {
          leader_id: 4,
          follower_count: 1,
          follower_ids: [5],
          expected_drone_count: 2,
          processed_drone_count: 1,
          ready: false,
          leader_uploaded: true,
          state: 'partial_outputs',
          cluster_plot_available: false,
          leader_plot_available: false,
          issues: ['Follower 5 output missing'],
          advisories: [],
          missing_follower_ids: [5],
          processed_follower_ids: [],
        },
      ],
      cluster_summary: {
        cluster_count: 2,
        ready_cluster_count: 1,
        needs_processing_cluster_count: 0,
        missing_upload_cluster_count: 0,
        partial_output_cluster_count: 1,
        overall_state: 'partial',
      },
      processed_drones: [1, 2, 3, 4],
      session: {
        exists: true,
        session_id: '20260328_173515',
        processed_leaders: [1, 4],
        total_drones: 5,
      },
    });

    render(
      <MemoryRouter>
        <MissionReadinessCard refreshTrigger={0} />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Swarm Mission Readiness')).toBeInTheDocument();
    });

    expect(screen.getByText('50% Clusters Ready')).toBeInTheDocument();
    expect(screen.getByText('Ready Clusters')).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText('Processed Drones')).toBeInTheDocument();
    expect(screen.getByText('4/5')).toBeInTheDocument();
    expect(screen.getByText('Active Session')).toBeInTheDocument();
    expect(screen.getByText('20260328_173515')).toBeInTheDocument();
    expect(screen.getByText('1 cluster still needs follower regeneration or output review.')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Trajectory Planning' })).toHaveAttribute('href', '/trajectory-planning');
    expect(screen.getByRole('link', { name: 'Swarm Trajectory' })).toHaveAttribute('href', '/swarm-trajectory');
  });
});
