//app/dashboard/drone-dashboard/src/App.js
import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';

// Import design tokens first
import './styles/DesignTokens.css';

// Import pages and components
import Overview from './pages/Overview';
import Detail from './components/DroneDetail';
import SidebarMenu from './components/SidebarMenu';
import SwarmDesign from './pages/SwarmDesign';
import MissionConfig from './pages/MissionConfig';
import DroneShowDesign from './pages/DroneShowDesign';
import CustomShowPage from './pages/CustomShowPage';
import GlobeView from './pages/GlobeView';
import ManageDroneShow from './pages/ManageDroneShow';
import SwarmTrajectory from './pages/SwarmTrajectory';

// Clean import - no error boundary needed with Mapbox
import TrajectoryPlanning from './pages/TrajectoryPlanning';

// Import external styles
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import 'leaflet/dist/leaflet.css';

// Import main app styles (should come after design tokens)
import './App.css';

/**
 * Main Application Component
 * Clean routing with Mapbox-based trajectory planning
 * Now includes unified design system
 */
const App = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);

  return (
    <Router>
      <div className="app-container">
        <SidebarMenu />
        <div className="content">
          <Routes>
            {/* Main drone management routes */}
            <Route path="/drone-show-design" element={<DroneShowDesign />} />
            <Route path="/swarm-design" element={<SwarmDesign />} />
            <Route path="/mission-config" element={<MissionConfig />} />
            <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
            <Route path="/manage-drone-show" element={<ManageDroneShow />} />
            <Route path="/custom-show" element={<CustomShowPage />} />
            <Route path="/globe-view" element={<GlobeView />} />
            <Route path="/swarm-trajectory" element={<SwarmTrajectory />} />
            
            {/* Enhanced Trajectory Planning Route with unified design system */}
            <Route path="/trajectory-planning" element={<TrajectoryPlanning />} />
            
            {/* Default route */}
            <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
          </Routes>
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
  );
};

export default App;