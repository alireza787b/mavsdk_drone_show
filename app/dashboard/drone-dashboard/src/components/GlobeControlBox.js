// app/dashboard/drone-dashboard/src/components/GlobeControlBox.js
import React from 'react';
import '../styles/GlobeControlBox.css';

function GlobeControlBox({ 
  setShowGround, 
  showGround, 
  setGroundLevel, 
  groundLevel, 
  toggleDroneVisibility, 
  droneVisibility, 
  isToolboxOpen,
  showGrid, 
  setShowGrid, 
  handleGetTerrainClick 
}) {
  return (
    <div className={`globe-control-box ${isToolboxOpen ? 'show' : 'hide'}`}>
      <h4>Control Panel</h4>
      
      {/* Show/Hide Ground */}
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGround}
            onChange={(e) => setShowGround(e.target.checked)}
          />
          Show Ground
        </label>
      </div>
      
      {/* Set Ground Level */}
      <div className="control-section">
        <label className="control-label">
          Ground Level (m):
          <input 
            type="number" 
            min={-2000} 
            max={15000} 
            step="1" 
            value={groundLevel} 
            onChange={(e) => setGroundLevel(Number(e.target.value))}
            className="number-input"
          />
        </label>
        <button 
          onClick={handleGetTerrainClick} 
          className="get-terrain-button"
        >
          Get Terrain
        </button>
      </div>

      {/* Show/Hide Grid */}
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGrid}
            onChange={() => setShowGrid(!showGrid)}
          />
          Show Grid
        </label>
      </div>
      
      {/* Drone Visibility Toggles */}
      <div className="control-section drone-toggles">
        <h5>Drone Visibility:</h5>
        {Object.keys(droneVisibility).map((droneId) => (
          <div key={droneId} className="drone-toggle">
            <label>
              <input
                type="checkbox"
                checked={droneVisibility[droneId]}
                onChange={() => toggleDroneVisibility(droneId)}
              />
              Drone {droneId}
            </label>
          </div>
        ))}
      </div>
    </div>
  );
}

export default GlobeControlBox;
