// src/components/trajectory/WaypointPanel.js
import React from 'react';
import PropTypes from 'prop-types';
import { getSpeedStatus } from '../../utilities/SpeedCalculator';

const WaypointPanel = ({
  waypoints,
  selectedWaypointId,
  onSelectWaypoint,
  onUpdateWaypoint,
  onDeleteWaypoint,
  onMoveWaypoint,
  onFlyTo
}) => {
  if (!waypoints || waypoints.length === 0) {
    return (
      <div className="waypoint-panel">
        <h3>Waypoints</h3>
        <p>No waypoints yet. Click on the map to add waypoints with custom altitude and timing.</p>
      </div>
    );
  }

  // Get speed status indicator
  const getSpeedIndicator = (waypoint, index) => {
    if (index === 0) return null; // First waypoint has no speed requirement
    
    const speed = waypoint.estimatedSpeed || 0;
    const status = getSpeedStatus(speed);
    
    switch (status) {
      case 'feasible':
        return <span className="speed-indicator speed-feasible" title="Optimal speed">✓</span>;
      case 'marginal':
        return <span className="speed-indicator speed-marginal" title="High speed - use caution">⚠</span>;
      case 'impossible':
        return <span className="speed-indicator speed-impossible" title="Speed too high for safe operation">⚠</span>;
      default:
        return null;
    }
  };

  // Format speed display
  const formatSpeed = (speed) => {
    if (!speed || speed === 0) return '0.0';
    return speed.toFixed(1);
  };

  // Format time display
  const formatTime = (timeFromStart) => {
    if (!timeFromStart) return '0';
    if (timeFromStart < 60) return `${timeFromStart.toFixed(1)}s`;
    
    const minutes = Math.floor(timeFromStart / 60);
    const seconds = (timeFromStart % 60).toFixed(0);
    return `${minutes}m ${seconds}s`;
  };

  return (
    <div className="waypoint-panel">
      <div className="waypoint-panel-header">
        <h3>Waypoints ({waypoints.length})</h3>
        {waypoints.some(wp => wp.estimatedSpeed > 20) && (
          <div className="speed-warning-summary">
            <span className="speed-indicator speed-impossible">⚠</span>
            High speed detected
          </div>
        )}
      </div>
      
      <div className="waypoint-list">
        {waypoints.map((waypoint, index) => (
          <div 
            key={waypoint.id}
            className={`waypoint-item ${selectedWaypointId === waypoint.id ? 'selected' : ''} ${
              index > 0 && !waypoint.speedFeasible ? 'speed-warning' : ''
            }`}
            onClick={() => onSelectWaypoint(waypoint.id)}
          >
            <div className="waypoint-header">
              <div className="waypoint-name-section">
                <strong>{waypoint.name}</strong>
                {index > 0 && getSpeedIndicator(waypoint, index)}
              </div>
              <div className="waypoint-actions">
                <button 
                  onClick={(e) => { e.stopPropagation(); onFlyTo(waypoint); }}
                  title="Fly to waypoint"
                  className="action-btn fly-btn"
                >
                  📍
                </button>
                <button 
                  onClick={(e) => { e.stopPropagation(); onDeleteWaypoint(waypoint.id); }}
                  title="Delete waypoint"
                  className="action-btn delete-btn"
                >
                  🗑️
                </button>
              </div>
            </div>
            
            <div className="waypoint-details">
              <div className="detail-row">
                <span className="detail-label">Position:</span>
                <span className="detail-value">
                  {waypoint.latitude.toFixed(6)}, {waypoint.longitude.toFixed(6)}
                </span>
              </div>
              
              <div className="detail-row">
                <span className="detail-label">Altitude:</span>
                <span className="detail-value">{waypoint.altitude.toFixed(1)}m</span>
              </div>
              
              <div className="detail-row">
                <span className="detail-label">Time:</span>
                <span className="detail-value">{formatTime(waypoint.timeFromStart || waypoint.time || 0)}</span>
              </div>
              
              {index > 0 && (
                <div className="detail-row speed-row">
                  <span className="detail-label">Speed:</span>
                  <div className="speed-display">
                    <span className={`detail-value speed-value speed-${getSpeedStatus(waypoint.estimatedSpeed || 0)}`}>
                      {formatSpeed(waypoint.estimatedSpeed)}m/s
                    </span>
                    {waypoint.estimatedSpeed > 15 && (
                      <span className="speed-warning-text">
                        ({(waypoint.estimatedSpeed * 3.6).toFixed(1)} km/h)
                      </span>
                    )}
                  </div>
                </div>
              )}
              
              {index === 0 && (
                <div className="detail-row start-point">
                  <span className="detail-label">Type:</span>
                  <span className="detail-value start-indicator">Start Point</span>
                </div>
              )}
              
              {index === waypoints.length - 1 && waypoints.length > 1 && (
                <div className="detail-row end-point">
                  <span className="detail-label">Type:</span>
                  <span className="detail-value end-indicator">End Point</span>
                </div>
              )}
            </div>
            
            {/* Speed warning for high-speed segments */}
            {index > 0 && waypoint.estimatedSpeed > 20 && (
              <div className="waypoint-speed-warning">
                <small>⚠ High speed segment - verify drone capabilities</small>
              </div>
            )}
          </div>
        ))}
      </div>
      
      {/* Summary statistics */}
      {waypoints.length > 1 && (
        <div className="waypoint-summary">
          <div className="summary-item">
            <span className="summary-label">Total Points:</span>
            <span className="summary-value">{waypoints.length}</span>
          </div>
          
          <div className="summary-item">
            <span className="summary-label">Duration:</span>
            <span className="summary-value">
              {formatTime(waypoints[waypoints.length - 1]?.timeFromStart || 0)}
            </span>
          </div>
          
          <div className="summary-item">
            <span className="summary-label">Max Speed:</span>
            <span className="summary-value">
              {Math.max(...waypoints.slice(1).map(wp => wp.estimatedSpeed || 0)).toFixed(1)}m/s
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

WaypointPanel.propTypes = {
  waypoints: PropTypes.array.isRequired,
  selectedWaypointId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
  onSelectWaypoint: PropTypes.func.isRequired,
  onUpdateWaypoint: PropTypes.func.isRequired,
  onDeleteWaypoint: PropTypes.func.isRequired,
  onMoveWaypoint: PropTypes.func.isRequired,
  onFlyTo: PropTypes.func.isRequired,
};

export default WaypointPanel;