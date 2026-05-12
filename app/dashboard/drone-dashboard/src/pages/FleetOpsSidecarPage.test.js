import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import FleetOpsSidecarPage, { SMART_WIFI_SIDECAR_CONFIG } from './FleetOpsSidecarPage';
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
      presence: { state: 'online', age_seconds: 1 },
      service_state: 'active',
      installed_ref: 'v2.1.10',
      mode: 'fleet-merge',
      profile_source: 'node-local',
      desired_hash: 'abcdef1234567890',
      local_hash: 'abcdef1234567890',
      drift_state: 'in_sync',
      profile_count: 1,
      dashboard: { url: 'http://198.51.100.11:9080/' },
      last_apply_result: { status: 'success' },
    },
    {
      hw_id: '2',
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
    expect(await screen.findByLabelText(/select drone 2/i)).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: /baseline/i }));

    expect(screen.getByRole('dialog', { name: /repo wi-fi baseline/i })).toBeInTheDocument();
    expect(screen.getByText('Demo Field')).toBeInTheDocument();
    expect(screen.getByText('secret:stored')).toBeInTheDocument();
    expect(screen.queryByText(/redacted-demo-value/i)).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByLabelText(/select drone 1/i));
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
    fireEvent.click(await screen.findByLabelText(/select drone 1/i));
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
    fireEvent.click(await screen.findByLabelText(/select drone 1/i));
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
