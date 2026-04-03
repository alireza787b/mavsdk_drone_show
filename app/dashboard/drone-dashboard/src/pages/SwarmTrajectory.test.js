import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectory from './SwarmTrajectory';
import useFetch from '../hooks/useFetch';
import {
  buildSwarmTrajectoryPlotUrl,
  clearAllSwarmTrajectories,
  clearSwarmTrajectoryDrone,
  clearSwarmTrajectoryLeader,
  clearProcessedData,
  commitSwarmTrajectoryOutputs,
  downloadSwarmClusterKml,
  downloadSwarmTrajectoryCsv,
  downloadSwarmTrajectoryKml,
  getSwarmLeaders,
  getSwarmTrajectoryStatus,
  processTrajectories,
  removeSwarmTrajectoryUpload,
  uploadSwarmTrajectory,
} from '../services/droneApiService';

jest.mock('../hooks/useFetch');
jest.mock('../services/droneApiService', () => ({
  buildSwarmTrajectoryPlotUrl: jest.fn((filename) => `http://plots.test/${filename}`),
  clearAllSwarmTrajectories: jest.fn(),
  clearSwarmTrajectoryDrone: jest.fn(),
  clearSwarmTrajectoryLeader: jest.fn(),
  clearProcessedData: jest.fn(),
  commitSwarmTrajectoryOutputs: jest.fn(),
  downloadSwarmClusterKml: jest.fn(),
  downloadSwarmTrajectoryCsv: jest.fn(),
  downloadSwarmTrajectoryKml: jest.fn(),
  getSwarmLeaders: jest.fn(),
  getSwarmTrajectoryStatus: jest.fn(),
  processTrajectories: jest.fn(),
  removeSwarmTrajectoryUpload: jest.fn(),
  uploadSwarmTrajectory: jest.fn(),
}));

describe('SwarmTrajectory git writeback messaging', () => {
  const readyStatus = {
    success: true,
    status: {
      has_results: true,
      processed_trajectories: 3,
      processed_drones: [1, 2, 3],
      processed_leaders: [1],
      leader_count: 1,
      follower_count: 2,
      uploaded_leaders: [1],
      clusters: [
        {
          leader_id: 1,
          follower_ids: [2, 3],
          follower_count: 2,
          expected_drone_count: 3,
          processed_drone_count: 3,
          ready: true,
          state: 'ready',
          leader_uploaded: true,
          leader_processed: true,
          issues: [],
          advisories: [],
          cluster_plot_available: true,
          leader_plot_available: true,
        },
      ],
      cluster_summary: {
        cluster_count: 1,
        ready_cluster_count: 1,
        needs_processing_cluster_count: 0,
        partial_output_cluster_count: 0,
        missing_upload_cluster_count: 0,
        processed_cluster_count: 1,
        overall_state: 'ready',
      },
      session: {
        exists: true,
        session_id: 's1',
        processed_leaders: [1],
        total_drones: 3,
      },
      processing_recommendation: {
        action: 'safe_incremental',
        message: 'Safe incremental processing is available.',
        details: [],
      },
    },
  };

  beforeEach(() => {
    jest.clearAllMocks();
    useFetch.mockReturnValue({
      data: { git_auto_push: false },
      error: null,
      loading: false,
    });
    getSwarmLeaders.mockResolvedValue({
      success: true,
      leaders: [1],
      hierarchies: { 1: 2 },
      follower_details: { 1: [2, 3] },
      simulation_mode: true,
    });
    getSwarmTrajectoryStatus.mockResolvedValue(readyStatus);
    buildSwarmTrajectoryPlotUrl.mockImplementation((filename) => `http://plots.test/${filename}`);
    clearAllSwarmTrajectories.mockResolvedValue({ success: true });
    clearSwarmTrajectoryDrone.mockResolvedValue({ success: true });
    clearSwarmTrajectoryLeader.mockResolvedValue({ success: true });
    clearProcessedData.mockResolvedValue({ success: true });
    commitSwarmTrajectoryOutputs.mockResolvedValue({ success: true });
    downloadSwarmClusterKml.mockResolvedValue(new Blob(['cluster']));
    downloadSwarmTrajectoryCsv.mockResolvedValue(new Blob(['csv']));
    downloadSwarmTrajectoryKml.mockResolvedValue(new Blob(['kml']));
    processTrajectories.mockResolvedValue({ success: true });
    removeSwarmTrajectoryUpload.mockResolvedValue({ success: true });
    uploadSwarmTrajectory.mockResolvedValue({ success: true });
  });

  test('labels commit step as local-only when GCS auto-push is disabled', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Review and Prepare Launch')).toBeInTheDocument();
    });

    expect(screen.getByRole('button', { name: 'Commit Outputs Locally' })).toBeInTheDocument();
    expect(screen.getByText(/optionally record the generated outputs to git/i)).toBeInTheDocument();
  });

  test('treats partial outputs as attention items instead of normal launch-ready flow', async () => {
    getSwarmTrajectoryStatus.mockResolvedValue({
      success: true,
      status: {
        has_results: true,
        processed_trajectories: 2,
        processed_drones: [1, 2],
        processed_leaders: [1],
        leader_count: 1,
        follower_count: 2,
        uploaded_leaders: [1],
        clusters: [
          {
            leader_id: 1,
            follower_ids: [2, 3],
            follower_count: 2,
            expected_drone_count: 3,
            processed_drone_count: 2,
            processed_follower_ids: [2],
            missing_follower_ids: [3],
            ready: false,
            state: 'partial_outputs',
            leader_uploaded: true,
            leader_processed: true,
            issues: ['Missing follower outputs: 3'],
            advisories: [],
            cluster_plot_available: true,
            leader_plot_available: true,
          },
        ],
        cluster_summary: {
          cluster_count: 1,
          ready_cluster_count: 0,
          needs_processing_cluster_count: 0,
          partial_output_cluster_count: 1,
          missing_upload_cluster_count: 0,
          processed_cluster_count: 1,
          overall_state: 'partial',
        },
        session: {
          exists: true,
          session_id: 'partial-session',
          processed_leaders: [1],
          total_drones: 2,
        },
        processing_recommendation: {
          action: 'safe_incremental',
          message: 'Safe incremental processing is available.',
          details: [],
        },
      },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByText('Review and Prepare Launch')).toBeInTheDocument();
    });

    expect(screen.getByText(/outputs generated, review still required/i)).toBeInTheDocument();
    expect(screen.getByText(/resolve the listed attention items, and reprocess before treating this as a full-fleet launch package/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open mission trigger/i })).toHaveLength(2);
  });
});
