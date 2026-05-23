import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockGetEnvRegistryResponse = jest.fn();
const mockGetGcsEnvResponse = jest.fn();
const mockGetUnifiedGitStatusResponse = jest.fn();
const mockGetFleetNodeEnvResponse = jest.fn();
const mockUpdateGcsEnvResponse = jest.fn();
const mockUpdateFleetNodeEnvResponse = jest.fn();
const mockApplyGcsEnvResponse = jest.fn();

jest.mock('../services/gcsApiService', () => ({
  getEnvRegistryResponse: (...args) => mockGetEnvRegistryResponse(...args),
  getGcsEnvResponse: (...args) => mockGetGcsEnvResponse(...args),
  getUnifiedGitStatusResponse: (...args) => mockGetUnifiedGitStatusResponse(...args),
  getFleetNodeEnvResponse: (...args) => mockGetFleetNodeEnvResponse(...args),
  updateGcsEnvResponse: (...args) => mockUpdateGcsEnvResponse(...args),
  updateFleetNodeEnvResponse: (...args) => mockUpdateFleetNodeEnvResponse(...args),
  applyGcsEnvResponse: (...args) => mockApplyGcsEnvResponse(...args),
}));

const EnvironmentsPage = require('./EnvironmentsPage').default;

const originalCreateObjectURL = URL.createObjectURL;
const originalRevokeObjectURL = URL.revokeObjectURL;
const originalAnchorClick = HTMLAnchorElement.prototype.click;

const registryPayload = {
  version: 1,
  registry_hash: 'abc123456789def',
  entries: [],
};

const envPayload = {
  config_path: '/etc/mds/gcs.env',
  config_present: true,
  registry_version: 1,
  registry_hash: 'abc123456789def',
  unknown_keys: ['OLD_PORT'],
  deprecated_keys: [],
  warnings: ['This GCS env file contains unregistered keys.'],
  values: [
    {
      name: 'MDS_MODE',
      title: 'Runtime mode',
      scope: 'gcs',
      domain: 'runtime',
      value_type: 'string',
      value: 'sitl',
      value_present: true,
      secret: false,
      secret_configured: false,
      default: 'sitl',
      editable: true,
      ui_visibility: 'operator',
      restart_required: 'gcs',
      apply_action: 'restart_gcs',
      allowed_values: ['real', 'sitl'],
      docs: 'docs/guides/runtime-config-sources.md',
      deprecated: false,
      replacement: null,
      notes: 'Host-local runtime mode.',
    },
    {
      name: 'MDS_AUTH_ENABLED',
      title: 'Dashboard auth',
      scope: 'gcs',
      domain: 'auth',
      value_type: 'boolean',
      value: 'false',
      value_present: true,
      secret: false,
      secret_configured: false,
      default: false,
      editable: true,
      ui_visibility: 'operator',
      restart_required: 'gcs',
      apply_action: 'restart_gcs',
      allowed_values: [true, false],
      docs: 'docs/guides/gcs-auth.md',
      deprecated: false,
      replacement: null,
      notes: '',
    },
    {
      name: 'MDS_AUTH_USERS_FILE',
      title: 'Auth users file',
      scope: 'gcs',
      domain: 'auth',
      value_type: 'path',
      value: '/etc/mds/auth/users.json',
      value_present: true,
      secret: false,
      secret_configured: false,
      default: '/etc/mds/auth/users.json',
      editable: true,
      ui_visibility: 'advanced',
      restart_required: 'gcs',
      apply_action: 'restart_gcs',
      allowed_values: [],
      docs: 'docs/guides/gcs-auth.md',
      deprecated: false,
      replacement: null,
      notes: '',
    },
    {
      name: 'MDS_AGENT_ACTION_CIRCUIT_BREAKER',
      title: 'Simurgh non-action circuit breaker',
      scope: 'agent',
      domain: 'agent',
      source_of_truth: '/etc/mds/gcs.env',
      value_type: 'boolean',
      value: 'true',
      value_present: true,
      secret: false,
      secret_configured: false,
      default: true,
      editable: true,
      ui_visibility: 'operator',
      restart_required: 'gcs',
      apply_action: 'restart_gcs',
      allowed_values: [true, false],
      docs: 'docs/guides/simurgh-operator.md',
      deprecated: false,
      replacement: null,
      notes: 'Primary field safety switch.',
    },
  ],
};

