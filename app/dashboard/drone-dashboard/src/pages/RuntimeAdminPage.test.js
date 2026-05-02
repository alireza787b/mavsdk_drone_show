import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockSaveGcsConfigResponse = jest.fn();
const mockApplyGcsConfigResponse = jest.fn();
const mockApplyRuntimeUpdateResponse = jest.fn();

jest.mock('../hooks/useGcsGitInfo', () => ({
  __esModule: true,
  default: jest.fn(() => ({})),
}));

jest.mock('../hooks/useGcsRuntimeStatus', () => ({
  __esModule: true,
  default: jest.fn(() => ({})),
}));

jest.mock('../contexts/AuthContext', () => ({
  useAuth: () => ({
    dashboardAuthEnabled: false,
    apiAuthEnabled: false,
    role: null,
    user: null,
    status: { dashboard_auth_enabled: false, api_auth_enabled: false },
    logout: jest.fn(),
  }),
}));

jest.mock('../services/gcsApiService', () => ({
  saveGcsConfigResponse: (...args) => mockSaveGcsConfigResponse(...args),
  applyGcsConfigResponse: (...args) => mockApplyGcsConfigResponse(...args),
  applyRuntimeUpdateResponse: (...args) => mockApplyRuntimeUpdateResponse(...args),
  fetchGcsResource: jest.fn().mockResolvedValue({ data: { mode: 'real' } }),
  GCS_ROUTE_KEYS: {
    systemRuntimeStatus: 'systemRuntimeStatus',
  },
  listAuthUsersResponse: jest.fn().mockResolvedValue({ data: { users: [] } }),
  listAuthTokensResponse: jest.fn().mockResolvedValue({ data: { tokens: [] } }),
  createAuthUserResponse: jest.fn(),
  updateAuthUserResponse: jest.fn(),
  createAuthTokenResponse: jest.fn(),
  revokeAuthTokenResponse: jest.fn(),
}));

const RuntimeAdminPage = require('./RuntimeAdminPage').default;
const routerFuture = { v7_relativeSplatPath: true, v7_startTransition: true };

const baseGitInfo = {
  repo: 'demo/customer-mds',
  branch: 'customer-demo',
  commit: 'abcdef12',
};

const baseRuntimeStatus = {
  error: null,
  loading: false,
  mode: 'real',
  modeLabel: 'REAL',
  configuredMode: 'real',
  configuredModeLabel: 'REAL',
  modeSource: 'env:MDS_MODE',
  repoAccessMode: 'https_token_file',
  gitAutoPush: false,
  configuredGitAutoPush: false,
  restartRequired: false,
  sitlInstanceCount: 0,
  installDir: '/opt/demo-gcs',
  gcsConfigPath: '/etc/mds/gcs.env',
  raw: {
    git_auth_token_file: '/root/.mds_git_read_token',
    git_auth_token_file_readable: true,
    git_ssh_key_file: null,
    git_ssh_key_file_readable: false,
  },
  gitAuthHealth: {
    status: 'healthy',
    summary: 'HTTPS token-file access is configured and readable.',
    issues: [],
  },
  repoSyncStatus: {
    branch: 'customer-demo',
    commit: 'abcdef12',
    remote_url: 'https://github.com/demo/customer-mds.git',
    tracking_branch: 'origin/customer-demo',
    status: 'clean',
    commits_ahead: 0,
    commits_behind: 2,
    update_readiness: 'ready_to_fast_forward',
    update_summary: 'Tracking branch is ahead by 2 commit(s); a controlled fast-forward update is available.',
    fast_forward_update_available: true,
  },
  fleetDefaults: {
    profile_id: 'customer-alpha',
    profile_source: 'file:/tmp/deployment.env',
    connectivity_backend: 'smart-wifi-manager',
    smart_wifi_manager_repo_url_https: 'https://github.com/demo/smart-wifi-manager.git',
    smart_wifi_manager_ref: 'v1.2.3',
    smart_wifi_manager_mode: 'manage',
    smart_wifi_manager_import_mode: 'merge',
    smart_wifi_manager_install_dir: '/opt/demo-smartwifi',
    smart_wifi_manager_dashboard_listen: '0.0.0.0:9080',
    smart_wifi_manager_profile_path: 'deployment/connectivity/demo/profile.json',
    mavlink_management_mode: 'managed',
    mavlink_anywhere_repo_url_https: 'https://github.com/demo/mavlink-anywhere.git',
    mavlink_anywhere_ref: 'v9.9.9',
    mavlink_anywhere_install_dir: '/opt/demo-mavlink',
    mavlink_anywhere_dashboard_listen: '0.0.0.0:9070',
    mavlink_anywhere_skip_dashboard: false,
  },
  mavlinkRuntime: {
    management_mode: 'managed',
    ref: 'v9.9.9',
    repo_web_url: 'https://github.com/demo/mavlink-anywhere/tree/v9.9.9',
    install_dir: '/opt/demo-mavlink',
    runtime_present: true,
    router_binary_present: true,
    router_service_status: 'active',
    dashboard_listen: '0.0.0.0:9070',
    dashboard_service_status: 'active',
  },
  connectivityRuntime: {
    backend: 'smart-wifi-manager',
    mode: 'manage',
    ref: 'v1.2.3',
    repo_web_url: 'https://github.com/demo/smart-wifi-manager/tree/v1.2.3',
    install_dir: '/opt/demo-smartwifi',
    profile_path: '/tmp/demo-profile.json',
    profile_present: true,
    dashboard_listen: '0.0.0.0:9080',
    service_status: 'active',
  },
  docs: {
    mds_init_setup: 'https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/mds-init-setup.md',
    fleet_sync_and_secrets: 'https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/fleet-sync-and-secrets.md',
    mavlink_routing_setup: 'https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/mavlink-routing-setup.md',
    git_sync_feature: 'https://github.com/demo/customer-mds/blob/customer-demo/docs/features/git-sync.md',
  },
};

