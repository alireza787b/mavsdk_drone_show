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
  getSwarmTrajectoryElevationBatch,
  getSwarmTrajectoryPreview,
  getSwarmTrajectoryProcessJob,
  getSwarmTrajectoryStatus,
  getSwarmTrajectoryValidation,
  removeSwarmTrajectoryUpload,
  uploadSwarmTrajectory,
} from '../services/droneApiService';

jest.mock('../hooks/useFetch');
jest.mock('../components/trajectory/SwarmRouteMapEditor', () => (props) => (
  <div data-testid="swarm-route-map-editor">
    <span>{props.altitudeLabel}</span>
    <button
      type="button"
      onClick={() => props.onAddWaypoint?.({ latitude: 35.03, longitude: 51.04 })}
    >
      Map click route point
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
  getSwarmTrajectoryElevationBatch: jest.fn(),
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
    getSwarmTrajectoryElevationBatch.mockResolvedValue({
      success: true,
      results: [{ id: 'wp', lat: 35, lng: 51, elevation_m: 1000, status: 'ok', source: 'test' }],
      summary: { requested: 1, resolved: 1, unavailable: 0, status: 'ok' },
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

    expect(screen.getByRole('button', { name: 'Commit Outputs Locally' })).toBeInTheDocument();
    expect(screen.getByText(/optionally commit for traceability/i)).toBeInTheDocument();
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
    expect(screen.getByText(/resolve attention items and reprocess/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open mission trigger/i }).length).toBeGreaterThanOrEqual(1);
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

    expect(screen.getAllByText('Workspace review & policy').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole('tab', { name: /leaders/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /process/i })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /review/i })).toBeInTheDocument();
  });

  test('assigns a drafted leader route from the single-page workflow', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('swarm-route-map-editor')).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '35.0' } });
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '51.0' } });
    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    await waitFor(() => {
      expect(screen.getByText(/WP1/i)).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '35.01' } });
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '51.02' } });
    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    await waitFor(() => {
      expect(screen.getByText(/WP2/i)).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /assign to leader/i }));

    await waitFor(() => {
      expect(uploadSwarmTrajectory).toHaveBeenCalledWith('1', expect.any(Blob), 'Drone 1.csv');
    });
    expect(getSwarmTrajectoryElevationBatch).not.toHaveBeenCalled();
  });

  test('adds draft waypoints from the embedded route map editor', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('swarm-route-map-editor')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: 'Map click route point' }));

    await waitFor(() => {
      expect(screen.getByText(/35.03000, 51.04000/i)).toBeInTheDocument();
    });
    expect(getSwarmTrajectoryElevationBatch).not.toHaveBeenCalled();
  });

  test('adds AGL waypoints with backend terrain provenance and sea-level elevation', async () => {
    getSwarmTrajectoryElevationBatch.mockResolvedValue({
      success: true,
      results: [{
        id: 'wp',
        lat: 35,
        lng: 51,
        elevation_m: 0,
        status: 'ok',
        source: 'opentopodata',
        provider: 'opentopodata',
        confidence: 'reported',
      }],
      summary: { requested: 1, resolved: 1, unavailable: 0, status: 'ok' },
    });

    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <SwarmTrajectory />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(screen.getByTestId('swarm-route-map-editor')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole('button', { name: /AGL Terrain based/i }));
    fireEvent.change(screen.getByLabelText('Latitude'), { target: { value: '35.0' } });
    fireEvent.change(screen.getByLabelText('Longitude'), { target: { value: '51.0' } });
    fireEvent.change(screen.getByLabelText('Time'), { target: { value: '0' } });
    fireEvent.click(screen.getByRole('button', { name: /add waypoint/i }));

    await waitFor(() => {
      expect(getSwarmTrajectoryElevationBatch).toHaveBeenCalledWith([
        expect.objectContaining({ lat: 35, lng: 51 }),
      ]);
    });
    expect(await screen.findByText('Terrain ready')).toBeInTheDocument();
    expect(screen.getByText(/1\/1 waypoint elevations resolved via opentopodata/i)).toBeInTheDocument();
    expect(screen.getByText(/100 m MSL/i)).toBeInTheDocument();
  });
});
