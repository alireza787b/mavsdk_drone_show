import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SitlControlPage from './SitlControlPage';
import {
  getSitlControlHost,
  getSitlControlImages,
  getSitlControlInstanceLogs,
  getSitlControlInstances,
  getSitlControlOperation,
  getSitlControlOperations,
  getSitlControlPolicy,
  reconcileSitlFleet,
  restartSitlInstance,
} from '../services/sitlControlService';

jest.mock('../services/sitlControlService', () => ({
  getSitlControlPolicy: jest.fn(),
  getSitlControlHost: jest.fn(),
  getSitlControlImages: jest.fn(),
  getSitlControlInstances: jest.fn(),
  getSitlControlInstanceLogs: jest.fn(),
  getSitlControlOperations: jest.fn(),
  getSitlControlOperation: jest.fn(),
  reconcileSitlFleet: jest.fn(),
  restartSitlInstance: jest.fn(),
  removeSitlInstance: jest.fn(),
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
        memory_total_bytes: 1024 * 1024 * 1024,
        memory_available_bytes: 512 * 1024 * 1024,
        disk_path: '/tmp',
        disk_total_bytes: 20 * 1024 * 1024 * 1024,
        disk_free_bytes: 8 * 1024 * 1024 * 1024,
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
    restartSitlInstance.mockResolvedValue({
      operation_id: 'sitl-op-3',
      summary: 'Restart queued',
    });
    window.confirm = jest.fn(() => true);
  });

  test('renders SITL inventory summary and selected instance logs', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('SITL Control')).toBeInTheDocument();
    expect(await screen.findByText('Fleet')).toBeInTheDocument();
    expect(await screen.findByText('Docker')).toBeInTheDocument();
    expect((await screen.findAllByText('mavsdk-drone-show-sitl:latest')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('drone-1')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('P1|H1')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Reconciling SITL fleet')).length).toBeGreaterThan(0);
    expect(await screen.findByLabelText(/image repository/i)).toHaveValue('mavsdk-drone-show-sitl');
    expect(await screen.findByLabelText(/image tag/i)).toHaveValue('latest');

    await waitFor(() => {
      expect(getSitlControlInstanceLogs).toHaveBeenCalledWith('drone-1', { tail: 200 });
    });

    await waitFor(() => {
      expect(getSitlControlOperation).toHaveBeenCalledWith('sitl-op-1');
      expect(screen.getByText('Waiting for readiness')).toBeInTheDocument();
    });
  });

  test('switches selected instance and reloads logs', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('drone-2')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /drone-2/i }));

    await waitFor(() => {
      expect(getSitlControlInstanceLogs).toHaveBeenLastCalledWith('drone-2', { tail: 200 });
    });
  });

  test('submits reconcile and restart actions through the SITL control service', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('Reconcile fleet')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/desired instances/i), { target: { value: '4' } });
    fireEvent.click(screen.getByRole('button', { name: /reconcile fleet/i }));

    await waitFor(() => {
      expect(reconcileSitlFleet).toHaveBeenCalledWith(expect.objectContaining({ target_count: 4 }));
    });

    fireEvent.click(screen.getByRole('button', { name: /restart/i }));

    await waitFor(() => {
      expect(restartSitlInstance).toHaveBeenCalledWith('drone-1');
    });
  });

  test('restart keeps inventory visible and shows instance-local pending state', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByRole('heading', { name: 'Instances' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^restart$/i }));

    await waitFor(() => {
      expect(screen.getByText(/this container is restarting/i)).toBeInTheDocument();
    });

    const detailPanel = screen.getByText(/this container is restarting/i).closest('.sitl-instance-detail');
    const restartButton = within(detailPanel).getByRole('button', { name: /restarting/i });

    expect(restartButton).toBeDisabled();
    expect(screen.getByText('drone-2')).toBeInTheDocument();
  });

  test('filters the instance list with the search field', async () => {
    render(<SitlControlPage />);

    expect(await screen.findByText('drone-2')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/search sitl instances/i), { target: { value: '172.18.0.3' } });

    const instancesHeading = screen.getByRole('heading', { name: 'Instances' });
    const instancesSection = instancesHeading.closest('.sitl-section');

    expect(within(instancesSection).queryByRole('button', { name: /drone-1/i })).not.toBeInTheDocument();
    expect(within(instancesSection).getByRole('button', { name: /drone-2/i })).toBeInTheDocument();
  });
});
