//app/dashboard/drone-dashboard/src/components/trajectory/TrajectoryStats.js
import React from 'react';
import PropTypes from 'prop-types';

const TrajectoryStats = ({ stats }) => {
  const formatDistance = (distance) => {
    if (distance > 1000) {
      return `${(distance / 1000).toFixed(2)} km`;
    }
    return `${distance.toFixed(1)} m`;
  };

  const formatTime = (time) => {
    if (time > 60) {
      const minutes = Math.floor(time / 60);
      const seconds = time % 60;
      return `${minutes}m ${seconds.toFixed(0)}s`;
    }
    return `${time.toFixed(0)}s`;
  };

  return (
    <div className="trajectory-stats">
      <div className="stat-item">
        <span className="stat-label">Distance:</span>
        <span className="stat-value">{formatDistance(stats.totalDistance)}</span>
      </div>
      <div className="stat-item">
        <span className="stat-label">Time:</span>
        <span className="stat-value">{formatTime(stats.totalTime)}</span>
      </div>
      <div className="stat-item">
        <span className="stat-label">Max Alt:</span>
        <span className="stat-value">{stats.maxAltitude.toFixed(1)}m</span>
      </div>
      <div className="stat-item">
        <span className="stat-label">Min Alt:</span>
        <span className="stat-value">{stats.minAltitude.toFixed(1)}m</span>
      </div>
    </div>
  );
};

TrajectoryStats.propTypes = {
  stats: PropTypes.shape({
    totalDistance: PropTypes.number.isRequired,
    totalTime: PropTypes.number.isRequired,
    maxAltitude: PropTypes.number.isRequired,
    minAltitude: PropTypes.number.isRequired,
  }).isRequired,
};

export default TrajectoryStats;
