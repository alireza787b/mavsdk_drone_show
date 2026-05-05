import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import DroneGitStatus from './DroneGitStatus';

describe('DroneGitStatus', () => {
  const baseProps = {
    droneName: 'Drone 101',
    gcsGitStatus: { commit: 'abc12345' },
    gitStatus: {
      branch: 'main',
      commit: 'abc12345',
      status: 'clean',
      in_sync_with_gcs: true,
      repo_access_mode: 'https_token_file',
      git_auth_health_status: 'healthy',
      git_auth_health_summary: 'Healthy',
      git_auth_health_issues: [],
      mavlink_runtime: {
        management_mode: 'managed',
        ref: 'v3.0.5',
        repo_web_url: 'https://github.com/demo/mavlink-anywhere/tree/v3.0.5',
        router_service_status: 'active',
        dashboard_enabled: true,
        dashboard_access_mode: 'direct',
        dashboard_url: 'http://10.0.0.101:9070',
      },
      connectivity_runtime: {
        backend: 'smart-wifi-manager',
        mode: 'observe',
        service_status: 'active',
        repo_web_url: 'https://github.com/demo/smart-wifi-manager/tree/v2.1.6',
        dashboard_access_mode: 'local_only',
        dashboard_url: null,
      },
      git_sync_runtime: {
        status: 'success',
        summary: 'Git synchronization completed successfully · Coordinator restart scheduled',
        updated_units: ['coordinator.service'],
      },
    },
  };

  it('renders managed runtime summaries and reachable dashboard links when expanded', () => {
    render(<DroneGitStatus {...baseProps} />);

    fireEvent.click(screen.getByRole('button', { name: /toggle details/i }));

    expect(screen.getByText(/managed · v3.0.5 · router active · dashboard direct link/i)).toBeInTheDocument();
    expect(screen.getByText(/smart-wifi-manager · observe · service active · dashboard local only/i)).toBeInTheDocument();
    expect(screen.getByText(/git synchronization completed successfully · coordinator restart scheduled/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /dashboard/i })).toHaveAttribute('href', 'http://10.0.0.101:9070');
  });
});
