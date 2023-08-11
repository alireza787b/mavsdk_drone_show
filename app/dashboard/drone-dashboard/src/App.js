import React, { useState, useEffect } from 'react';
import Overview from './components/Overview';
import Detail from './components/DroneDetail';
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
    <div>
      <p>
      System Local Time: {currentTime.toLocaleString()} | System UNIX Time: {Math.floor(currentTime / 1000)}</p>
      {selectedDrone ? (
        <Detail drone={selectedDrone} goBack={() => setSelectedDrone(null)} />
      ) : (
        <Overview setSelectedDrone={setSelectedDrone} />
      )}
    </div>
  );
};

export default App;
