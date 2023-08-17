import React from 'react';
import '../styles/Sidebar.css';
import { Link } from 'react-router-dom';

const Sidebar = ({ currentTime }) => {
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
<Link to="/swarm-design">Swarm Design</Link>

        <li>Details</li>
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
