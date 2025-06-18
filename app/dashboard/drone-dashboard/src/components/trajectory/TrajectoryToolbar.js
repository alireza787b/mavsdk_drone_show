// src/components/trajectory/TrajectoryToolbar.js
import React from 'react';
import {
  FaPlus,
  FaRoute,
  FaMountain,
  FaFileExport,
  FaTrash,
  FaGlobeAmericas,
  FaMap,
  FaCube
} from 'react-icons/fa';
import '../../styles/TrajectoryToolbar.css';

const TrajectoryToolbar = ({
  isAddingWaypoint,
  setIsAddingWaypoint,
  showPath,
  setShowPath,
  showTerrain,
  setShowTerrain,
  pathInterpolation,
  setPathInterpolation,
  viewMode,
  setViewMode,
  onExport,
  onClear
}) => {
  return (
    <div className="trajectory-toolbar">
      <div className="toolbar-section">
        <div className="toolbar-group">
          <button
            className={`toolbar-btn ${isAddingWaypoint ? 'active' : ''}`}
            onClick={() => setIsAddingWaypoint(!isAddingWaypoint)}
            title="Add Waypoint - Click on map to place"
          >
            <FaPlus />
            <span>Add Waypoint</span>
          </button>

          <button
            className={`toolbar-btn ${showPath ? 'active' : ''}`}
            onClick={() => setShowPath(!showPath)}
            title="Toggle Path Visibility"
          >
            <FaRoute />
            <span>Path</span>
          </button>

          <button
            className={`toolbar-btn ${showTerrain ? 'active' : ''}`}
            onClick={() => setShowTerrain(!showTerrain)}
            title="Toggle 3D Terrain"
          >
            <FaMountain />
            <span>Terrain</span>
          </button>
        </div>

        <div className="toolbar-group">
          <label className="toolbar-label">View:</label>
          <button
            className={`toolbar-btn icon-only ${viewMode === '3D' ? 'active' : ''}`}
            onClick={() => setViewMode('3D')}
            title="3D View"
          >
            <FaGlobeAmericas />
          </button>
          <button
            className={`toolbar-btn icon-only ${viewMode === '2D' ? 'active' : ''}`}
            onClick={() => setViewMode('2D')}
            title="2D View"
          >
            <FaMap />
          </button>
          <button
            className={`toolbar-btn icon-only ${viewMode === 'CV' ? 'active' : ''}`}
            onClick={() => setViewMode('CV')}
            title="Columbus View"
          >
            <FaCube />
          </button>
        </div>

        <div className="toolbar-group">
          <label className="toolbar-label">Interpolation:</label>
          <select
            className="toolbar-select"
            value={pathInterpolation}
            onChange={(e) => setPathInterpolation(e.target.value)}
          >
            <option value="linear">Linear</option>
            <option value="cubic">Cubic Spline</option>
            <option value="catmull">Catmull-Rom</option>
          </select>
        </div>
      </div>

      <div className="toolbar-section">
        <div className="toolbar-group">
          <button 
            className="toolbar-btn danger-btn" 
            onClick={onClear}
            title="Clear All Waypoints"
          >
            <FaTrash />
            <span>Clear</span>
          </button>
          
          <button 
            className="toolbar-btn primary-btn" 
            onClick={onExport}
            title="Export Trajectory as CSV"
          >
            <FaFileExport />
            <span>Export CSV</span>
          </button>
        </div>
      </div>
    </div>
  );
};

export default TrajectoryToolbar;
