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

import React, { useState, Suspense, lazy } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';

// Import theme system
import { ThemeProvider } from './contexts/ThemeContext';
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
const LogViewer = lazy(() => import('./pages/LogViewer'));

/**
 * Main Application Component
 * Clean routing with Mapbox-based trajectory planning
 * Now includes unified design system with dynamic sidebar
 */
const App = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(window.innerWidth < 768);

  return (
    <ThemeProvider>
      <ErrorBoundary>
      <MapProvider>
      <Router
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
      <div className="app-container">
        <SidebarMenu
          collapsed={sidebarCollapsed}
          onToggle={setSidebarCollapsed}
        />
        <div className={`content ${sidebarCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'}`}>
          <SyncWarningBanner />
          <Suspense fallback={<div className="page-loading">Loading...</div>}>
          <Routes>
            {/* Main drone management routes */}
            <Route path="/drone-show-design" element={<ManageDroneShow />} />
            <Route path="/swarm-design" element={<SwarmDesign />} />
            <Route path="/mission-config" element={<MissionConfig />} />
            <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
            <Route path="/manage-drone-show" element={<ManageDroneShow />} />
            <Route path="/custom-show" element={<CustomShowPage />} />
            <Route path="/globe-view" element={<GlobeView />} />
            <Route path="/swarm-trajectory" element={<SwarmTrajectory />} />
            
            {/* Enhanced Trajectory Planning Route with unified design system */}
            <Route path="/trajectory-planning" element={<TrajectoryPlanning />} />

            {/* QuickScout SAR */}
            <Route path="/quickscout" element={<QuickScoutPage />} />

            {/* System */}
            <Route path="/logs" element={<LogViewer />} />

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
      </ErrorBoundary>
    </ThemeProvider>
  );
};

export default App;
