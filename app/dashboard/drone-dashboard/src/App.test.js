import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';

// Mock primary routed pages
jest.mock('./pages/Overview', () => ({ __esModule: true, default: () => <div data-testid="overview" /> }));
jest.mock('./pages/MissionConfig', () => ({ __esModule: true, default: () => <div data-testid="mission-config" /> }));
jest.mock('./components/SidebarMenu', () => ({ collapsed, mobile, mobileOpen }) => (
  <nav
    data-testid="sidebar"
    data-collapsed={String(collapsed)}
    data-mobile={String(mobile)}
    data-open={String(mobileOpen)}
  />
));
jest.mock('./components/SyncWarningBanner', () => () => null);
jest.mock('./components/ErrorBoundary', () => ({ children }) => <>{children}</>);
jest.mock('./contexts/CommandActivityContext', () => ({
  CommandActivityProvider: ({ children }) => <>{children}</>,
}));
jest.mock('./hooks/useGcsRuntimeStatus', () => ({
  __esModule: true,
  default: () => ({
    loading: false,
    error: null,
    mode: 'sitl',
    modeLabel: 'SITL',
    configuredMode: 'sitl',
    configuredModeLabel: 'SITL',
    restartRequired: false,
    docs: {},
  }),
}));

// Mock lazy-loaded pages — must return { default: Component } for React.lazy
jest.mock('./pages/SwarmDesign', () => ({ __esModule: true, default: () => <div data-testid="swarm-design" /> }));
jest.mock('./pages/DroneShowDesign', () => ({ __esModule: true, default: () => <div data-testid="drone-show-design" /> }));
jest.mock('./pages/CustomShowPage', () => ({ __esModule: true, default: () => <div data-testid="custom-show" /> }));
jest.mock('./pages/GlobeView', () => ({ __esModule: true, default: () => <div data-testid="globe-view" /> }));
jest.mock('./pages/ManageDroneShow', () => ({ __esModule: true, default: () => <div data-testid="manage-drone-show" /> }));
jest.mock('./pages/SwarmTrajectory', () => ({ __esModule: true, default: () => <div data-testid="swarm-trajectory" /> }));
jest.mock('./pages/TrajectoryPlanning', () => ({ __esModule: true, default: () => <div data-testid="trajectory-planning" /> }));
jest.mock('./pages/QuickScoutPage', () => ({ __esModule: true, default: () => <div data-testid="quickscout" /> }));
jest.mock('./pages/FleetEnrollmentPage', () => ({ __esModule: true, default: () => <div data-testid="fleet-enrollment" /> }));
jest.mock('./pages/SimurghOperatorPage', () => ({ __esModule: true, default: () => <div data-testid="simurgh-operator" /> }));
jest.mock('./pages/LogViewer', () => ({ __esModule: true, default: () => <div data-testid="log-viewer" /> }));
jest.mock('./components/DroneDetail', () => ({ __esModule: true, default: () => <div data-testid="drone-detail" /> }));

// Mock services
jest.mock('./services/logService', () => ({
  reportFrontendError: jest.fn().mockResolvedValue({ status: 'received' }),
}));

jest.mock('./services/gcsApiService', () => {
  const actual = jest.requireActual('./services/gcsApiService');
  return {
    ...actual,
    getAuthStatusResponse: jest.fn().mockResolvedValue({
      data: {
        dashboard_auth_enabled: false,
        api_auth_enabled: false,
        authenticated: false,
      },
    }),
    loginResponse: jest.fn(),
    logoutResponse: jest.fn().mockResolvedValue({ data: { authenticated: false } }),
    setGcsCsrfToken: jest.fn(),
  };
});

describe('App', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    window.innerWidth = originalInnerWidth;
    window.history.pushState({}, '', '/');
  });

  test('renders without crashing', async () => {
    render(<App />);
    expect(await screen.findByTestId('sidebar')).toBeInTheDocument();
    expect(await screen.findByTestId('overview')).toBeInTheDocument();
  });

  test('renders sidebar navigation', async () => {
    render(<App />);
    expect(await screen.findByTestId('sidebar')).toBeInTheDocument();
    expect(await screen.findByTestId('overview')).toBeInTheDocument();
  });

  test('renders default route (Overview)', async () => {
    render(<App />);
    expect(await screen.findByTestId('overview')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /dashboard guide/i })).toHaveAttribute(
      'href',
      expect.stringContaining('/docs/guides/dashboard-operator.md')
    );
  });

  test('uses overlay navigation on mobile viewports', async () => {
    window.innerWidth = 375;
    render(<App />);

    const sidebar = await screen.findByTestId('sidebar');
    expect(sidebar).toHaveAttribute('data-mobile', 'true');
    expect(sidebar).toHaveAttribute('data-collapsed', 'false');
    expect(sidebar).toHaveAttribute('data-open', 'false');

    fireEvent.click(screen.getByLabelText('Open navigation menu'));
    const backdrop = screen.getByLabelText('Close navigation overlay');
    expect(backdrop).toBeInTheDocument();
    expect(backdrop.closest('.mobile-shell-controls')).toBeNull();
    expect(screen.getByLabelText('Close navigation menu').closest('.mobile-shell-controls')).toHaveClass('is-open');
    expect(screen.queryByLabelText('Open GCS Runtime')).not.toBeInTheDocument();
    expect(sidebar).toHaveAttribute('data-open', 'true');
    expect(await screen.findByTestId('overview')).toBeInTheDocument();
  });

  test('routes to the Simurgh Operator dashboard', async () => {
    window.history.pushState({}, '', '/simurgh');
    render(<App />);

    expect(await screen.findByTestId('simurgh-operator')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /simurgh guide/i })).toHaveAttribute(
      'href',
      expect.stringContaining('/docs/guides/simurgh-operator.md')
    );
  });
});
