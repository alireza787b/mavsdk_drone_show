import React, { useState, useEffect } from 'react';
import Overview from './components/Overview';
import Detail from './components/DroneDetail';
import Sidebar from './components/Sidebar';
import SwarmDesign from './components/SwarmDesign';
import Mission from './components/MissionConfig';
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import './App.css';
import MissionConfig from './components/MissionConfig';

const App = () => {
  
  const [selectedDrone, setSelectedDrone] = useState(null);





  return (
    <Router>
      <div className="app-container">
        <Sidebar />
        <div className="content">
          <Routes>
          <Route path="/swarm-design" element={<SwarmDesign />} />
          <Route path="/mission-config" element={<MissionConfig />} />
            <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
            <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
};

export default App;
