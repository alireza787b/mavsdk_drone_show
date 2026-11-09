import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useTheme } from '../hooks/useTheme';
import useGcsGitInfo from '../hooks/useGcsGitInfo';
import { VERSION_DISPLAY } from '../version';

jest.mock('../hooks/useTheme', () => ({
  __esModule: true,
  useTheme: jest.fn(() => ({ isDark: false })),
}));

jest.mock('../hooks/useGcsGitInfo', () => ({
  __esModule: true,
  default: jest.fn(() => ({})),
}));

const SidebarMenu = require('./SidebarMenu').default;

const baseGitInfo = {
  repo: 'example/mds',
  branch: 'main',
  commit: 'abcdef1',
  runtimeLabel: 'main · abcdef1',
  raw: { author_name: 'Example maintainer', commit_date: '2026-11-09T12:00:00Z', commit_message: 'Example checkpoint', uncommitted_changes: ['example.js'] },
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

beforeEach(() => {
  jest.clearAllMocks();
  useTheme.mockReturnValue({ isDark: false, themePreference: 'light', getThemeLabel: () => 'Light',
    setTheme: jest.fn(), toggleTheme: jest.fn(), cycleTheme: jest.fn() });
  useGcsGitInfo.mockReturnValue(baseGitInfo);
});

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
    expect(screen.queryByText('example/mds')).not.toBeInTheDocument();
    expect(screen.getByText(VERSION_DISPLAY)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'System / About' })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Running REAL')).not.toBeInTheDocument();
    expect(screen.queryByText('Configured SITL')).not.toBeInTheDocument();
    expect(screen.queryByText('Restart pending')).not.toBeInTheDocument();
    expect(screen.getByText('Apply')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /fleet ops/i })).toHaveAttribute('href', '/fleet-ops');
    expect(screen.getByRole('link', { name: /simurgh/i })).toHaveAttribute('href', '/simurgh');
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
    expect(screen.getByRole('button', { name: 'System / About' })).not.toHaveAttribute('title');
    expect(screen.getByText(VERSION_DISPLAY)).toBeInTheDocument();
  });

  it('groups operator workflows into focused navigation sections', () => {
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
      />
    );

    const operateSection = screen.getByText('Operate').closest('.nav-section');
    const operateLabels = within(operateSection).getAllByRole('link').map((link) => link.textContent);

    expect(operateLabels).toEqual([
      'Overview',
      'Mission Config',
      'Smart Swarm',
      'Drone Show',
    ]);

    const planSection = screen.getByText('Plan').closest('.nav-section');
    const planLabels = within(planSection).getAllByRole('link').map((link) => link.textContent);

    expect(planLabels).toEqual([
      'QuickScout SAR',
      'Swarm Trajectory',
      'Custom CSV Show',
    ]);
    expect(within(operateSection).getByRole('link', { name: 'Smart Swarm' })).toHaveAttribute('href', '/swarm-design');
    expect(within(planSection).getByRole('link', { name: 'QuickScout SAR' })).toHaveAttribute('href', '/quickscout');
    expect(within(planSection).queryByRole('link', { name: 'Route Editor' })).not.toBeInTheDocument();
  });

  it('ports collapsed sidebar tooltips outside the scroll container and avoids stale hover timers', () => {
    jest.useFakeTimers();
    renderSidebar(
      <SidebarMenu
        collapsed
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
      />
    );

    const quickScout = screen.getByRole('link', { name: 'QuickScout SAR' });
    const routeEditor = screen.getByRole('link', { name: 'Swarm Trajectory' });

    fireEvent.mouseEnter(quickScout);
    expect(screen.getByRole('tooltip')).toHaveTextContent('QuickScout SAR');
    expect(screen.getByRole('tooltip').closest('.modern-sidebar-wrapper')).toBeNull();

    fireEvent.mouseEnter(routeEditor);
    expect(screen.getByRole('tooltip')).toHaveTextContent('Swarm Trajectory');
    act(() => {
      jest.advanceTimersByTime(1999);
    });
    expect(screen.getByRole('tooltip')).toHaveTextContent('Swarm Trajectory');

    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
    jest.useRealTimers();
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
    expect(within(dialog).getByRole('link', { name: /security/i })).toHaveAttribute('href', '/runtime-admin');
    expect(within(dialog).getByRole('link', { name: /logs/i })).toHaveAttribute('href', '/logs');
  });

  it('shows the signed-in user profile when only API auth is enabled', () => {
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
        authStatus={{
          dashboard_auth_enabled: false,
          api_auth_enabled: true,
          session_ttl_hours: 12,
        }}
        currentUser={{
          username: 'operator',
          role: 'operator',
        }}
        onLogout={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: /open profile for operator/i }));

    const dialog = screen.getByRole('dialog', { name: /signed-in user profile/i });
    expect(dialog).toBeInTheDocument();
    expect(within(dialog).getByText('operator', { selector: 'strong' })).toBeInTheDocument();
  });

  it('keeps project links and repository/time diagnostics behind System / About by default', () => {
    renderSidebar(
      <SidebarMenu
        collapsed={false}
        gitInfoOverride={baseGitInfo}
        themeOverride={baseTheme}
      />
    );

    expect(screen.queryByRole('dialog', { name: 'System / About' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /alireza ghaderi/i })).not.toBeInTheDocument();
    expect(document.querySelector('.current-time')).toBeNull();
    const trigger = screen.getByRole('button', { name: 'System / About' });
    trigger.focus();
    fireEvent.click(trigger);
    const about = screen.getByRole('dialog', { name: 'System / About' });
    expect(about.closest('.modern-sidebar-wrapper')).toBeNull();
    expect(within(about).getByText('example/mds')).toBeInTheDocument();
    expect(within(about).getByText('main')).toBeInTheDocument();
    expect(within(about).getByText('abcdef1')).toBeInTheDocument();
    expect(within(about).getByText('Commit details').tagName).toBe('SUMMARY');
    fireEvent.click(within(about).getByText('Commit details'));
    expect(within(about).getByText('Example maintainer')).toBeInTheDocument();
    expect(within(about).getByText('Example checkpoint')).toBeInTheDocument();
    expect(about.querySelector('.current-time .timestamp')).not.toBeNull();
    expect(screen.getByRole('link', { name: /alireza ghaderi/i })).toHaveAttribute('href', 'https://joomtalk.ir/');
    expect(screen.getByRole('link', { name: /open linkedin profile/i })).toHaveAttribute('href', 'https://linkedin.com/in/alireza787b');
    fireEvent.click(within(about).getByRole('button', { name: 'Close System / About' }));
    expect(screen.queryByRole('dialog', { name: 'System / About' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.querySelector('.current-time')).toBeNull();
  });

  it('opens diagnostics from the collapsed sidebar and closes on native Escape cancellation', () => {
    renderSidebar(<SidebarMenu collapsed gitInfoOverride={baseGitInfo} />);
    fireEvent.click(screen.getByRole('button', { name: 'System / About' }));
    expect(screen.getByText('example/mds')).toBeInTheDocument();
    fireEvent(screen.getByRole('dialog', { name: 'System / About' }), new Event('cancel', { bubbles: true, cancelable: true }));
    expect(screen.queryByRole('dialog', { name: 'System / About' })).not.toBeInTheDocument();
  });

  it('preserves every route and keeps optional Simurgh in its separate section', () => {
    renderSidebar(<SidebarMenu collapsed={false} />);
    const routes = within(screen.getByRole('navigation', { name: 'Main navigation' })).getAllByRole('link').map((link) => link.getAttribute('href'));
    expect(routes).toEqual(['/', '/mission-config', '/swarm-design', '/drone-show', '/quickscout', '/swarm-trajectory', '/custom-show', '/fleet-ops', '/fleet-enrollment', '/px4-parameters', '/environments', '/logs', '/globe-view', '/runtime-admin', '/sitl-control', '/simurgh']);
    expect(within(screen.getByText('AI').closest('.nav-section')).getAllByRole('link')).toHaveLength(1);
  });

  it('preserves labeled theme controls and their callbacks', () => {
    renderSidebar(<SidebarMenu collapsed={false} />);
    const group = screen.getByRole('group', { name: 'Display theme selector' });
    expect(within(group).getByRole('button', { name: 'Light' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(within(group).getByRole('button', { name: 'Dark' }));
    expect(useTheme().setTheme).toHaveBeenCalledWith('dark');
  });

  it.each([390, 820, 960])('uses the parent mobile modifier at %spx, hides closed navigation and closes after routing', (width) => {
    const previousWidth = window.innerWidth;
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
    const onNavigate = jest.fn();
    const props = { mobile: true, collapsed: true, onNavigate, gitInfoOverride: baseGitInfo };
    try {
      const view = renderSidebar(<SidebarMenu {...props} mobileOpen={false} />);
      expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument();
      const wrapper = view.container.querySelector('.modern-sidebar-wrapper');
      expect(wrapper).toHaveClass('mobile', 'expanded');
      expect(wrapper).not.toHaveClass('mobile-open');
      view.rerender(<MemoryRouter><SidebarMenu {...props} mobileOpen /></MemoryRouter>);
      expect(wrapper).toHaveClass('mobile-open');
      expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument();
      fireEvent.click(screen.getByRole('link', { name: 'Fleet Ops' }));
      expect(onNavigate).toHaveBeenCalledTimes(1);
    } finally {
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: previousWidth });
    }
  });

  it('keeps password submission and logout callbacks intact', async () => {
    const onChangePassword = jest.fn().mockResolvedValue({}), onLogout = jest.fn();
    renderSidebar(<SidebarMenu collapsed={false} authStatus={{ dashboard_auth_enabled: true }} currentUser={{ username: 'operator', role: 'operator' }} onChangePassword={onChangePassword} onLogout={onLogout} />);
    fireEvent.click(screen.getByRole('button', { name: /open profile for operator/i }));
    const dialog = screen.getByRole('dialog', { name: /signed-in user profile/i });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Change password' }));
    fireEvent.change(screen.getByPlaceholderText('Current password'), { target: { value: 'old-example' } });
    fireEvent.change(screen.getByPlaceholderText('New password'), { target: { value: 'new-example' } });
    fireEvent.change(screen.getByPlaceholderText('Confirm new password'), { target: { value: 'new-example' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save password' }));
    await waitFor(() => expect(within(dialog).getByText('Password updated.')).toBeInTheDocument());
    expect(onChangePassword).toHaveBeenCalledWith({ currentPassword: 'old-example', newPassword: 'new-example' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Log out' }));
    expect(onLogout).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog', { name: /signed-in user profile/i })).not.toBeInTheDocument();
  });
});
