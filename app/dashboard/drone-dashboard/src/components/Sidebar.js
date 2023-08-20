import React, { useState, useEffect } from 'react';
import '../styles/Sidebar.css';
import { Link } from 'react-router-dom';

const Sidebar = () => {
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
    <div className="sidebar">
      <h2>Swarm Dashboard</h2>
      <div className="time-details">
        <p>
        Local Time:<br /> {currentTime.toLocaleString()} 
        </p>
        <br />
        <p>
        UNIX Time:<br /> {Math.floor(currentTime / 1000)}
        </p>
        
      </div>
      <ul>
      <li>
  <a href="/">Overview</a>
</li>
<li>
<Link to="/mission-config">Mission Config</Link>
</li>
<li>
<Link to="/swarm-design">Swarm Design</Link>
</li>
        <li>Settings</li>
      </ul>
     
      <div className="developer-info">
 <p> MAVSDK Drone Show <br/> by Alireza Ghaderi 
 </p>
  <a href="https://github.com/alireza787b/mavsdk_drone_show" target="_blank" rel="noopener noreferrer">
    Github Repository
  </a>
</div>
      
    </div>

  );
};

export default Sidebar;
