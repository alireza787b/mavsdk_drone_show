import React, { useState, useEffect, useContext } from 'react';
import Overview from './components/Overview';
import Detail from './components/DroneDetail';
import Header from './components/Header';
import Sidebar from './components/Sidebar';

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
    <div className="app-container">
      <Sidebar currentTime={currentTime} />
      <div className="content">
        {selectedDrone ? (
          <Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />
        ) : (
          <Overview setSelectedDrone={setSelectedDrone} />
        )}
      </div>
    </div>
  );
};



export default App;
