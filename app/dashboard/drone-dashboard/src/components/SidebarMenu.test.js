import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('../hooks/useTheme', () => ({
  __esModule: true,
  useTheme: jest.fn(() => ({ isDark: false })),
}));

jest.mock('../hooks/useGcsGitInfo', () => ({
  __esModule: true,
  default: jest.fn(() => ({})),
}));

jest.mock('./ThemeToggle', () => jest.fn(() => <div>Theme toggle</div>));
jest.mock('./CurrentTime', () => jest.fn(() => <span>12:00</span>));
jest.mock('./GitInfo', () => jest.fn(() => <div>Git info</div>));

const SidebarMenu = require('./SidebarMenu').default;

const baseGitInfo = {
  repo: 'demo/customer-mds',
  runtimeLabel: 'main · abcdef1',
};

const baseTheme = {
  isDark: false,
};

const renderSidebar = (ui) => render(
  <MemoryRouter
    future={{
      v7_startTransition: true,
      v7_relativeSplatPath: true,
    }}
  >
    {ui}
  </MemoryRouter>
);

describe('SidebarMenu', () => {
  it('shows the runtime badge in expanded mode', () => {
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
        runtimeStatus={{
          mode: 'real',
          modeLabel: 'REAL',
          configuredMode: 'sitl',
          configuredModeLabel: 'SITL',
          restartRequired: true,
        }}
      />
    );

    expect(screen.getByLabelText(/real runtime, configured sitl, restart required/i)).toBeInTheDocument();
    expect(screen.getByText('demo/customer-mds')).toBeInTheDocument();
    expect(screen.queryByText('Running REAL')).not.toBeInTheDocument();
    expect(screen.queryByText('Configured SITL')).not.toBeInTheDocument();
    expect(screen.queryByText('Restart pending')).not.toBeInTheDocument();
    expect(screen.getByText('Apply')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /fleet ops/i })).toHaveAttribute('href', '/fleet-ops');
    expect(screen.getByRole('link', { name: /open gcs runtime to review runtime mode/i })).toHaveAttribute('href', '/runtime-admin');
  });

  it('keeps the runtime badge visible in collapsed mode', () => {
    renderSidebar(
      <SidebarMenu
        collapsed
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
        runtimeStatus={{
          mode: 'real',
          modeLabel: 'REAL',
          configuredMode: 'sitl',
          configuredModeLabel: 'SITL',
          restartRequired: true,
        }}
      />
    );

    expect(screen.getByLabelText(/real runtime, configured sitl, restart required/i)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /open gcs runtime to review runtime mode/i })).toHaveAttribute('href', '/runtime-admin');
    expect(screen.getByRole('link', { name: /fleet ops/i })).toHaveAttribute('href', '/fleet-ops');
    expect(screen.getByRole('button', { name: /show git status hint/i })).not.toHaveAttribute('title');
  });

  it('opens a compact signed-in user profile from the sidebar', () => {
    const onChangePassword = jest.fn().mockResolvedValue({});
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
        authStatus={{
          dashboard_auth_enabled: true,
          api_auth_enabled: false,
          session_ttl_hours: 12,
        }}
        currentUser={{
          username: 'admin',
          role: 'admin',
          password_changed_at: '2026-04-29T00:00:00Z',
        }}
        onChangePassword={onChangePassword}
        onLogout={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /open profile for admin/i }));

    const dialog = screen.getByRole('dialog', { name: /signed-in user profile/i });
    expect(dialog).toBeInTheDocument();
    expect(dialog.closest('.modern-sidebar-wrapper')).toBeNull();
    expect(within(dialog).getByText('admin', { selector: 'strong' })).toBeInTheDocument();
    expect(within(dialog).getByText('admin', { selector: 'span' })).toBeInTheDocument();
    expect(screen.queryByLabelText(/current/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /change password/i }));
    expect(screen.getByLabelText(/current/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/current password/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/^new password$/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/confirm new password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /save password/i })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /security/i })).toHaveAttribute('href', '/runtime-admin');
    expect(screen.getByRole('link', { name: /logs/i })).toHaveAttribute('href', '/logs');
  });

  it('shows compact project footer links in expanded mode', () => {
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
      />
    );

    expect(screen.getByRole('link', { name: /alireza ghaderi/i })).toHaveAttribute('href', 'https://joomtalk.ir/');
    expect(screen.getByRole('link', { name: /open linkedin profile/i })).toHaveAttribute('href', 'https://linkedin.com/in/alireza787b');
  });
});
