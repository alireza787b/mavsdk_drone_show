import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import App from './App';

// Mock eagerly loaded components
jest.mock('./pages/Overview', () => () => <div data-testid="overview" />);
jest.mock('./pages/MissionConfig', () => () => <div data-testid="mission-config" />);
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
jest.mock('./pages/LogViewer', () => ({ __esModule: true, default: () => <div data-testid="log-viewer" /> }));
jest.mock('./components/DroneDetail', () => ({ __esModule: true, default: () => <div data-testid="drone-detail" /> }));

// Mock services
jest.mock('./services/logService', () => ({
  reportFrontendError: jest.fn().mockResolvedValue({ status: 'received' }),
}));

describe('App', () => {
  const originalInnerWidth = window.innerWidth;

  afterEach(() => {
    window.innerWidth = originalInnerWidth;
  });

  test('renders without crashing', () => {
    render(<App />);
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
  });

  test('renders sidebar navigation', () => {
    render(<App />);
    expect(screen.getByTestId('sidebar')).toBeInTheDocument();
  });

  test('renders default route (Overview)', () => {
    render(<App />);
    expect(screen.getByTestId('overview')).toBeInTheDocument();
  });

  test('uses overlay navigation on mobile viewports', () => {
    window.innerWidth = 375;
    render(<App />);

    const sidebar = screen.getByTestId('sidebar');
    expect(sidebar).toHaveAttribute('data-mobile', 'true');
    expect(sidebar).toHaveAttribute('data-collapsed', 'false');
    expect(sidebar).toHaveAttribute('data-open', 'false');

    fireEvent.click(screen.getByLabelText('Open navigation menu'));
    expect(screen.getByLabelText('Close navigation overlay')).toBeInTheDocument();
    expect(sidebar).toHaveAttribute('data-open', 'true');
  });
});
