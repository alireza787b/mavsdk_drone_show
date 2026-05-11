import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import FleetOpsPage from './FleetOpsPage';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS, syncReposResponse } from '../services/gcsApiService';

jest.mock('../hooks/useFetch');
jest.mock('../services/gcsApiService', () => {
  const actual = jest.requireActual('../services/gcsApiService');
  return {
    ...actual,
    syncReposResponse: jest.fn(),
  };
});

const gitPayload = {
  gcs_status: {
    branch: 'main',
    commit: 'abcdef1234567890',
    remote_url: 'git@github.com:demo/customer-mds.git',
  },
  git_status: {
    1: {
      pos_id: 1,
      hw_id: '1',
      ip: '198.51.100.11',
      branch: 'main',
      commit: 'abcdef1234567890',
      in_sync_with_gcs: true,
      repo_access_mode: 'https_token_file',
      git_auth_health_status: 'healthy',
      git_auth_health_summary: 'HTTPS token-file access is configured and readable.',
      mavlink_runtime: {
        management_mode: 'managed',
        ref: 'v3.0.8',
        repo_web_url: 'https://github.com/alireza787b/mavlink-anywhere/tree/v3.0.8',
        router_service_status: 'active',
        dashboard_enabled: true,
        dashboard_service_status: 'active',
        dashboard_access_mode: 'local_only',
        dashboard_listen: '127.0.0.1:9070',
        dashboard_url: null,
        desired_config_hash: 'abcdef1234567890',
        applied_config_hash: 'abcdef1234567890',
        config_hash_match: true,
      },
      connectivity_runtime: {
        backend: 'none',
        mode: 'observe',
        service_status: 'unknown',
        profile_present: false,
        dashboard_access_mode: 'local_only',
        desired_config_hash: '1111111111111111',
        applied_config_hash: '1111111111111111',
        config_hash_match: true,
      },
      git_sync_runtime: {
        status: 'unknown',
        summary: 'No node-local git sync runtime state has been recorded yet.',
        mavlink_runtime_reconcile_status: 'unknown',
        connectivity_reconcile_status: 'unknown',
      },
    },
    2: {
      pos_id: 2,
      hw_id: '2',
      ip: '198.51.100.12',
      branch: 'main',
      commit: '1111111111111111',
      in_sync_with_gcs: false,
      repo_access_mode: 'ssh_key',
      git_auth_health_status: 'warning',
      git_auth_health_summary: 'SSH key is missing.',
      mavlink_runtime: {
        management_mode: 'managed',
        ref: 'v3.0.8',
        router_service_status: 'failed',
        dashboard_enabled: true,
        dashboard_service_status: 'inactive',
        dashboard_access_mode: 'disabled',
        desired_config_hash: '2222222222222222',
        applied_config_hash: '3333333333333333',
        config_hash_match: false,
      },
      connectivity_runtime: {
        backend: 'smart-wifi-manager',
        mode: 'manage',
        service_status: 'inactive',
        profile_present: false,
        dashboard_access_mode: 'disabled',
        profile_hash: '4444444444444444',
        desired_config_hash: '5555555555555555',
        applied_config_hash: '6666666666666666',
        config_hash_match: false,
      },
    },
  },
};

const heartbeatPayload = {
  timestamp: 1777049000000,
  heartbeats: [
    { pos_id: 1, hw_id: '1', ip: '198.51.100.11', online: true, runtime_mode: 'real', last_heartbeat: 1777048999000 },
    { pos_id: 2, hw_id: '2', ip: '198.51.100.12', online: false, runtime_mode: 'real', last_heartbeat: 1777048800000 },
  ],
};

function mockFleetFeeds() {
  useFetch.mockImplementation((endpoint) => {
    if (endpoint === GCS_ROUTE_KEYS.gitStatus) {
      return { data: gitPayload, loading: false, error: null };
    }
    if (endpoint === GCS_ROUTE_KEYS.fleetHeartbeats) {
      return { data: heartbeatPayload, loading: false, error: null };
    }
    return { data: null, loading: false, error: null };
  });
}

function clonePayload(payload) {
  return JSON.parse(JSON.stringify(payload));
}

function renderFleetOps(props = {}) {
  return render(
    <MemoryRouter>
      <FleetOpsPage {...props} />
    </MemoryRouter>
  );
}

