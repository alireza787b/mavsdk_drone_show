//app/dashboard/drone-dashboard/src/App.js
import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Overview from './pages/Overview';
import Detail from './components/DroneDetail';
import SidebarMenu from './components/SidebarMenu';
import SwarmDesign from './pages/SwarmDesign';
import MissionConfig from './pages/MissionConfig'; // Fixed duplicate import
import DroneShowDesign from './pages/DroneShowDesign';
import CustomShowPage from './pages/CustomShowPage'; // Import the new page
import GlobeView from './pages/GlobeView';
import TrajectoryPlanning from './pages/TrajectoryPlanning';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import 'leaflet/dist/leaflet.css';

import './App.css';
import ManageDroneShow from './pages/ManageDroneShow';

const App = () => {
  const [selectedDrone, setSelectedDrone] = useState(null);

  return (
    <Router>
      <div className="app-container">
        <SidebarMenu />
        <div className="content">
          <Routes>
            <Route path="/drone-show-design" element={<DroneShowDesign />} />
            <Route path="/swarm-design" element={<SwarmDesign />} />
            <Route path="/mission-config" element={<MissionConfig />} />
            <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
            <Route path="/manage-drone-show" element={<ManageDroneShow />} />
            <Route path="/custom-show" element={<CustomShowPage />}  /> {/* New route */}
            <Route path="/globe-view" element={<GlobeView />} />
	    <Route path="/trajectory-planning" element={<TrajectoryPlanning />} />


            <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
          </Routes>
        </div>
      </div>
      <ToastContainer />
    </Router>
  );
};

export default App;
