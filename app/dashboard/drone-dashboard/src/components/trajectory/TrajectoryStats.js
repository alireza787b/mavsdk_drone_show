// src/components/trajectory/TrajectoryStats.js
import React from 'react';
import { FaRoute, FaClock, FaArrowUp, FaArrowDown } from 'react-icons/fa';
import '../../styles/TrajectoryStats.css';

const TrajectoryStats = ({ stats }) => {
  const formatDistance = (meters) => {
    if (meters < 1000) {
      return `${meters.toFixed(0)}m`;
    } else {
      return `${(meters / 1000).toFixed(2)}km`;
    }
  };

  const formatTime = (seconds) => {
    if (seconds < 60) {
      return `${seconds.toFixed(0)}s`;
    } else if (seconds < 3600) {
      const minutes = Math.floor(seconds / 60);
      const secs = Math.floor(seconds % 60);
      return `${minutes}m ${secs}s`;
    } else {
      const hours = Math.floor(seconds / 3600);
      const minutes = Math.floor((seconds % 3600) / 60);
      return `${hours}h ${minutes}m`;
    }
  };

  return (
    <div className="trajectory-stats">
      <div className="stat-item">
        <FaRoute className="stat-icon" />
        <div className="stat-content">
          <span className="stat-label">Distance</span>
          <span className="stat-value">{formatDistance(stats.totalDistance)}</span>
        </div>
      </div>
      
      <div className="stat-item">
        <FaClock className="stat-icon" />
        <div className="stat-content">
          <span className="stat-label">Duration</span>
          <span className="stat-value">{formatTime(stats.totalTime)}</span>
        </div>
      </div>
      
      <div className="stat-item">
        <FaArrowUp className="stat-icon" />
        <div className="stat-content">
          <span className="stat-label">Max Alt</span>
          <span className="stat-value">{stats.maxAltitude.toFixed(0)}m</span>
        </div>
      </div>
      
      <div className="stat-item">
        <FaArrowDown className="stat-icon" />
        <div className="stat-content">
          <span className="stat-label">Min Alt</span>
          <span className="stat-value">{stats.minAltitude.toFixed(0)}m</span>
        </div>
      </div>
    </div>
  );
};

export default TrajectoryStats;
