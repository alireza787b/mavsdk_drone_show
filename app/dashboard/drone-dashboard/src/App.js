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

// Import design tokens first
import './styles/DesignTokens.css';

// Eagerly loaded — primary operational views
import Overview from './pages/Overview';
import MissionConfig from './pages/MissionConfig';
import SidebarMenu from './components/SidebarMenu';
import SyncWarningBanner from './components/SyncWarningBanner';
import ErrorBoundary from './components/ErrorBoundary';

// External styles and toast
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import 'leaflet/dist/leaflet.css';
import './App.css';

// Lazy loaded — heavy visualization pages (three.js, plotly, cytoscape, mapbox)
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
const LogViewer = lazy(() => import('./pages/LogViewer'));
const SitlControlPage = lazy(() => import('./pages/SitlControlPage'));

/**
 * Main Application Component
 * Clean routing with Mapbox-based trajectory planning
 * Now includes unified design system with dynamic sidebar
 */
const MOBILE_BREAKPOINT = 960;

const getIsMobileViewport = () => {
  if (typeof window === 'undefined') {
    return false;
  }
  return window.innerWidth <= MOBILE_BREAKPOINT;
};

const App = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [isMobile, setIsMobile] = useState(getIsMobileViewport);
  const [desktopSidebarCollapsed, setDesktopSidebarCollapsed] = useState(getIsMobileViewport);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

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
    <ThemeProvider>
      <ErrorBoundary>
        <CommandActivityProvider>
          <MapProvider>
            <Router
              future={{
                v7_startTransition: true,
                v7_relativeSplatPath: true,
              }}
            >
              <div className={`app-container ${isMobile ? 'app-mobile' : 'app-desktop'}`}>
                {isMobile && (
                  <>
                    <button
                      className={`mobile-sidebar-toggle ${mobileSidebarOpen ? 'is-open' : ''}`}
                      onClick={() => setMobileSidebarOpen((current) => !current)}
                      aria-label={mobileSidebarOpen ? 'Close navigation menu' : 'Open navigation menu'}
                    >
                      {mobileSidebarOpen ? <FaTimes /> : <FaBars />}
                    </button>
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
                />
                <div className={contentClassName}>
                  <SyncWarningBanner />
                  <Suspense fallback={<div className="page-loading">Loading...</div>}>
                    <Routes>
                      {/* Main drone management routes */}
                      <Route path="/drone-show-design" element={<ManageDroneShow />} />
                      <Route path="/swarm-design" element={<SwarmDesign />} />
                      <Route path="/mission-config" element={<MissionConfig />} />
                      <Route path="/fleet-enrollment" element={<FleetEnrollmentPage />} />
                      <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
                      <Route path="/manage-drone-show" element={<ManageDroneShow />} />
                      <Route path="/custom-show" element={<CustomShowPage />} />
                      <Route path="/globe-view" element={<GlobeView />} />
                      <Route path="/swarm-trajectory" element={<SwarmTrajectory />} />
                      <Route path="/px4-parameters" element={<Px4ParametersPage />} />

                      {/* Enhanced Trajectory Planning Route with unified design system */}
                      <Route path="/trajectory-planning" element={<TrajectoryPlanning />} />

                      {/* QuickScout SAR */}
                      <Route path="/quickscout" element={<QuickScoutPage />} />

                      {/* System */}
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
          </MapProvider>
        </CommandActivityProvider>
      </ErrorBoundary>
    </ThemeProvider>
  );
};

export default App;
