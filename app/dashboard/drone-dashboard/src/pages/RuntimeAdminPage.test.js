import React from 'react';
import { render, screen } from '@testing-library/react';

import RuntimeAdminPage from './RuntimeAdminPage';

jest.mock('../hooks/useGcsGitInfo', () => jest.fn(() => ({
  repo: 'demo/customer-mds',
  branch: 'customer-demo',
  commit: 'abcdef12',
})));

jest.mock('../hooks/useGcsRuntimeStatus', () => jest.fn(() => ({
  error: null,
  mode: 'real',
  modeLabel: 'REAL',
  modeSource: 'env:MDS_MODE',
  repoAccessMode: 'https_token_file',
  gitAutoPush: false,
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

describe('RuntimeAdminPage', () => {
  test('renders live runtime posture and doc links', () => {
    render(<RuntimeAdminPage />);

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
  });
});
