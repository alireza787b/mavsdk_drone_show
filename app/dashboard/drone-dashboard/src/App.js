//app/dashboard/drone-dashboard/src/App.js
/**
 * Copyright (c) 2025 Alireza Ghaderi
 * SPDX-License-Identifier: CC-BY-NC-SA-4.0
 *
 * This file is part of MAVSDK Drone Show
 * https://github.com/alireza787b/mavsdk_drone_show
 *
 * Licensed under Creative Commons Attribution-NonCommercial-ShareAlike 4.0
 * For commercial licensing, contact: p30planets@gmail.com
 */

import React, { useEffect, useState, Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom';
import { FaBars, FaTimes } from 'react-icons/fa';

import mdsMark from './assets/mds-mark.svg';

// Import theme system
import { ThemeProvider } from './contexts/ThemeContext';
import { CommandActivityProvider } from './contexts/CommandActivityContext';
import { MapProvider } from './contexts/MapContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import { UlogTransferCenter, UlogTransferProvider } from './components/logs/UlogTransferCenter';
import { ObservationProvider } from './contexts/ObservationContext';
import FleetObservationMonitor from './features/fleet-overview/FleetObservationMonitor';

// Import design tokens first
import './styles/DesignTokens.css';
// Shared operator surfaces have one cascade order, independent of lazy routes.
import './styles/MapCommon.css';
import './styles/SearchBar.css';
import './styles/IdentityDoctrineStrip.css';
import './styles/MissionPlanning.css';
import './styles/PrecisionMoveDialog.css';
import './styles/TakeoffDialog.css';

import SidebarMenu from './components/SidebarMenu';
import RouteDocsShortcut from './components/RouteDocsShortcut';
import SyncWarningBanner from './components/SyncWarningBanner';
import CommandActivityPanel from './components/CommandActivityPanel';
import { FleetAlertsProvider } from './features/fleet-overview/FleetAlertsContext';
import FleetAlertsPanel from './features/fleet-overview/FleetAlertsPanel';
import ErrorBoundary from './components/ErrorBoundary';
import useGcsRuntimeStatus from './hooks/useGcsRuntimeStatus';

// External styles and toast
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import 'leaflet/dist/leaflet.css';
import './App.css';

// Lazy loaded — heavy visualization pages (three.js, plotly, cytoscape, mapbox)
const Overview = lazy(() => import('./pages/Overview'));
const MissionConfig = lazy(() => import('./pages/MissionConfig'));
const SwarmDesign = lazy(() => import('./pages/SwarmDesign'));
const CustomShowWorkspace = lazy(() => import('./pages/CustomShowWorkspace'));
const GlobeView = lazy(() => import('./pages/GlobeView'));
const DroneShowWorkspace = lazy(() => import('./pages/DroneShowWorkspace'));
const SwarmTrajectory = lazy(() => import('./pages/SwarmTrajectoryWorkspace'));
const QuickScoutPage = lazy(() => import('./pages/QuickScoutPage'));
const Px4ParametersPage = lazy(() => import('./pages/Px4ParametersPage'));
const FleetEnrollmentPage = lazy(() => import('./pages/FleetEnrollmentPage'));
const FleetOpsPage = lazy(() => import('./pages/FleetOpsPage'));
const FleetOpsWifiPage = lazy(() => import('./pages/FleetOpsWifiPage'));
const FleetOpsMavlinkPage = lazy(() => import('./pages/FleetOpsMavlinkPage'));
const MaintenancePage = lazy(() => import('./pages/MaintenancePage'));
const LogViewer = lazy(() => import('./pages/LogViewer'));
const SitlControlPage = lazy(() => import('./pages/SitlControlPage'));
const RuntimeAdminPage = lazy(() => import('./pages/RuntimeAdminPage'));
const EnvironmentsPage = lazy(() => import('./pages/EnvironmentsPage'));
const SimurghOperatorPage = lazy(() => import('./pages/SimurghOperatorPage'));
const LoginPage = lazy(() => import('./pages/LoginPage'));

/**
 * Main Application Component
 * Clean routing for dashboard mission planning and operations
 * Now includes unified design system with dynamic sidebar
 */
const MOBILE_BREAKPOINT = 960;

const getIsMobileViewport = () => {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.innerWidth <= MOBILE_BREAKPOINT;
};

function LoadingStatus({ label, standalone = false, onRetry }) {
  return (
    <div className={standalone ? 'app-loading app-loading--standalone' : 'app-loading'} role={onRetry ? undefined : 'status'}>
      <img className="app-loading__mark" src={mdsMark} width="56" height="56" alt="" />
      <span className="app-loading__label" role={onRetry ? 'alert' : undefined}>{label}</span>
      {onRetry
        ? <button className="app-loading__retry" type="button" onClick={onRetry}>Retry</button>
        : <span className="app-loading__indicator" aria-hidden="true" />}
    </div>
  );
}

const AuthGate = ({ children }) => {
  const auth = useAuth();

  if (!auth.hasStatus) {
    if (auth.error && !auth.loading) {
      return (
        <LoadingStatus
          label="Couldn’t connect to the GCS"
          standalone
          onRetry={() => auth.refresh().catch(() => undefined)}
        />
      );
    }
    return <LoadingStatus label="Checking access…" standalone />;
  }

  if (auth.authRequired && !auth.authenticated) {
    return (
      <Suspense fallback={<LoadingStatus label="Opening sign-in…" standalone />}>
        <LoginPage />
      </Suspense>
    );
  }

  return children;
};

const AppShell = () => {
  const [isMobile, setIsMobile] = useState(getIsMobileViewport);
  const [desktopSidebarCollapsed, setDesktopSidebarCollapsed] = useState(getIsMobileViewport);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const runtimeStatus = useGcsRuntimeStatus();
  const auth = useAuth();
  const trustedDemo = auth.status?.dashboard_auth_enabled === false && auth.status?.api_auth_enabled === false;
  const logRole = auth.role || (trustedDemo ? 'operator' : 'viewer');

  useEffect(() => {
    const handleResize = () => {
      const mobileViewport = getIsMobileViewport();
      setIsMobile(mobileViewport);
      if (!mobileViewport) {
        setMobileSidebarOpen(false);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  const handleSidebarToggle = (nextState) => {
    if (isMobile) {
      setMobileSidebarOpen(Boolean(nextState));
      return;
    }

    setDesktopSidebarCollapsed(Boolean(nextState));
  };

  const handleSidebarNavigate = () => {
    if (isMobile) {
      setMobileSidebarOpen(false);
    }
  };

  const sidebarCollapsed = isMobile ? false : desktopSidebarCollapsed;
  const contentClassName = `content ${
    isMobile
      ? 'content-mobile'
      : sidebarCollapsed
        ? 'sidebar-collapsed'
        : 'sidebar-expanded'
  }`;

  return (
    <ObservationProvider key={`${runtimeStatus.mode}:${auth.user?.id || auth.user?.username || 'session'}:${auth.role || ''}`}>
    <CommandActivityProvider>
    <UlogTransferProvider userRole={logRole} runtimeMode={runtimeStatus.mode} operatorId={auth.user?.id || auth.user?.username}>
    <Router
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
      <FleetAlertsProvider key={`${runtimeStatus.mode}:${auth.user?.id || auth.user?.username || 'session'}`}>
              <FleetObservationMonitor />
              <div className={`app-container ${isMobile ? 'app-mobile' : 'app-desktop'}`}>
                {isMobile && (
                  <>
                    <div className={`mobile-shell-controls ${mobileSidebarOpen ? 'is-open' : ''}`}>
                      <button
                        className={`mobile-sidebar-toggle ${mobileSidebarOpen ? 'is-open' : ''}`}
                        onClick={() => setMobileSidebarOpen((current) => !current)}
                        aria-label={mobileSidebarOpen ? 'Close navigation menu' : 'Open navigation menu'}
                      >
                        {mobileSidebarOpen ? <FaTimes /> : <FaBars />}
                      </button>
                    </div>
                    {mobileSidebarOpen && (
                      <button
                        className="sidebar-backdrop"
                        type="button"
                        aria-label="Close navigation overlay"
                        onClick={() => setMobileSidebarOpen(false)}
                      />
                    )}
                  </>
                )}
                <SidebarMenu
                  collapsed={sidebarCollapsed}
                  mobile={isMobile}
                  mobileOpen={mobileSidebarOpen}
                  onNavigate={handleSidebarNavigate}
                  onToggle={handleSidebarToggle}
                  runtimeStatus={runtimeStatus}
                  authStatus={auth.status}
                  currentUser={auth.user}
                  onLogout={auth.logout}
                  onChangePassword={auth.changePassword}
                />
                <div className={contentClassName}>
                  <SyncWarningBanner />
                  <UlogTransferCenter userRole={logRole} />
                  <div className="shell-operations-strip"><CommandActivityPanel /><FleetAlertsPanel /><RouteDocsShortcut /></div>
                  <Suspense fallback={<LoadingStatus label="Opening workspace…" />}>
                    <Routes>
                      {/* Main drone management routes */}
                      <Route path="/drone-show" element={<DroneShowWorkspace runtimeMode={runtimeStatus.mode} />} />
                      <Route path="/drone-show-design" element={<DroneShowWorkspace runtimeMode={runtimeStatus.mode} />} />
                      <Route path="/swarm-design" element={<SwarmDesign />} />
                      <Route path="/mission-config" element={<MissionConfig />} />
                      <Route path="/fleet-enrollment" element={<FleetEnrollmentPage />} />
                      <Route path="/fleet-ops" element={<FleetOpsPage operatorId={auth.user?.id || auth.user?.username || ''} runtimeMode={runtimeStatus.mode} />} />
                      <Route path="/fleet-ops/wifi" element={<FleetOpsWifiPage />} />
                      <Route path="/fleet-ops/mavlink" element={<FleetOpsMavlinkPage />} />
                      <Route path="/maintenance" element={<MaintenancePage />} />
                      <Route path="/drone-detail" element={<Navigate to="/" replace />} />
                      <Route path="/manage-drone-show" element={<DroneShowWorkspace runtimeMode={runtimeStatus.mode} />} />
                      <Route path="/custom-show" element={<CustomShowWorkspace runtimeMode={runtimeStatus.mode} />} />
                      <Route path="/globe-view" element={<GlobeView />} />
                      <Route path="/swarm-trajectory" element={<SwarmTrajectory />} />
                      <Route path="/px4-parameters" element={<Px4ParametersPage runtimeMode={runtimeStatus.mode} operatorId={auth.user?.id || auth.user?.username || ''} />} />

                      {/* Existing bookmarks resolve to the single mission authoring workspace. */}
                      <Route path="/trajectory-planning" element={<Navigate to="/swarm-trajectory?tab=plan" replace />} />

                      {/* QuickScout SAR */}
                      <Route path="/quickscout" element={<QuickScoutPage />} />

                      {/* System */}
                      <Route path="/runtime-admin" element={<RuntimeAdminPage />} />
                      <Route path="/environments" element={<EnvironmentsPage />} />
                      <Route path="/simurgh" element={<SimurghOperatorPage />} />
                      <Route path="/logs" element={<LogViewer runtimeMode={runtimeStatus.mode} operatorId={auth.user?.id || auth.user?.username || ''} userRole={logRole} />} />
                      <Route path="/sitl-control" element={<SitlControlPage />} />

                      {/* Backward-compatible alias used by workflow guidance */}
                      <Route path="/mission-control" element={<Overview runtimeMode={runtimeStatus.mode} operatorId={auth.user?.id || auth.user?.username || ''} />} />

                      {/* Default route */}
                      <Route path="/" element={<Overview runtimeMode={runtimeStatus.mode} operatorId={auth.user?.id || auth.user?.username || ''} />} />
                    </Routes>
                  </Suspense>
                </div>
              </div>
              <ToastContainer
                position="top-right"
                autoClose={5000}
                hideProgressBar={false}
                newestOnTop={false}
                closeOnClick
                limit={3}
                rtl={false}
                pauseOnFocusLoss
                draggable
                pauseOnHover
                // Enhanced styling to match design system
                className="toast-container"
                toastClassName="toast-item"
                bodyClassName="toast-body"
                progressClassName="toast-progress"
              />
      </FleetAlertsProvider>
    </Router>
    </UlogTransferProvider>
    </CommandActivityProvider>
    </ObservationProvider>
  );
};

const AuthenticatedWorkspace = () => {
  const auth = useAuth();
  return <ObservationProvider key={`${auth.user?.id || auth.user?.username || 'session'}:${auth.role || ''}`}><AppShell /></ObservationProvider>;
};

const App = () => (
  <ThemeProvider>
    <ErrorBoundary>
        <MapProvider>
          <AuthProvider>
            <AuthGate>
              <AuthenticatedWorkspace />
            </AuthGate>
          </AuthProvider>
        </MapProvider>
    </ErrorBoundary>
  </ThemeProvider>
);

export default App;
