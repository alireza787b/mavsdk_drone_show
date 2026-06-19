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
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { FaBars, FaTimes } from 'react-icons/fa';

// Import theme system
import { ThemeProvider } from './contexts/ThemeContext';
import { CommandActivityProvider } from './contexts/CommandActivityContext';
import { MapProvider } from './contexts/MapContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';

// Import design tokens first
import './styles/DesignTokens.css';

import SidebarMenu from './components/SidebarMenu';
import RouteDocsShortcut from './components/RouteDocsShortcut';
import SyncWarningBanner from './components/SyncWarningBanner';
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
const Detail = lazy(() => import('./components/DroneDetail'));
const SwarmDesign = lazy(() => import('./pages/SwarmDesign'));
const CustomShowPage = lazy(() => import('./pages/CustomShowPage'));
const GlobeView = lazy(() => import('./pages/GlobeView'));
const ManageDroneShow = lazy(() => import('./pages/ManageDroneShow'));
const SwarmTrajectory = lazy(() => import('./pages/SwarmTrajectory'));
const TrajectoryPlanning = lazy(() => import('./pages/TrajectoryPlanning'));
const QuickScoutPage = lazy(() => import('./pages/QuickScoutPage'));
const Px4ParametersPage = lazy(() => import('./pages/Px4ParametersPage'));
const FleetEnrollmentPage = lazy(() => import('./pages/FleetEnrollmentPage'));
const FleetOpsPage = lazy(() => import('./pages/FleetOpsPage'));
const FleetOpsWifiPage = lazy(() => import('./pages/FleetOpsWifiPage'));
const FleetOpsMavlinkPage = lazy(() => import('./pages/FleetOpsMavlinkPage'));
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

const AppLoadingFallback = () => (
  <div className="page-loading" role="status" aria-live="polite" aria-label="Loading mission dashboard">
    <div className="page-loading__card">
      <div className="page-loading__radar" aria-hidden="true">
        <span className="page-loading__sweep" />
        <span className="page-loading__node page-loading__node--one" />
        <span className="page-loading__node page-loading__node--two" />
        <span className="page-loading__node page-loading__node--three" />
      </div>
      <div className="page-loading__copy">
        <strong>Loading mission dashboard</strong>
        <span>Preparing fleet view</span>
      </div>
      <div className="page-loading__dots" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
    </div>
  </div>
);

const AuthLoadingFallback = () => (
  <div className="page-loading" role="status" aria-live="polite" aria-label="Checking dashboard access">
    <div className="page-loading__card">
      <div className="page-loading__radar" aria-hidden="true">
        <span className="page-loading__sweep" />
        <span className="page-loading__node page-loading__node--one" />
        <span className="page-loading__node page-loading__node--two" />
      </div>
      <div className="page-loading__copy">
        <strong>Checking dashboard access</strong>
        <span>Preparing secure session</span>
      </div>
    </div>
  </div>
);

const AuthGate = ({ children }) => {
  const auth = useAuth();

  if (auth.loading && !auth.authRequired) {
    return <AuthLoadingFallback />;
  }

  if (auth.authRequired && !auth.authenticated) {
    return (
      <Suspense fallback={<AuthLoadingFallback />}>
        <LoginPage />
      </Suspense>
    );
  }

  return children;
};

const AppShell = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [isMobile, setIsMobile] = useState(getIsMobileViewport);
  const [desktopSidebarCollapsed, setDesktopSidebarCollapsed] = useState(getIsMobileViewport);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const runtimeStatus = useGcsRuntimeStatus();
  const auth = useAuth();

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
    <Router
      future={{
        v7_startTransition: true,
        v7_relativeSplatPath: true,
      }}
    >
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
                  <RouteDocsShortcut />
                  <SyncWarningBanner />
                  <Suspense fallback={<AppLoadingFallback />}>
                    <Routes>
                      {/* Main drone management routes */}
                      <Route path="/drone-show-design" element={<ManageDroneShow />} />
                      <Route path="/swarm-design" element={<SwarmDesign />} />
                      <Route path="/mission-config" element={<MissionConfig />} />
                      <Route path="/fleet-enrollment" element={<FleetEnrollmentPage />} />
                      <Route path="/fleet-ops" element={<FleetOpsPage />} />
                      <Route path="/fleet-ops/wifi" element={<FleetOpsWifiPage />} />
                      <Route path="/fleet-ops/mavlink" element={<FleetOpsMavlinkPage />} />
                      <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
                      <Route path="/manage-drone-show" element={<ManageDroneShow />} />
                      <Route path="/custom-show" element={<CustomShowPage />} />
                      <Route path="/globe-view" element={<GlobeView />} />
                      <Route path="/swarm-trajectory" element={<SwarmTrajectory />} />
                      <Route path="/px4-parameters" element={<Px4ParametersPage />} />

                      {/* Advanced Route Editor retained for lower-level trajectory authoring */}
                      <Route path="/trajectory-planning" element={<TrajectoryPlanning />} />

                      {/* QuickScout SAR */}
                      <Route path="/quickscout" element={<QuickScoutPage />} />

                      {/* System */}
                      <Route path="/runtime-admin" element={<RuntimeAdminPage />} />
                      <Route path="/environments" element={<EnvironmentsPage />} />
                      <Route path="/simurgh" element={<SimurghOperatorPage />} />
                      <Route path="/logs" element={<LogViewer />} />
                      <Route path="/sitl-control" element={<SitlControlPage />} />

                      {/* Backward-compatible alias used by workflow guidance */}
                      <Route path="/mission-control" element={<Overview setSelectedDrone={setSelectedDrone} />} />

                      {/* Default route */}
                      <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
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
    </Router>
  );
};

const App = () => (
  <ThemeProvider>
    <ErrorBoundary>
      <CommandActivityProvider>
        <MapProvider>
          <AuthProvider>
            <AuthGate>
              <AppShell />
            </AuthGate>
          </AuthProvider>
        </MapProvider>
      </CommandActivityProvider>
    </ErrorBoundary>
  </ThemeProvider>
);

export default App;