const fleetPayload = {
  git_status: {
    1: {
      pos_id: 1,
      hw_id: '1',
      ip: '192.0.2.10',
      env_runtime: {
        status_source: 'registry',
        registry_version: 1,
        registry_hash: 'abc123456789def',
        local_env_path: '/etc/mds/local.env',
        local_env_present: true,
        node_identity_path: '/etc/mds/node_identity.json',
        node_identity_present: true,
        runtime_mode: 'real',
        runtime_mode_source: 'env:MDS_MODE',
        hw_id: 1,
        hw_id_source: 'env:MDS_HW_ID',
        configured_key_count: 7,
        configured_node_key_count: 5,
        registered_node_key_count: 20,
        unknown_keys: [],
        deprecated_keys: [],
        warnings: [],
      },
    },
  },
};

const nodeEnvPayload = {
  hw_id: '1',
  endpoint: 'http://192.0.2.10:7070/api/v1/system/env',
  reachable: true,
  config_path: '/etc/mds/local.env',
  config_present: true,
  registry_version: 1,
  registry_hash: 'abc123456789def',
  unknown_keys: [],
  deprecated_keys: [],
  summary: fleetPayload.git_status[1].env_runtime,
  warnings: [],
  values: [
    {
      name: 'MDS_CONNECTIVITY_BACKEND',
      title: 'Connectivity backend',
      scope: 'node',
      domain: 'connectivity',
      source_of_truth: '/etc/mds/local.env',
      value_type: 'string',
      value: 'smart-wifi-manager',
      value_present: true,
      secret: false,
      secret_configured: false,
      default: 'none',
      editable: true,
      ui_visibility: 'operator',
      restart_required: 'node_service',
      apply_action: 'restart_node_service',
      allowed_values: ['none', 'smart-wifi-manager'],
      docs: 'docs/guides/connectivity-runtime.md',
      deprecated: false,
      replacement: null,
      notes: 'Optional connectivity sidecar.',
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
      <EnvironmentsPage />
    </MemoryRouter>
  );
}

describe('EnvironmentsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    URL.createObjectURL = jest.fn(() => 'blob:env-profile');
    URL.revokeObjectURL = jest.fn();
    HTMLAnchorElement.prototype.click = jest.fn();
    mockGetEnvRegistryResponse.mockResolvedValue({ data: registryPayload });
    mockGetGcsEnvResponse.mockResolvedValue({ data: envPayload });
    mockGetUnifiedGitStatusResponse.mockResolvedValue({ data: fleetPayload });
    mockGetFleetNodeEnvResponse.mockResolvedValue({ data: nodeEnvPayload });
    mockUpdateGcsEnvResponse.mockResolvedValue({
      data: {
        success: true,
        changed_keys: ['MDS_MODE'],
        restart_required: true,
        config_path: '/etc/mds/gcs.env',
      },
    });
    mockUpdateFleetNodeEnvResponse.mockResolvedValue({
      data: {
        success: true,
        changed_keys: ['MDS_CONNECTIVITY_BACKEND'],
        restart_required: true,
        config_path: '/etc/mds/local.env',
      },
    });
    mockApplyGcsEnvResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'scheduled',
        message: 'GCS restart scheduled.',
        scheduled: true,
        restart_delay_ms: 2000,
      },
    });
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    HTMLAnchorElement.prototype.click = originalAnchorClick;
  });

  test('renders registry-backed GCS environment posture', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { level: 1, name: /environments/i })).toBeInTheDocument();
    expect(await screen.findByText('/etc/mds/gcs.env')).toBeInTheDocument();
    expect(await screen.findByText('Runtime mode')).toBeInTheDocument();
    expect(screen.getByText('Simurgh non-action circuit breaker')).toBeInTheDocument();
    expect(screen.getByText('Dashboard auth')).toBeInTheDocument();
    expect(screen.queryByText('Auth users file')).not.toBeInTheDocument();
    expect(screen.getByText(/unregistered keys/i)).toBeInTheDocument();
  });

  test('shows advanced variables and persists a GCS env edit', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /advanced/i }));
    expect(screen.getByText('Auth users file')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /edit mds_mode/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /^value$/i }), { target: { value: 'real' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockUpdateGcsEnvResponse).toHaveBeenCalledWith({ updates: { MDS_MODE: 'real' } });
    });
    expect(await screen.findByText(/apply pending/i)).toBeInTheDocument();
  });

  test('identifies which environment metadata endpoint failed', async () => {
    mockGetEnvRegistryResponse.mockResolvedValueOnce({ data: registryPayload });
    mockGetGcsEnvResponse.mockRejectedValueOnce(new Error('server exploded'));

    renderPage();

    expect(await screen.findByText('Environment registry unavailable')).toBeInTheDocument();
    expect(screen.getByText(/GCS env: server exploded/i)).toBeInTheDocument();
  });

  test('schedules the GCS env apply restart', async () => {
    renderPage();

    await screen.findByText('Runtime mode');
    fireEvent.click(await screen.findByRole('button', { name: /apply gcs environment restart/i }));

    await waitFor(() => {
      expect(mockApplyGcsEnvResponse).toHaveBeenCalledTimes(1);
    });
    expect(await screen.findByText(/gcs restart scheduled/i)).toBeInTheDocument();
  });

  test('exports a registry-safe GCS env profile', async () => {
    renderPage();

    await screen.findByText('Runtime mode');
    const exportButtons = await screen.findAllByRole('button', { name: /export gcs env profile/i });
    fireEvent.click(exportButtons[0]);

    expect(URL.createObjectURL).toHaveBeenCalledTimes(1);
    expect(await screen.findByText(/gcs env profile exported/i)).toBeInTheDocument();
  });

  test('dry-runs then imports a GCS env profile', async () => {
    renderPage();

    const profile = {
      version: 1,
      kind: 'mds-env-profile',
      scope: 'gcs',
      entries: {
        MDS_MODE: 'real',
      },
    };
    const file = new File([JSON.stringify(profile)], 'profile.json', { type: 'application/json' });

    fireEvent.change(await screen.findByLabelText(/import gcs env profile file/i), {
      target: { files: [file] },
    });

    await waitFor(() => {
      expect(mockUpdateGcsEnvResponse).toHaveBeenCalledWith({
        updates: { MDS_MODE: 'real' },
        dry_run: true,
      });
    });

    fireEvent.click(await screen.findByRole('button', { name: /^import$/i }));

    await waitFor(() => {
      expect(mockUpdateGcsEnvResponse).toHaveBeenCalledWith({ updates: { MDS_MODE: 'real' } });
    });
  });

  test('shows and edits selected fleet node env values', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /fleet nodes/i }));

    expect((await screen.findAllByText(/hw 1/i)).length).toBeGreaterThan(0);
    expect(screen.getByText('real')).toBeInTheDocument();
    expect(screen.getByText('5/20')).toBeInTheDocument();
    expect(screen.getByText(/identity ok/i)).toBeInTheDocument();
    expect(await screen.findByText('Connectivity backend')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /edit mds_connectivity_backend/i }));
    fireEvent.change(screen.getByRole('combobox', { name: /^value$/i }), { target: { value: 'none' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));

    await waitFor(() => {
      expect(mockUpdateFleetNodeEnvResponse).toHaveBeenCalledWith('1', {
        updates: { MDS_CONNECTIVITY_BACKEND: 'none' },
      });
    });
  });
});
