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
      package_stats: {
        available: true,
        drone_count: 4,
        route_entry_time_s: 10,
        mission_clock_s: 72,
        route_motion_time_s: 62,
        max_altitude_msl_m: 1465,
        min_altitude_msl_m: 1450,
        altitude_window_m: 15,
      },
      session: {
        exists: true,
        session_id: '20260328_173515',
        processed_leaders: [1, 4],
        total_drones: 5,
      },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
    expect(screen.getAllByText('20260328_173515')).toHaveLength(2);
    expect(screen.getByText('1 cluster still needs follower regeneration or output review.')).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => (
        element?.classList?.contains('readiness-session-note')
        && element.textContent.includes('Package timing:')
      )),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => (
        element?.tagName === 'STRONG'
        && element.textContent === '72.0s mission clock • entry 10.0s • motion 62.0s'
      )),
    ).toBeInTheDocument();
    expect(
      screen.getByText((_, element) => (
        element?.classList?.contains('readiness-session-note')
        && element.textContent.includes('Altitude envelope:')
      )),
    ).toBeInTheDocument();
    expect(screen.getByText('1450.0-1465.0 m MSL • window 15.0 m')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Trajectory Planning' })).toHaveAttribute('href', '/trajectory-planning');
    expect(screen.getByRole('link', { name: 'Swarm Trajectory' })).toHaveAttribute('href', '/swarm-trajectory');
  });
});
