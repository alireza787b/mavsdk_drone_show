import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import RuntimeAdminPage from './RuntimeAdminPage';
import useGcsRuntimeStatus from '../hooks/useGcsRuntimeStatus';

const mockSaveGcsConfigResponse = jest.fn();
const mockApplyGcsConfigResponse = jest.fn();

jest.mock('../hooks/useGcsGitInfo', () => jest.fn(() => ({
  repo: 'demo/customer-mds',
  branch: 'customer-demo',
  commit: 'abcdef12',
})));

jest.mock('../hooks/useGcsRuntimeStatus', () => jest.fn(() => ({
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
})));

jest.mock('../services/gcsApiService', () => ({
  saveGcsConfigResponse: (...args) => mockSaveGcsConfigResponse(...args),
  applyGcsConfigResponse: (...args) => mockApplyGcsConfigResponse(...args),
}));

describe('RuntimeAdminPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders live runtime posture and doc links', () => {
    render(
      <MemoryRouter>
        <RuntimeAdminPage />
      </MemoryRouter>
    );

    expect(screen.getByRole('heading', { name: /runtime admin/i })).toBeInTheDocument();
    expect(screen.getByText('REAL')).toBeInTheDocument();
    expect(screen.getByText('/opt/demo-gcs')).toBeInTheDocument();
    expect(screen.getByText('smart-wifi-manager')).toBeInTheDocument();
    expect(screen.getByText(/https token-file access is configured and readable/i)).toBeInTheDocument();
    expect(screen.getByText('/opt/demo-mavlink')).toBeInTheDocument();
    expect(screen.getByText('/tmp/demo-profile.json')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /bootstrap guide/i })).toHaveAttribute(
      'href',
      'https://github.com/demo/customer-mds/blob/customer-demo/docs/guides/mds-init-setup.md'
    );
    expect(screen.getByRole('link', { name: /open mavlink-anywhere repo/i })).toHaveAttribute(
      'href',
      'https://github.com/demo/mavlink-anywhere/tree/v9.9.9'
    );
    expect(screen.getAllByRole('link', { name: /open local dashboard/i })[0]).toHaveAttribute(
      'href',
      'http://localhost:9070/'
    );
    expect(screen.getAllByRole('link', { name: /open local dashboard/i })[1]).toHaveAttribute(
      'href',
      'http://localhost:9080/'
    );
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
      <MemoryRouter>
        <RuntimeAdminPage />
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

    expect(screen.getByText(/restart the gcs runtime to apply them/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /apply persisted runtime settings with restart/i }));

    await waitFor(() => {
      expect(mockApplyGcsConfigResponse).toHaveBeenCalledTimes(1);
    });

    expect(screen.getByText(/gcs restart scheduled/i)).toBeInTheDocument();
  });

  test('warns when switching toward REAL while local SITL containers still exist', () => {
    useGcsRuntimeStatus.mockReturnValueOnce({
      ...useGcsRuntimeStatus(),
      mode: 'sitl',
      modeLabel: 'SITL',
      configuredMode: 'real',
      configuredModeLabel: 'REAL',
      restartRequired: true,
      sitlInstanceCount: 2,
    });

    render(
      <MemoryRouter>
        <RuntimeAdminPage />
      </MemoryRouter>
    );

    expect(screen.getByText(/2 local SITL instance\(s\) are still running/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open sitl control/i })).toHaveAttribute('href', '/sitl-control');
  });
});
