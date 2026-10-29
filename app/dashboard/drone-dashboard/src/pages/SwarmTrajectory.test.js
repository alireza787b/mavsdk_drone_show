import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import SwarmTrajectory from './SwarmTrajectory';
import useFetch from '../hooks/useFetch';
import {
  buildSwarmTrajectoryPlotUrl,
  cancelSwarmTrajectoryProcessJob,
  clearAllSwarmTrajectories,
  clearSwarmTrajectoryDrone,
  clearSwarmTrajectoryLeader,
  clearProcessedData,
  commitSwarmTrajectoryOutputs,
  createSwarmTrajectoryProcessJob,
  downloadSwarmClusterKml,
  downloadSwarmTrajectoryCsv,
  downloadSwarmTrajectoryKml,
  getSwarmLeaders,
  getSwarmTrajectoryPreview,
  getSwarmTrajectoryProcessJob,
  getSwarmTrajectoryStatus,
  getSwarmTrajectoryValidation,
  removeSwarmTrajectoryUpload,
  uploadSwarmTrajectory,
} from '../services/droneApiService';

jest.mock('../hooks/useFetch');
// Map/legend behavior has its own real component tests; keep parent action
// tests independent of Leaflet's browser-only module loading.
jest.mock('../components/trajectory/TrajectoryRouteReview', () => () => <div data-testid="route-review" />);
jest.mock('./TrajectoryPlanning', () => (props) => (
  <div data-testid="leader-route-editor" data-leader={props.scopedLeaderId}>
    <span>{props.initialWaypoints.length} editor waypoints</span>
    <button type="button" onClick={() => props.onWaypointsChange([
      ...props.initialWaypoints,
      { id: 'draft-point', latitude: 0, longitude: 0, altitude: 100, timeFromStart: 0 },
    ])}>Edit route draft</button>
    <button type="button" onClick={() => props.onAssigned(props.scopedLeaderId, { success: true })}>
      Acknowledge assigned route
    </button>
  </div>
));
jest.mock('../services/droneApiService', () => ({
  buildSwarmTrajectoryPlotUrl: jest.fn((filename) => `http://plots.test/${filename}`),
  cancelSwarmTrajectoryProcessJob: jest.fn(),
  clearAllSwarmTrajectories: jest.fn(),
  clearSwarmTrajectoryDrone: jest.fn(),
  clearSwarmTrajectoryLeader: jest.fn(),
  clearProcessedData: jest.fn(),
  commitSwarmTrajectoryOutputs: jest.fn(),
  createSwarmTrajectoryProcessJob: jest.fn(),
  downloadSwarmClusterKml: jest.fn(),
  downloadSwarmTrajectoryCsv: jest.fn(),
  downloadSwarmTrajectoryKml: jest.fn(),
  getSwarmLeaders: jest.fn(),
  getSwarmTrajectoryPreview: jest.fn(),
  getSwarmTrajectoryProcessJob: jest.fn(),
  getSwarmTrajectoryStatus: jest.fn(),
  getSwarmTrajectoryValidation: jest.fn(),
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
    localStorage.clear();
    window.innerWidth = 1024;
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
    getSwarmTrajectoryValidation.mockResolvedValue({
      success: true,
      ready: true,
      state: 'ready',
      blockers: [],
      warnings: [],
      advisories: [],
      processed_drone_ids: [1, 2, 3],
      expected_drone_ids: [1, 2, 3],
      missing_drone_ids: [],
      cluster_summary: readyStatus.status.cluster_summary,
      package_stats: { available: true, drone_count: 3, drone_ids: [1, 2, 3] },
    });
    getSwarmTrajectoryPreview.mockResolvedValue({
      success: true,
      generated_at: '2026-05-15T00:00:00Z',
      drones: [
        {
          drone_id: 1,
          role: 'leader',
          top_leader_id: 1,
          direct_leader_id: null,
          point_count: 2,
          preview_point_count: 2,
          global_coordinates_available: true,
          points: [
            { sequence: 0, lat: 35, lng: 51, alt_msl: 1200, time_s: 0 },
            { sequence: 1, lat: 35.01, lng: 51.02, alt_msl: 1210, time_s: 30 },
          ],
          warnings: [],
        },
        {
          drone_id: 2,
          role: 'follower',
          top_leader_id: 1,
          direct_leader_id: 1,
          point_count: 2,
          preview_point_count: 2,
          global_coordinates_available: true,
          points: [
            { sequence: 0, lat: 35, lng: 51.001, alt_msl: 1198, time_s: 0 },
            { sequence: 1, lat: 35.01, lng: 51.021, alt_msl: 1208, time_s: 30 },
          ],
          warnings: [],
        },
      ],
      clusters: [],
      summary: {},
      blockers: [],
      warnings: [],
      advisories: [],
    });
    createSwarmTrajectoryProcessJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'queued',
      phase: 'queued',
      progress_percent: 0,
      message: 'Queued',
      cancel_requested: false,
    });
    getSwarmTrajectoryProcessJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'succeeded',
      phase: 'complete',
      progress_percent: 100,
      message: 'Complete',
      cancel_requested: false,
      result: {
        success: true,
        outcome: 'success',
        message: 'Formation outputs ready',
        processed_drones: 3,
        processed_drone_list: [1, 2, 3],
        processed_leaders: [1],
        missing_leaders: [],
        skipped_drone_ids: [],
        auto_reloaded: [],
        statistics: { leaders: 1, followers: 2, errors: 0 },
      },
    });
    cancelSwarmTrajectoryProcessJob.mockResolvedValue({
      job_id: 'job-1',
      status: 'canceled',
      phase: 'canceled',
      progress_percent: 20,
      message: 'Canceled',
      cancel_requested: true,
    });
    buildSwarmTrajectoryPlotUrl.mockImplementation((filename) => `http://plots.test/${filename}`);
    clearAllSwarmTrajectories.mockResolvedValue({ success: true });
    clearSwarmTrajectoryDrone.mockResolvedValue({ success: true });
    clearSwarmTrajectoryLeader.mockResolvedValue({ success: true });
    clearProcessedData.mockResolvedValue({ success: true });
    commitSwarmTrajectoryOutputs.mockResolvedValue({ success: true });
    downloadSwarmClusterKml.mockResolvedValue(new Blob(['cluster']));
    downloadSwarmTrajectoryCsv.mockResolvedValue(new Blob(['csv']));
    downloadSwarmTrajectoryKml.mockResolvedValue(new Blob(['kml']));
    removeSwarmTrajectoryUpload.mockResolvedValue({ success: true });
    uploadSwarmTrajectory.mockResolvedValue({ success: true });
  });

  afterEach(() => {
    window.innerWidth = 1024;
  });

  test('labels commit step as local-only when GCS auto-push is disabled', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /review/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('tab', { name: /review/i }));

    expect(screen.getByRole('button', { name: 'Record package' })).toBeInTheDocument();
    expect(screen.getByTestId('route-review')).toBeInTheDocument();
  });

  test('switching leader keeps routes separate and recovers them after reload', async () => {
    getSwarmLeaders.mockResolvedValue({ success: true, leaders: [1, 5],
      hierarchies: { 1: 2, 5: 0 }, follower_details: { 1: [2, 3], 5: [] }, simulation_mode: true });
    const first = render(<MemoryRouter><SwarmTrajectory /></MemoryRouter>);
    await waitFor(() => expect(screen.getByLabelText('Leader route assignment')).toHaveValue('1'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit route draft' }));
    await waitFor(() => expect(screen.getByText('1 editor waypoints')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Leader route assignment'), { target: { value: '5' } });
    expect(screen.getByText('0 editor waypoints')).toBeInTheDocument();
    expect(screen.getByTestId('leader-route-editor')).toHaveAttribute('data-leader', '5');
    fireEvent.change(screen.getByLabelText('Leader route assignment'), { target: { value: '1' } });
    expect(screen.getByText('1 editor waypoints')).toBeInTheDocument();
    first.unmount();
    render(<MemoryRouter><SwarmTrajectory /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('1 editor waypoints')).toBeInTheDocument());
    expect(uploadSwarmTrajectory).not.toHaveBeenCalled();
  });

  test('existing files cannot substitute for unavailable validation', async () => {
    getSwarmTrajectoryValidation.mockResolvedValue({ success: false, error: 'Unavailable' });
    render(<MemoryRouter><SwarmTrajectory /></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole('tab', { name: /review/i })).toBeInTheDocument());
    fireEvent.click(screen.getByRole('tab', { name: /review/i }));
    expect(screen.getByRole('button', { name: 'Record package' })).toBeDisabled();
    expect(commitSwarmTrajectoryOutputs).not.toHaveBeenCalled();
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
      expect(screen.getByRole('tab', { name: /review/i })).toBeInTheDocument();
    });
    fireEvent.click(screen.getByRole('tab', { name: /review/i }));

    expect(screen.getByText(/outputs generated, review still required/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: 'Operate' }).length).toBeGreaterThanOrEqual(1);
  });

  test('uses compact operator-flow and workspace-review summaries on mobile', async () => {
    window.innerWidth = 640;

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByRole('tab', { name: /route/i })).toHaveAttribute('aria-selected', 'true');
    });

    expect(screen.getAllByText('Package details').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('tab', { name: /uploads/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /generate/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /review/i })).toBeInTheDocument();
  });

  test('embeds one leader-scoped editor and advances only after an acknowledged assignment', async () => {
    render(<MemoryRouter><SwarmTrajectory embedded /></MemoryRouter>);
    const editor = await screen.findByTestId('leader-route-editor');
    expect(editor).toHaveAttribute('data-leader', '1');
    expect(screen.queryByRole('heading', { name: 'Swarm Trajectory Mission' })).not.toBeInTheDocument();
    expect(uploadSwarmTrajectory).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge assigned route' }));
    await waitFor(() => expect(screen.getByRole('tab', { name: /generate/i })).toHaveAttribute('aria-selected', 'true'));
    expect(screen.queryByTestId('leader-route-editor')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: /route/i }));
    expect(screen.getByTestId('leader-route-editor')).toHaveAttribute('data-leader', '1');
  });
});