describe('RuntimeAdminPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders live runtime posture and doc links', () => {
    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage runtimeOverride={baseRuntimeStatus} gitInfoOverride={baseGitInfo} />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { level: 1, name: /gcs runtime/i })).toBeInTheDocument();
    expect(screen.getByText(/gcs host/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open fleet ops/i })).toHaveAttribute('href', '/fleet-ops');
    expect(screen.getByText(/config real/i)).toBeInTheDocument();
    expect(screen.getByText('/opt/demo-gcs')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /host capabilities/i })).toBeInTheDocument();
    expect(screen.getByText('GCS read-only/demo')).toBeInTheDocument();
    expect(screen.getByText('Token file configured')).toBeInTheDocument();
    expect(screen.getByText('smart-wifi-manager')).toBeInTheDocument();
    expect(screen.getByText(/https token-file access is configured and readable/i)).toBeInTheDocument();
    expect(screen.getByText(/tracking branch is ahead by 2 commit\(s\)/i)).toBeInTheDocument();
    expect(screen.queryByText('/root/.mds_git_read_token')).not.toBeInTheDocument();
    expect(screen.queryByText('/opt/demo-mavlink')).not.toBeInTheDocument();
    expect(screen.queryByText('/tmp/demo-profile.json')).not.toBeInTheDocument();
    expect(screen.getByText(/use fleet ops for drone mavlink, smart wi-fi, git auth, profile drift, and sync actions/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run controlled gcs update/i })).toBeEnabled();
    expect(screen.getByRole('link', { name: /bootstrap guide/i })).toHaveAttribute(
      'href',
      'https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/mds-init-setup.md'
    );
    expect(screen.queryByRole('link', { name: /open mavlink-anywhere repo/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /open local dashboard/i })).not.toBeInTheDocument();
  });

  test('persists runtime host config and schedules apply restart', async () => {
    mockSaveGcsConfigResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'success',
        message: 'Host-local GCS settings were persisted. Restart the GCS runtime to apply them.',
        configured_mode: 'sitl',
        configured_git_auto_push: true,
        restart_required: true,
        warnings: [],
      },
    });
    mockApplyGcsConfigResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'scheduled',
        message: 'GCS restart scheduled.',
        configured_mode: 'sitl',
        configured_git_auto_push: true,
        restart_required: true,
        scheduled: true,
        restart_delay_ms: 2000,
        warnings: [],
      },
    });

    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage runtimeOverride={baseRuntimeStatus} gitInfoOverride={baseGitInfo} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: /set runtime mode to sitl/i }));
    fireEvent.click(screen.getByRole('button', { name: /enable git auto-push/i }));
    fireEvent.click(screen.getByRole('button', { name: /save runtime settings/i }));

    await waitFor(() => {
      expect(mockSaveGcsConfigResponse).toHaveBeenCalledWith({
        mode: 'sitl',
        git_auto_push: true,
      });
    });

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /apply persisted runtime settings with restart/i })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole('button', { name: /apply persisted runtime settings with restart/i }));

    await waitFor(() => {
      expect(mockApplyGcsConfigResponse).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(screen.getByText(/gcs restart scheduled/i)).toBeInTheDocument();
    });
  });

  test('can save changed runtime settings and schedule restart from one action', async () => {
    mockSaveGcsConfigResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'success',
        message: 'Host-local GCS settings were persisted. Restart the GCS runtime to apply them.',
        configured_mode: 'sitl',
        configured_git_auto_push: false,
        restart_required: true,
        warnings: [],
      },
    });
    mockApplyGcsConfigResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'scheduled',
        message: 'GCS restart scheduled.',
        configured_mode: 'sitl',
        configured_git_auto_push: false,
        restart_required: true,
        scheduled: true,
        restart_delay_ms: 2000,
        warnings: [],
      },
    });

    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage runtimeOverride={baseRuntimeStatus} gitInfoOverride={baseGitInfo} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: /set runtime mode to sitl/i }));
    fireEvent.click(screen.getByRole('button', { name: /apply runtime changes and restart gcs/i }));

    await waitFor(() => {
      expect(mockSaveGcsConfigResponse).toHaveBeenCalledWith({
        mode: 'sitl',
        git_auto_push: false,
      });
    });
    await waitFor(() => {
      expect(mockApplyGcsConfigResponse).toHaveBeenCalledTimes(1);
    });
  });

  test('runs constrained runtime update when the checkout is fast-forwardable', async () => {
    mockApplyRuntimeUpdateResponse.mockResolvedValue({
      data: {
        success: true,
        status: 'scheduled',
        message: 'Controlled GCS update scheduled.',
        update_readiness: 'ready_to_fast_forward',
        current_commit: 'abcdef12',
        target_commit: 'fedcba98',
        tracking_branch: 'origin/customer-demo',
        pending_paths_count: 3,
        blocked_paths: [],
        scheduled: true,
        restart_delay_ms: 2000,
        warnings: [],
      },
    });

    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage runtimeOverride={baseRuntimeStatus} gitInfoOverride={baseGitInfo} />
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: /run controlled gcs update/i }));

    await waitFor(() => {
      expect(mockApplyRuntimeUpdateResponse).toHaveBeenCalledTimes(1);
    });

    await waitFor(() => {
      expect(screen.getByText(/controlled gcs update scheduled/i)).toBeInTheDocument();
    });
  });

  test('warns when switching toward REAL while local SITL containers still exist', () => {
    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage
          runtimeOverride={{
            ...baseRuntimeStatus,
            mode: 'sitl',
            modeLabel: 'SITL',
            configuredMode: 'real',
            configuredModeLabel: 'REAL',
            restartRequired: true,
            sitlInstanceCount: 2,
          }}
          gitInfoOverride={baseGitInfo}
        />
      </MemoryRouter>
    );

    expect(screen.getByText(/2 local SITL instance\(s\) are still running/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open sitl control/i })).toHaveAttribute('href', '/sitl-control');
  });

  test('disables constrained update when a restart is already pending', () => {
    render(
      <MemoryRouter future={routerFuture}>
        <RuntimeAdminPage
          runtimeOverride={{
            ...baseRuntimeStatus,
            restartRequired: true,
          }}
          gitInfoOverride={baseGitInfo}
        />
      </MemoryRouter>
    );

    expect(screen.getByRole('button', { name: /run controlled gcs update/i })).toBeDisabled();
    expect(screen.getByText(/apply the pending runtime restart before attempting an in-place gcs update/i)).toBeInTheDocument();
  });
});
