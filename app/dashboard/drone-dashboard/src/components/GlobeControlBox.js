// src/components/GlobeControlBox.js
import React from 'react';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import '../styles/GlobeControlBox.css';

function GlobeControlBox({ 
  drones = [],
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
      <div className="globe-control-box__header">
        <div>
          <p className="globe-control-box__eyebrow">3D view</p>
          <h4>View Filters</h4>
        </div>
      </div>
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGround}
            onChange={(e) => setShowGround(e.target.checked)}
          />
          Ground
        </label>
      </div>
      <div className="control-section">
        <label className="control-label">
          Ground level
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
          Load Terrain
        </button>
      </div>
      <div className="control-section">
        <label className="control-label">
          <input
            type="checkbox"
            checked={showGrid}
            onChange={() => setShowGrid(!showGrid)}
          />
          Grid
        </label>
      </div>
      <div className="control-section drone-toggles">
        <h5>Visible Drones</h5>
        {Object.keys(droneVisibility).map((droneId) => {
          const drone = drones.find((entry) => String(entry?.[FIELD_NAMES.HW_ID]) === String(droneId));
          const label = formatCompactDroneIdentity(
            drone?.[FIELD_NAMES.POS_ID],
            droneId,
            `H${droneId}`,
          );

          return (
          <div key={droneId} className="drone-toggle">
            <label>
              <input
                type="checkbox"
                checked={droneVisibility[droneId]}
                onChange={() => toggleDroneVisibility(droneId)}
              />
              <span>{label}</span>
            </label>
          </div>
        )})}
      </div>
    </div>
  );
}

export default GlobeControlBox;
