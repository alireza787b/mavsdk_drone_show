import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SitlControlPage from './SitlControlPage';
import {
  createSitlInstance,
  getSitlControlHost,
  getSitlControlImages,
  getSitlControlInstanceLogs,
  getSitlControlInstances,
  getSitlControlOperation,
  getSitlControlOperations,
  getSitlControlPolicy,
  reconcileSitlFleet,
  releaseSitlImage,
  removeSitlInstance,
  restartSitlInstance,
  runSitlInstanceAction,
} from '../services/sitlControlService';

jest.mock('../services/sitlControlService', () => ({
  getSitlControlPolicy: jest.fn(),
  createSitlInstance: jest.fn(),
  getSitlControlHost: jest.fn(),
  getSitlControlImages: jest.fn(),
  getSitlControlInstances: jest.fn(),
  getSitlControlInstanceLogs: jest.fn(),
  getSitlControlOperations: jest.fn(),
  getSitlControlOperation: jest.fn(),
  reconcileSitlFleet: jest.fn(),
  releaseSitlImage: jest.fn(),
  restartSitlInstance: jest.fn(),
  removeSitlInstance: jest.fn(),
  runSitlInstanceAction: jest.fn(),
}));

describe('SitlControlPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    getSitlControlPolicy.mockResolvedValue({
      sim_mode: true,
      read_only: false,
      defaults: {
        default_image: 'mavsdk-drone-show-sitl:latest',
        default_network_name: 'drone-network',
        default_git_sync: true,
        default_requirements_sync: true,
      },
      features: {
        lifecycle_mutations: true,
        bulk_actions: true,
        image_release: true,
      },
      docker: {
        daemon_reachable: true,
        server_version: '28.0.0',
        socket_path: '/var/run/docker.sock',
      },
    });
    getSitlControlHost.mockResolvedValue({
      host: {
        hostname: 'hetzner',
        platform: 'Linux',
        platform_release: '6.8.0',
        architecture: 'x86_64',
        cpu_count_logical: 8,
        memory_total_bytes: 4 * 1024 * 1024 * 1024,
        memory_available_bytes: 2 * 1024 * 1024 * 1024,
        disk_path: '/tmp',
        disk_total_bytes: 40 * 1024 * 1024 * 1024,
        disk_free_bytes: 12 * 1024 * 1024 * 1024,
      },
    });
    getSitlControlImages.mockResolvedValue({
      images: [
        {
          image_id: 'sha256:1',
          primary_tag: 'mavsdk-drone-show-sitl:latest',
          repo_tags: ['mavsdk-drone-show-sitl:latest', 'mavsdk-drone-show-sitl:v5'],
          branch: 'main-candidate',
          commit: 'abc1234',
          in_use_by_instances: 1,
          size_bytes: 1024 * 1024 * 1024,
          created_at: '2026-04-13T00:00:00Z',
        },
      ],
    });
    getSitlControlInstances.mockResolvedValue({
      instances: [
        {
          name: 'drone-1',
          state: 'running',
          status: 'running',
          hw_id: '1',
          pos_id_hint: 1,
          image_ref: 'mavsdk-drone-show-sitl:latest',
          git_repo_url: 'https://github.com/alireza787b/mavsdk_drone_show.git',
          git_branch: 'main-candidate',
          ip_addresses: { 'drone-network': '172.18.0.2' },
          git_sync_enabled: true,
          requirements_sync_enabled: true,
          started_at: '2026-04-13T00:01:00Z',
        },
        {
          name: 'drone-2',
          state: 'exited',
          status: 'exited',
          hw_id: '2',
          pos_id_hint: 2,
          image_ref: 'mavsdk-drone-show-sitl:latest',
          git_repo_url: 'https://github.com/alireza787b/mavsdk_drone_show.git',
          git_branch: 'main-candidate',
          ip_addresses: { 'drone-network': '172.18.0.3' },
          git_sync_enabled: false,
          requirements_sync_enabled: true,
          started_at: '2026-04-13T00:02:00Z',
        },
      ],
    });
    getSitlControlInstanceLogs.mockResolvedValue({
      lines: ['boot', 'ready'],
      source: 'docker',
    });
    getSitlControlOperations.mockResolvedValue({
      operations: [
        {
          operation_id: 'sitl-op-1',
          operation_type: 'reconcile_fleet',
          status: 'running',
          summary: 'Reconciling SITL fleet',
          detail: 'Waiting for readiness',
          affected_instances: ['drone-1'],
          log_lines: ['boot'],
          created_at: 1000,
          updated_at: 1000,
        },
      ],
    });
    getSitlControlOperation.mockResolvedValue({
      operation_id: 'sitl-op-1',
      operation_type: 'reconcile_fleet',
      status: 'running',
      summary: 'Reconciling SITL fleet',
      detail: 'Waiting for readiness',
      affected_instances: ['drone-1'],
      log_lines: ['boot', 'ready'],
      created_at: 1000,
      updated_at: 1001,
    });
    reconcileSitlFleet.mockResolvedValue({
      operation_id: 'sitl-op-2',
      summary: 'SITL fleet reconcile queued',
    });
    createSitlInstance.mockResolvedValue({
      operation_id: 'sitl-op-create',
      summary: 'Created drone-3',
    });
    restartSitlInstance.mockResolvedValue({
      operation_id: 'sitl-op-3',
      summary: 'Restart queued',
    });
    removeSitlInstance.mockResolvedValue({
      operation_id: 'sitl-op-4',
      summary: 'Remove queued',
    });
    runSitlInstanceAction.mockResolvedValue({
      operation_id: 'sitl-op-5',
      summary: 'Batch restart queued',
    });
    releaseSitlImage.mockResolvedValue({
      operation_id: 'sitl-op-6',
      summary: 'SITL image save queued',
    });
  });

  test('renders inventory with collapsed instance details by default', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('SITL Control')).toBeInTheDocument();
    expect(await screen.findByRole('heading', { name: 'Fleet' })).toBeInTheDocument();
    expect(await screen.findByText('Docker')).toBeInTheDocument();
    expect(await screen.findByLabelText(/image repository/i)).toHaveValue('mavsdk-drone-show-sitl');
    expect(await screen.findByLabelText(/image tag/i)).toHaveValue('latest');
    expect(await screen.findByText('drone-1')).toBeInTheDocument();
    expect(screen.queryByText('Logs')).not.toBeInTheDocument();
    expect(getSitlControlInstanceLogs).not.toHaveBeenCalled();
    expect(screen.queryByText('Waiting for readiness')).not.toBeInTheDocument();
  });

  test('toggles instance detail open and closed and loads logs only when selected', async () => {
    render(<SitlControlPage />);

    const row = await screen.findByRole('button', { name: /drone-1/i });
    fireEvent.click(row);

    await waitFor(() => {
      expect(getSitlControlInstanceLogs).toHaveBeenCalledWith('drone-1', { tail: 200 });
    });
    const detailPanel = await screen.findByText('Logs');
    expect(detailPanel).toBeInTheDocument();
    expect(screen.getByText(/^Git sync$/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /drone-1/i }));

    await waitFor(() => {
      expect(screen.queryByText('Logs')).not.toBeInTheDocument();
    });
  });

  test('reconcile and add-next require confirmation before queuing actions', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByRole('button', { name: /^reconcile$/i })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/desired instances/i), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: /^reconcile$/i }));
    const reconcileDialog = await screen.findByRole('dialog');
    fireEvent.click(within(reconcileDialog).getByRole('button', { name: /^reconcile$/i }));

    await waitFor(() => {
      expect(reconcileSitlFleet).toHaveBeenCalledWith(expect.objectContaining({ target_count: 4 }));
    });

    fireEvent.click(screen.getByRole('button', { name: /^next$/i }));
    expect(await screen.findByText(/add next sitl container/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^add next$/i }));

    await waitFor(() => {
      expect(createSitlInstance).toHaveBeenCalledWith(expect.objectContaining({
        image_ref: 'mavsdk-drone-show-sitl:latest',
      }));
    });
  });

  test('operations remain collapsed until opened explicitly', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('Ops')).toBeInTheDocument();
    expect(screen.queryByText('Waiting for readiness')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /ops/i }));

    expect(await screen.findByText('Reconciling SITL fleet')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /reconciling sitl fleet/i }));

    await waitFor(() => {
      expect(getSitlControlOperation).toHaveBeenCalledWith('sitl-op-1');
      expect(screen.getByText('Waiting for readiness')).toBeInTheDocument();
    });
  });

  test('image save flow stays inside Images and uses explicit confirmation', async () => {
    render(<SitlControlPage />);

    fireEvent.click(await screen.findByRole('button', { name: /images/i }));
    fireEvent.click(screen.getByRole('button', { name: /save image/i }));

    const imageCard = await screen.findByText(/source mavsdk-drone-show-sitl:latest/i);
    const releaseCard = imageCard.closest('.sitl-collapsible');
    expect(within(releaseCard).getByLabelText(/source image repository/i)).toHaveValue('mavsdk-drone-show-sitl');
    fireEvent.change(within(releaseCard).getByLabelText(/^Version tag$/i), { target: { value: 'release-demo' } });
    fireEvent.click(within(releaseCard).getAllByRole('button', { name: /^save image$/i }).slice(-1)[0]);

    const saveDialog = await screen.findByRole('dialog');
    fireEvent.click(within(saveDialog).getByRole('button', { name: /^save image$/i }));

    await waitFor(() => {
      expect(releaseSitlImage).toHaveBeenCalledWith(expect.objectContaining({
        image_repo: 'mavsdk-drone-show-sitl',
        version_tag: 'release-demo',
        tag_latest: true,
        tag_commit: true,
        export_archive: true,
      }));
    });
  });

  test('batch actions operate on the filtered visible scope', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByRole('heading', { name: 'Instances' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/search sitl instances/i), { target: { value: 'drone-2' } });
    fireEvent.click(screen.getByRole('button', { name: /batch/i }));

    const batchPanel = screen.getByText(/1 of 2 visible/i).closest('.sitl-batch-panel');
    fireEvent.click(within(batchPanel).getByRole('button', { name: /restart visible/i }));
    const batchDialog = await screen.findByRole('dialog');
    fireEvent.click(within(batchDialog).getByRole('button', { name: /^restart visible$/i }));

    await waitFor(() => {
      expect(runSitlInstanceAction).toHaveBeenCalledWith({
        action: 'restart',
        instance_names: ['drone-2'],
      });
    });
  });
});
