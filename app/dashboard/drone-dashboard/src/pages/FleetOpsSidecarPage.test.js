import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FleetOpsSidecarPage, { MAVLINK_SIDECAR_CONFIG, SMART_WIFI_SIDECAR_CONFIG } from './FleetOpsSidecarPage';
import {
  applyFleetSidecarReconcileResponse,
  dryRunFleetSidecarReconcileResponse,
  getFleetSidecarResponse,
  promoteFleetSidecarDraftResponse,
} from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({
  applyFleetSidecarPolicyResponse: jest.fn(),
  applyFleetSidecarReconcileResponse: jest.fn(),
  dryRunFleetSidecarPolicyResponse: jest.fn(),
  dryRunFleetSidecarReconcileResponse: jest.fn(),
  getFleetSidecarResponse: jest.fn(),
  promoteFleetSidecarDraftResponse: jest.fn(),
}));

const wifiTable = {
  schema: 'mds.sidecar_profile.v1',
  sidecar: 'smart-wifi-manager',
  baseline: {
    present: true,
    path: 'config/fleet-profiles/smart-wifi-manager/config.json',
    hash: 'abcdef1234567890',
    hash_semantics: 'sha256:canonical-sanitized-payload:12',
    profile_count: 1,
    profiles: [
      {
        id: 'field-primary',
        ssid: 'Demo Field',
        priority: 100,
        secret_status: 'stored',
      },
    ],
  },
  rows: [
    {
      hw_id: '1',
      pos_id: 1,
      ip: '198.51.100.11',
      presence: { state: 'online', age_seconds: 1 },
      service_state: 'active',
      installed_ref: 'v2.1.11',
      mode: 'fleet-merge',
      profile_source: 'node-local',
      desired_hash: 'abcdef1234567890',
      local_hash: 'abcdef1234567890',
      drift_state: 'local_extra',
      profile_count: 2,
      dashboard: { url: 'http://198.51.100.11:9080/' },
      profile_summary: {
        network_count: 2,
        profiles: [
          { id: 'field-primary', ssid: 'Demo Field Local', priority: 100, secret_status: 'stored' },
          { id: 'field-recovery', ssid: 'Demo Recovery', priority: 20, secret_status: 'external file' },
        ],
      },
      profiles: [
        { id: 'field-primary', ssid: 'Demo Field Local', priority: 100, secret_status: 'stored' },
        { id: 'field-recovery', ssid: 'Demo Recovery', priority: 20, secret_status: 'external file' },
      ],
      last_apply_result: 'local_extra',
    },
    {
      hw_id: '2',
      pos_id: 2,
      ip: '198.51.100.12',
      presence: { state: 'offline', age_seconds: 500 },
      service_state: 'unreachable',
      installed_ref: null,
      mode: 'fleet-merge',
      profile_source: null,
      desired_hash: 'abcdef1234567890',
      local_hash: null,
      drift_state: 'unreachable',
      profile_count: 0,
      dashboard: {},
      last_apply_result: null,
    },
  ],
};

const mavlinkTable = {
  schema: 'mds.sidecar_profile.v1',
  sidecar: 'mavlink-anywhere',
  baseline: {
    present: true,
    path: 'config/fleet-profiles/mavlink-anywhere/profile.json',
    hash: 'fedcba9876543210',
    hash_semantics: 'sha256:canonical-sanitized-payload:12',
    profile_count: 1,
    endpoints: [
      {
        name: 'gcs_ops',
        type: 'UdpEndpoint',
        mode: 'normal',
        address: '192.0.2.10',
        port: 24550,
        category: 'gcs',
        enabled: true,
      },
    ],
  },
  rows: [
    {
      hw_id: '1',
      pos_id: 1,
      ip: '198.51.100.11',
      presence: { state: 'online', age_seconds: 1 },
      service_state: 'active',
      installed_ref: 'v3.0.10',
      mode: 'local',
      profile_source: 'node-overlay',
      desired_hash: null,
      applied_hash: 'routehash123456',
      local_hash: 'routehash123456',
      drift_state: 'unmanaged',
      profile_count: 1,
      dashboard: { url: 'http://198.51.100.11:9070/' },
      profile_summary: {
        source_count: 1,
        endpoint_count: 1,
        sources: [
          { name: 'px4', type: 'UartEndpoint', device: '/dev/ttyS0', baud: 921600, role: 'source', mode: 'normal' },
        ],
        endpoints: [
          { name: 'gcs_vpn', type: 'UdpEndpoint', mode: 'normal', address: '192.0.2.11', port: 24550, category: 'gcs' },
        ],
      },
      sources: [
        { name: 'px4', type: 'UartEndpoint', device: '/dev/ttyS0', baud: 921600, role: 'source', mode: 'normal' },
      ],
      endpoints: [
        { name: 'gcs_vpn', type: 'UdpEndpoint', mode: 'normal', address: '192.0.2.11', port: 24550, category: 'gcs' },
      ],
      last_apply_result: 'unmanaged',
    },
  ],
};

