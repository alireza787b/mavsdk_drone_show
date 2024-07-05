//app/dashboard/drone-dashboard/src/App.js
import React, { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Overview from './pages/Overview';
import Detail from './components/DroneDetail';
import SidebarMenu from './components/SidebarMenu';
import SwarmDesign from './pages/SwarmDesign';
import MissionConfig from './pages/MissionConfig'; // Fixed duplicate import
import DroneShowDesign from './pages/DroneShowDesign';
import ImportShow from './pages/ImportShow';
import './App.css';

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
            <Route path="/import-drone-show" element={<ImportShow />} />
            <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
};

export default App;
