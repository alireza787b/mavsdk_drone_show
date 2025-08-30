import React from 'react';
import PropTypes from 'prop-types';

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
        <p>No waypoints yet. Click on the map to add waypoints.</p>
      </div>
    );
  }

  return (
    <div className="waypoint-panel">
      <h3>Waypoints ({waypoints.length})</h3>
      <div className="waypoint-list">
        {waypoints.map((waypoint, index) => (
          <div 
            key={waypoint.id}
            className={`waypoint-item ${selectedWaypointId === waypoint.id ? 'selected' : ''}`}
            onClick={() => onSelectWaypoint(waypoint.id)}
          >
            <div className="waypoint-header">
              <strong>{waypoint.name}</strong>
              <div className="waypoint-actions">
                <button onClick={(e) => { e.stopPropagation(); onFlyTo(waypoint); }}>
                  📍
                </button>
                <button onClick={(e) => { e.stopPropagation(); onDeleteWaypoint(waypoint.id); }}>
                  🗑️
                </button>
              </div>
            </div>
            <div className="waypoint-details">
              <div>Lat: {waypoint.latitude.toFixed(6)}</div>
              <div>Lon: {waypoint.longitude.toFixed(6)}</div>
              <div>Alt: {waypoint.altitude.toFixed(1)}m</div>
              <div>Time: {waypoint.time}s</div>
            </div>
          </div>
        ))}
      </div>
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