describe('FleetOpsSidecarPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    window.sessionStorage.clear();
    getFleetSidecarResponse.mockResolvedValue({ data: wifiTable });
  });

  test('renders redacted baseline and disables unreachable nodes by default', async () => {
    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    expect(await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /sidecar profile guide/i })).toHaveAttribute(
      'href',
      expect.stringContaining('docs/features/fleet-sidecar-profiles.md'),
    );
    expect(await screen.findByLabelText(/select P2\|H2/i)).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /baseline/i }));

    expect(screen.getByRole('dialog', { name: /repo wi-fi baseline/i })).toBeInTheDocument();
    expect(screen.getByText('Demo Field')).toBeInTheDocument();
    expect(screen.getByText('password stored')).toBeInTheDocument();
    expect(screen.queryByText(/redacted-demo-value/i)).not.toBeInTheDocument();
  });

  test('node detail dialog shows sanitized local and repo Wi-Fi profile detail', async () => {
    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i });
    const driftButtons = await screen.findAllByRole('button', { name: /local_extra/i });
    fireEvent.click(driftButtons[0]);

    expect(screen.getByRole('dialog', { name: /node wi-fi profile: P1\|H1/i })).toBeInTheDocument();
    expect(screen.getByText('Pos ID')).toBeInTheDocument();
    expect(screen.getByText('HW ID')).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open P1\|H1 wi-fi manager dashboard/i })[0]).toHaveAttribute(
      'href',
      'http://198.51.100.11:9080/'
    );
    expect(screen.getByText('Node Wi-Fi Differences')).toBeInTheDocument();
    expect(screen.getByText('Repo Wi-Fi Baseline')).toBeInTheDocument();
    expect(screen.getByText('Demo Field Local')).toBeInTheDocument();
    expect(screen.getByText('Demo Recovery')).toBeInTheDocument();
    expect(screen.getAllByText('Demo Field').length).toBeGreaterThan(0);
    expect(screen.getByText('password external file')).toBeInTheDocument();
    expect(screen.queryByText(/redacted-demo-value/i)).not.toBeInTheDocument();
  });

  test('node Wi-Fi differences hide profiles that match the repo-visible fields', async () => {
    getFleetSidecarResponse.mockResolvedValue({
      data: {
        ...wifiTable,
        rows: [
          {
            ...wifiTable.rows[0],
            drift_state: 'in_sync',
            profile_count: 1,
            profiles: [
              {
                id: 'field-primary',
                ssid: 'Demo Field',
                priority: '100',
                secret_status: 'stored',
                source: 'node-runtime',
                last_connected_at: 'redacted',
              },
            ],
            profile_summary: {
              profiles: [
                {
                  id: 'field-primary',
                  ssid: 'Demo Field',
                  priority: '100',
                  secret_status: 'stored',
                  source: 'node-runtime',
                  last_connected_at: 'redacted',
                },
              ],
            },
          },
        ],
      },
    });

    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i });
    fireEvent.click(await screen.findByRole('button', { name: /view P1\|H1 profile details/i }));

    expect(screen.getByText('Node Wi-Fi Differences')).toBeInTheDocument();
    expect(screen.getByText('0 profiles')).toBeInTheDocument();
    expect(screen.getByText('No node differences beyond repo baseline.')).toBeInTheDocument();
    expect(screen.getByText('Repo Wi-Fi Baseline')).toBeInTheDocument();
    expect(screen.getByText('Demo Field')).toBeInTheDocument();
  });

  test('mavlink detail dialog shows node sources, node endpoints, and repo endpoints', async () => {
    getFleetSidecarResponse.mockResolvedValue({ data: mavlinkTable });

    render(<FleetOpsSidecarPage config={MAVLINK_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /mavlink sidecar profiles/i });
    expect(await screen.findByRole('link', { name: /open P1\|H1 mavlink anywhere dashboard/i })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /view P1\|H1 profile details/i }));

    expect(screen.getByRole('dialog', { name: /node mavlink overlay: P1\|H1/i })).toBeInTheDocument();
    expect(screen.getAllByRole('link', { name: /open P1\|H1 mavlink anywhere dashboard/i })[0]).toHaveAttribute(
      'href',
      'http://198.51.100.11:9070/'
    );
    expect(screen.getByText('Node MAVLink Differences')).toBeInTheDocument();
    expect(screen.getByText('Repo MAVLink Baseline')).toBeInTheDocument();
    expect(screen.getByText('MAVLink input sources')).toBeInTheDocument();
    expect(screen.getByText('px4')).toBeInTheDocument();
    expect(screen.getByText('/dev/ttyS0 @ 921600')).toBeInTheDocument();
    expect(screen.getByText('gcs_vpn')).toBeInTheDocument();
    expect(screen.getByText('gcs_ops')).toBeInTheDocument();
  });

  test('requires dry-run token acknowledgement before reconcile apply', async () => {
    dryRunFleetSidecarReconcileResponse.mockResolvedValue({
      data: {
        schema: 'mds.sidecar_profile.v1',
        job_id: 'dryrun-1',
        kind: 'reconcile-dry-run',
        sidecar: 'smart-wifi-manager',
        mode: 'fleet-merge',
        node_ids: ['1'],
        baseline_hash: 'abcdef123456',
        confirmation_token: 'confirm-token',
        results: {
          1: { ok: true, result: { dry_run_id: 'node-dryrun-1' } },
        },
      },
    });
    applyFleetSidecarReconcileResponse.mockResolvedValue({
      data: {
        schema: 'mds.sidecar_profile.v1',
        job_id: 'dryrun-1',
        sidecar: 'smart-wifi-manager',
        applied: true,
        results: { 1: { ok: true } },
      },
    });

    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i });
    fireEvent.click(await screen.findByLabelText(/select P1\|H1/i));
    fireEvent.click(screen.getByRole('button', { name: /dry-run reconcile/i }));

    await waitFor(() => {
      expect(dryRunFleetSidecarReconcileResponse).toHaveBeenCalledWith(
        'smart-wifi-manager',
        { node_ids: ['1'], mode: 'fleet-merge' }
      );
    });
    expect(await screen.findByRole('dialog', { name: /reconcile-dry-run/i })).toBeInTheDocument();

    const applyButton = screen.getByRole('button', { name: /apply reconcile/i });
    expect(applyButton).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/acknowledge risks/i));
    fireEvent.change(screen.getByLabelText(/type dry-run confirmation token/i), {
      target: { value: 'confirm-token' },
    });
    expect(applyButton).not.toBeDisabled();
    fireEvent.click(applyButton);

    await waitFor(() => {
      expect(applyFleetSidecarReconcileResponse).toHaveBeenCalledWith(
        'smart-wifi-manager',
        {
          dry_run_id: 'dryrun-1',
          confirmation: {
            acknowledged_risks: true,
            advanced_strict_ack: false,
            confirmation_token: 'confirm-token',
            operator: 'dashboard',
          },
        }
      );
    });
  });

  test('keeps observe and local modes inspect-only for reconcile', async () => {
    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i });
    fireEvent.click(await screen.findByLabelText(/select P1\|H1/i));
    fireEvent.change(screen.getByLabelText(/^mode$/i), { target: { value: 'local' } });

    const reconcileButton = screen.getByRole('button', { name: /dry-run reconcile/i });
    expect(reconcileButton).toBeDisabled();
    expect(reconcileButton).toHaveAttribute('title', expect.stringContaining('inspect-only'));
    expect(dryRunFleetSidecarReconcileResponse).not.toHaveBeenCalled();
  });

  test('promote draft is confirmation-gated and does not mutate repo baseline', async () => {
    promoteFleetSidecarDraftResponse.mockResolvedValue({
      data: {
        schema: 'mds.sidecar_profile.v1',
        sidecar: 'smart-wifi-manager',
        node_id: '1',
        mutated_repo_baseline: false,
        draft: {
          summary: {
            hash: 'draft12345678',
            profile_count: 1,
            profiles: [{ id: 'field-primary', ssid: 'Demo Field', secret_status: 'redacted' }],
          },
        },
      },
    });

    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    await screen.findByRole('heading', { name: /wi-fi sidecar profiles/i });
    fireEvent.click(await screen.findByLabelText(/select P1\|H1/i));
    fireEvent.click(screen.getByRole('button', { name: /promote draft/i }));

    expect(screen.getByRole('dialog', { name: /promote reference draft/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /generate draft/i })).toBeDisabled();
    fireEvent.click(screen.getByLabelText(/acknowledge reference selection/i));
    fireEvent.change(screen.getByLabelText(/type promote/i), { target: { value: 'PROMOTE' } });
    fireEvent.click(screen.getByRole('button', { name: /generate draft/i }));

    await waitFor(() => {
      expect(promoteFleetSidecarDraftResponse).toHaveBeenCalledWith(
        'smart-wifi-manager',
        { node_id: '1' }
      );
    });
    expect(await screen.findByText(/repo baseline mutated/i)).toBeInTheDocument();
    expect(screen.getByText('no')).toBeInTheDocument();
  });

  test('clearing ops token removes persistent stale browser token values', async () => {
    window.sessionStorage.setItem('fleetOpsMutationToken', 'session-token');
    window.localStorage.setItem('fleetOpsMutationToken', 'stale-token');

    render(<FleetOpsSidecarPage config={SMART_WIFI_SIDECAR_CONFIG} />);

    const tokenInput = await screen.findByLabelText(/fleet ops mutation token/i);
    expect(tokenInput).toHaveValue('session-token');
    fireEvent.change(tokenInput, { target: { value: '' } });

    expect(window.sessionStorage.getItem('fleetOpsMutationToken')).toBeNull();
    expect(window.localStorage.getItem('fleetOpsMutationToken')).toBeNull();
  });
});
