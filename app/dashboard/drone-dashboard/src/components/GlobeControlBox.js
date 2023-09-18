import React from 'react';
import '../styles/GlobeControlBox.css'; // Import the CSS

function GlobeControlBox({ setShowGround, showGround, setGroundLevel, groundLevel, toggleDroneVisibility, droneVisibility, isToolboxOpen,showGrid, setShowGrid,handleGetTerrainClick }) {
  return (
    <div className={`globe-control-box ${isToolboxOpen ? 'show' : ''}`}>
      <h4>Control Box</h4>
      
      {/* Show/Hide Ground */}
      <div>
        <label>
          <input
            type="checkbox"
            checked={showGround}
            onChange={(e) => setShowGround(e.target.checked)}
          />
          Show Ground
        </label>
      </div>
      
     

     {/* Set Ground Level */}
<div>
  <label>Ground Level (meters): </label>
  <input 
    type="number" 
    min={-2000} 
    max={15000} 
    step="1" 
    value={groundLevel} 
    onChange={(e) => setGroundLevel(Number(e.target.value))}
  />
</div>
<button 
        onClick={handleGetTerrainClick} 
        className="get-terrain-button"
      >
        Get Online Terrain</button>


 {/* Set Grid Visibile */}
 <div>
      <label>
  <input
    type="checkbox"
    checked={showGrid}
    onChange={() => setShowGrid(!showGrid)}
  />
    Show Grid
</label>
</div>
      
      {/* Show/Hide Drones */}
      <div>
        <h5>Show Drones:</h5>
        {Object.keys(droneVisibility).map((droneId) => (
          <div key={droneId}>
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
