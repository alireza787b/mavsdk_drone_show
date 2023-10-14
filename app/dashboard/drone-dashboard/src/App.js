import React, { useState, useEffect } from 'react';
import Overview from './components/Overview';
import Detail from './components/DroneDetail';
import SidebarMenu from './components/SidebarMenu';
import SwarmDesign from './components/SwarmDesign';
import Mission from './components/MissionConfig';
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import './App.css';
import MissionConfig from './components/MissionConfig';
import DroneShowDesign from './components/DroneShowDesign'
import ImportShow from './components/ImportShow';

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
  <Route path="/import-drone-show" element={<ImportShow />} /> {/* New Route */}
  <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
</Routes>

        </div>
      </div>
    </Router>
  );
};

export default App;
