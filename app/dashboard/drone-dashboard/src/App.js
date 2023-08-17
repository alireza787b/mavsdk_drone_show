import React, { useState, useEffect } from 'react';
import Overview from './components/Overview';
import Detail from './components/DroneDetail';
import Sidebar from './components/Sidebar';
import SwarmDesign from './components/SwarmDesign';
import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import './App.css';

const App = () => {
  
  const [selectedDrone, setSelectedDrone] = useState(null);
  const [currentTime, setCurrentTime] = useState(new Date());

  // Function to update the current time
  const updateTime = () => {
    setCurrentTime(new Date());
  };

  // Set up an interval to update the current time every second
  useEffect(() => {
    const timeInterval = setInterval(updateTime, 1000);
    return () => {
      clearInterval(timeInterval);
    };
  }, []);

  return (
    <Router>
      <div className="app-container">
        <Sidebar currentTime={currentTime} />
        <div className="content">
          <Routes>
            <Route path="/swarm-design" element={<SwarmDesign />} />
            <Route path="/drone-detail" element={<Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />} />
            <Route path="/" element={<Overview setSelectedDrone={setSelectedDrone} />} />
          </Routes>
        </div>
      </div>
    </Router>
  );
};

export default App;
