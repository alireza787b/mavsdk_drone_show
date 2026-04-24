import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import FleetOpsPage from './FleetOpsPage';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';

jest.mock('../hooks/useFetch');

const gitPayload = {
  gcs_status: {
    branch: 'main-candidate',
    commit: 'abcdef1234567890',
  },
  git_status: {
    1: {
      pos_id: 1,
      hw_id: '1',
      ip: '100.82.72.33',
      branch: 'main-candidate',
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
      ip: '100.82.47.7',
      branch: 'main-candidate',
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
  heartbeats: [
    { pos_id: 1, hw_id: '1', ip: '100.82.72.33', online: true, runtime_mode: 'real' },
    { pos_id: 2, hw_id: '2', ip: '100.82.47.7', online: false, runtime_mode: 'real' },
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

describe('FleetOpsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFleetFeeds();
  });

  test('renders fleet access and sidecar posture from existing status APIs', () => {
    render(<FleetOpsPage />);

    expect(screen.getByRole('heading', { name: /fleet ops/i })).toBeInTheDocument();
    expect(screen.getAllByText('1/2').length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText('1 MAVLink')).toBeInTheDocument();
    expect(screen.getByText(/0 connectivity healthy/i)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 1/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 2/i })).toBeInTheDocument();
    expect(screen.getByText(/node-level sync, access, and sidecar posture/i)).toBeInTheDocument();
  });

  test('shows access details without exposing secret paths or values', () => {
    render(<FleetOpsPage />);

    fireEvent.click(screen.getByRole('tab', { name: /access/i }));

    expect(screen.getByText('HTTPS token')).toBeInTheDocument();
    expect(screen.getByText('SSH key')).toBeInTheDocument();
    expect(screen.getByText(/https token-file access is configured and readable/i)).toBeInTheDocument();
    expect(screen.queryByText(/token_file/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/\/root\//i)).not.toBeInTheDocument();
  });

  test('filters to nodes requiring operator attention', () => {
    render(<FleetOpsPage />);

    fireEvent.change(screen.getByLabelText(/filter/i), { target: { value: 'attention' } });

    expect(screen.queryByRole('heading', { name: /hw 1/i })).not.toBeInTheDocument();
    const attentionCard = screen.getByRole('heading', { name: /hw 2/i }).closest('article');
    expect(within(attentionCard).getByText('Offline')).toBeInTheDocument();
    expect(within(attentionCard).getAllByText('Drift').length).toBeGreaterThan(0);
  });

  test('drift filter includes sidecar and node-runtime drift, not only repo drift', () => {
    const driftGitPayload = clonePayload(gitPayload);
    driftGitPayload.git_status[3] = {
      pos_id: 3,
      hw_id: '3',
      ip: '100.82.47.9',
      branch: 'main-candidate',
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
    driftHeartbeatPayload.heartbeats.push({ pos_id: 3, hw_id: '3', ip: '100.82.47.9', online: true, runtime_mode: 'real' });

    render(<FleetOpsPage gitStatusOverride={driftGitPayload} heartbeatOverride={driftHeartbeatPayload} />);

    fireEvent.change(screen.getByLabelText(/filter/i), { target: { value: 'drift' } });

    expect(screen.queryByRole('heading', { name: /hw 1/i })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 2/i })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /hw 3/i })).toBeInTheDocument();
  });

  test('shows sidecar detail and treats local-only dashboards as diagnostics, not primary controls', () => {
    render(<FleetOpsPage />);

    fireEvent.click(screen.getByRole('tab', { name: /sidecars/i }));

    expect(screen.getByText(/ref v3.0.8; router active; dashboard local_only; hash abcdef123456/i)).toBeInTheDocument();
    expect(screen.getAllByText(/no direct dashboard/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/backend smart-wifi-manager; mode manage; profile missing; hash drift 666666666666 -> 555555555555/i)).toBeInTheDocument();
    expect(screen.getByText('222222222222')).toBeInTheDocument();
    expect(screen.getByText('333333333333')).toBeInTheDocument();
  });
});
