// app/dashboard/drone-dashboard/src/components/trajectory/TrajectoryToolbar.js
import React from 'react';
import PropTypes from 'prop-types';

const TrajectoryToolbar = ({
  isAddingWaypoint,
  onToggleAddWaypoint,
  onClearTrajectory,
  onExportTrajectory,
  showTerrain,
  onToggleTerrain,
  sceneMode,
  onSceneModeChange,
  waypointCount
}) => {
  return (
    <div className="trajectory-toolbar">
      <div className="toolbar-group">
        <button 
          className={isAddingWaypoint ? 'active' : ''}
          onClick={onToggleAddWaypoint}
          title="Add Waypoint Mode"
        >
          📍 Add Waypoint
        </button>
        <button onClick={onClearTrajectory} disabled={waypointCount === 0}>
          🗑️ Clear All
        </button>
        <button onClick={onExportTrajectory} disabled={waypointCount === 0}>
          💾 Export CSV
        </button>
      </div>
      
      <div className="toolbar-group">
        <button 
          className={showTerrain ? 'active' : ''}
          onClick={onToggleTerrain}
        >
          🏔️ Terrain
        </button>
        
        <select value={sceneMode} onChange={(e) => onSceneModeChange(e.target.value)}>
          <option value="3D">3D</option>
          <option value="2D">2D</option>
          <option value="Columbus">Columbus</option>
        </select>
      </div>
      
      <div className="toolbar-info">
        Waypoints: {waypointCount}
      </div>
    </div>
  );
};

TrajectoryToolbar.propTypes = {
  isAddingWaypoint: PropTypes.bool.isRequired,
  onToggleAddWaypoint: PropTypes.func.isRequired,
  onClearTrajectory: PropTypes.func.isRequired,
  onExportTrajectory: PropTypes.func.isRequired,
  showTerrain: PropTypes.bool.isRequired,
  onToggleTerrain: PropTypes.func.isRequired,
  sceneMode: PropTypes.string.isRequired,
  onSceneModeChange: PropTypes.func.isRequired,
  waypointCount: PropTypes.number.isRequired,
};

export default TrajectoryToolbar;