describe('FleetOpsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFleetFeeds();
  });

  test('renders fleet access and sidecar posture from existing status APIs', () => {
    renderFleetOps();

    expect(screen.getByRole('heading', { name: /fleet ops/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /fleet ops guide/i })).toHaveAttribute(
      'href',
      'https://github.com/demo/customer-mds/blob/main/docs/guides/fleet-ops.md',
    );
    expect(screen.getAllByText('1/2').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('1 MAVLink')).toBeInTheDocument();
    expect(screen.getByText(/0 connectivity/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 1/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 2/i })).toBeInTheDocument();
    expect(screen.getByText(/drone-node sync, access, and sidecars/i)).toBeInTheDocument();
    expect(screen.getByText(/drone nodes/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open gcs runtime admin/i })).toHaveAttribute('href', '/runtime-admin');
  });

  test('shows access details without exposing secret paths or values', () => {
    renderFleetOps();

    fireEvent.click(screen.getByRole('button', { name: /access/i }));

    expect(screen.getByText('HTTPS token')).toBeInTheDocument();
    expect(screen.getByText('SSH key')).toBeInTheDocument();
    expect(screen.getByText(/https token-file access is configured and readable/i)).toBeInTheDocument();
    expect(screen.queryByText(/token_file/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/root\//i)).not.toBeInTheDocument();
  });

  test('filters to nodes requiring operator attention', () => {
    renderFleetOps();

    fireEvent.change(screen.getByLabelText(/filter/i), { target: { value: 'attention' } });

    expect(screen.queryByRole('heading', { name: /hw 1/i })).not.toBeInTheDocument();
    const attentionCard = screen.getByRole('heading', { name: /hw 2/i }).closest('article');
    expect(within(attentionCard).getAllByText('Offline').length).toBeGreaterThan(0);
    expect(within(attentionCard).getAllByText('Drift').length).toBeGreaterThan(0);
  });

  test('drift filter includes sidecar and node-runtime drift, not only repo drift', () => {
    const driftGitPayload = clonePayload(gitPayload);
    driftGitPayload.git_status[3] = {
      pos_id: 3,
      hw_id: '3',
      ip: '198.51.100.13',
      branch: 'main',
      commit: 'abcdef1234567890',
      in_sync_with_gcs: true,
      repo_access_mode: 'https_token_file',
      git_auth_health_status: 'healthy',
      git_auth_health_summary: 'HTTPS token-file access is configured and readable.',
      mavlink_runtime: {
        management_mode: 'managed',
        ref: 'v3.0.8',
        router_service_status: 'active',
        dashboard_enabled: false,
        desired_config_hash: 'aaaaaaaaaaaaaaaa',
        applied_config_hash: 'bbbbbbbbbbbbbbbb',
        config_hash_match: false,
      },
      connectivity_runtime: { backend: 'none' },
      git_sync_runtime: {
        status: 'success',
        summary: 'Git synchronization completed successfully; unit update requires installer refresh.',
        service_reload_status: 'warning',
        deferred_unit_actions: ['git_sync_mds.service:manual_unit_update_required'],
        mavlink_runtime_reconcile_status: 'success',
        connectivity_reconcile_status: 'not_required',
      },
    };
    const driftHeartbeatPayload = clonePayload(heartbeatPayload);
    driftHeartbeatPayload.heartbeats.push({ pos_id: 3, hw_id: '3', ip: '198.51.100.13', online: true, runtime_mode: 'real', last_heartbeat: 1777048999000 });

    renderFleetOps({ gitStatusOverride: driftGitPayload, heartbeatOverride: driftHeartbeatPayload });

    fireEvent.change(screen.getByLabelText(/filter/i), { target: { value: 'drift' } });

    expect(screen.queryByRole('heading', { name: /hw 1/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 2/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 3/i })).toBeInTheDocument();
  });

  test('shows sidecar detail and only links direct dashboard listeners', () => {
    const directGitPayload = clonePayload(gitPayload);
    directGitPayload.git_status[1].mavlink_runtime.dashboard_access_mode = 'direct';
    directGitPayload.git_status[1].mavlink_runtime.dashboard_listen = '0.0.0.0:9070';

    renderFleetOps({ gitStatusOverride: directGitPayload, heartbeatOverride: heartbeatPayload });

    expect(screen.getByRole('link', { name: /open mavlink dashboard/i })).toHaveAttribute(
      'href',
      'http://198.51.100.11:9070',
    );

    fireEvent.click(screen.getByRole('button', { name: /sidecars/i }));

    expect(screen.getByRole('region', { name: /sidecar fleet table/i })).toBeInTheDocument();
    expect(screen.getByText(/wi-fi and mavlink posture/i)).toBeInTheDocument();
    expect(screen.getAllByText(/MAVLink/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Smart Wi-Fi/).length).toBeGreaterThan(0);
    expect(screen.getByText(/ref v3.0.8; router active; dashboard direct; hash abcdef123456/i)).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open mavlink dashboard/i }).length).toBeGreaterThan(0);
    expect(screen.getByText(/smart wi-fi is inactive; mode manage; fleet profile source missing\. import a private fleet profile, then sync \+ reconcile\. hash drift 666666666666 -> 555555555555/i)).toBeInTheDocument();
    expect(screen.getByText('222222222222')).toBeInTheDocument();
    expect(screen.getByText('333333333333')).toBeInTheDocument();
  });

  test('keeps local-only sidecar dashboards visible but disabled', () => {
    renderFleetOps();

    expect(screen.queryByRole('link', { name: /open mavlink dashboard/i })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText(/open mavlink dashboard is local-only/i).length).toBeGreaterThan(0);
  });

  test('sync action targets selected nodes and reports result', async () => {
    syncReposResponse.mockResolvedValue({
      data: {
        success: true,
        message: 'Sync verified: 1 of 1 drones now match GCS',
        synced_drones: [2],
        failed_drones: [],
      },
    });

    renderFleetOps();

    fireEvent.click(screen.getByRole('button', { name: /select drone 2/i }));
    fireEvent.click(screen.getByRole('button', { name: /sync \+ reconcile/i }));

    await waitFor(() => {
      expect(syncReposResponse).toHaveBeenCalledWith({ pos_ids: [2] });
    });
    expect(await screen.findByText(/sync verified: 1 of 1 drones now match gcs/i)).toBeInTheDocument();
  });
});
