// src/components/trajectory/TrajectoryToolbar.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import '../../styles/TrajectoryToolbar.css';

const TrajectoryToolbar = ({
  isAddingWaypoint,
  onToggleAddWaypoint,
  onClearTrajectory,
  onExportTrajectory,
  showTerrain,
  onToggleTerrain,
  sceneMode,
  onSceneModeChange,
  waypointCount,
  canUndo = false,
  canRedo = false,
  undoDescription = '',
  redoDescription = '',
  onUndo,
  onRedo,
  onSave,
  onLoad,
  onImport,
  onSendToSwarm,
  saveStatus = { saved: true, autoSaveTime: null },
  trajectoryName = '',
  canSendToSwarm = false
}) => {
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);

  // Format auto-save time for display
  const formatAutoSaveTime = (timestamp) => {
    if (!timestamp) return '';
    const now = Date.now();
    const diff = now - timestamp;
    const minutes = Math.floor(diff / (1000 * 60));
    
    if (minutes < 1) return 'just now';
    if (minutes === 1) return '1 min ago';
    return `${minutes} mins ago`;
  };

  return (
    <div className="trajectory-toolbar">
      <div className="toolbar-group toolbar-primary">
        <button 
          className={`toolbar-btn ${isAddingWaypoint ? 'active' : ''}`}
          onClick={onToggleAddWaypoint}
          title="Add Waypoint Mode (A)"
        >
          <span className="btn-icon">📍</span>
          <span className="btn-text">Add Waypoint</span>
        </button>
        
        <div className="toolbar-separator" />
        
        <button 
          className={`toolbar-btn undo-btn ${!canUndo ? 'disabled' : ''}`}
          onClick={onUndo}
          disabled={!canUndo}
          title={canUndo ? `Undo: ${undoDescription} (Ctrl+Z)` : 'Nothing to undo'}
        >
          <span className="btn-icon">↶</span>
          <span className="btn-text">Undo</span>
        </button>
        
        <button 
          className={`toolbar-btn redo-btn ${!canRedo ? 'disabled' : ''}`}
          onClick={onRedo}
          disabled={!canRedo}
          title={canRedo ? `Redo: ${redoDescription} (Ctrl+Y)` : 'Nothing to redo'}
        >
          <span className="btn-icon">↷</span>
          <span className="btn-text">Redo</span>
        </button>
      </div>

      <div className="toolbar-group toolbar-file">
        <button 
          className="toolbar-btn save-btn"
          onClick={onSave}
          title="Save Trajectory (Ctrl+S)"
        >
          <span className="btn-icon">💾</span>
          <span className="btn-text">Save</span>
          {!saveStatus.saved && <span className="unsaved-indicator">●</span>}
        </button>
        
        <button 
          className="toolbar-btn load-btn"
          onClick={onLoad}
          title="Load Trajectory (Ctrl+O)"
        >
          <span className="btn-icon">📂</span>
          <span className="btn-text">Load</span>
        </button>

        <button
          className="toolbar-btn import-btn"
          onClick={onImport}
          title="Import CSV or JSON Trajectory"
        >
          <span className="btn-icon">📥</span>
          <span className="btn-text">Import</span>
        </button>
        
        <button 
          className={`toolbar-btn export-btn ${waypointCount === 0 ? 'disabled' : ''}`}
          onClick={onExportTrajectory} 
          disabled={waypointCount === 0}
          title="Export Trajectory"
        >
          <span className="btn-icon">📤</span>
          <span className="btn-text">Export</span>
        </button>

        <button
          className={`toolbar-btn primary-btn ${!canSendToSwarm ? 'disabled' : ''}`}
          onClick={onSendToSwarm}
          disabled={!canSendToSwarm}
          title={canSendToSwarm ? 'Send current trajectory to a swarm cluster leader' : 'Add at least one waypoint before sending to swarm'}
        >
          <span className="btn-icon">🧭</span>
          <span className="btn-text">Send to Swarm</span>
        </button>
        
        <button 
          className={`toolbar-btn clear-btn danger ${waypointCount === 0 ? 'disabled' : ''}`}
          onClick={onClearTrajectory} 
          disabled={waypointCount === 0}
          title="Clear All Waypoints"
        >
          <span className="btn-icon">🗑️</span>
          <span className="btn-text">Clear</span>
        </button>
      </div>
      
      <div className="toolbar-group toolbar-view">
        <button 
          className={`toolbar-btn terrain-btn ${showTerrain ? 'active' : ''}`}
          onClick={onToggleTerrain}
          title="Toggle 3D Terrain"
        >
          <span className="btn-icon">🏔️</span>
          <span className="btn-text">Terrain</span>
        </button>
        
        <div className="view-mode-selector">
          <label className="view-mode-label">View:</label>
          <select 
            value={sceneMode} 
            onChange={(e) => onSceneModeChange(e.target.value)}
            className="view-mode-select"
            title="Change View Mode"
          >
            <option value="3D">3D</option>
            <option value="2D">2D</option>
            <option value="Columbus">Columbus</option>
          </select>
        </div>
      </div>
      
      <div className="toolbar-group toolbar-status">
        {/* Trajectory name display */}
        {trajectoryName && (
          <div className="trajectory-name-display">
            <span className="trajectory-name-label">Trajectory:</span>
            <span className="trajectory-name">{trajectoryName}</span>
          </div>
        )}
        
        {/* Waypoint count */}
        <div className="waypoint-count">
          <span className="count-label">Waypoints:</span>
          <span className="count-value">{waypointCount}</span>
        </div>
        
        {/* Save status */}
        <div className="save-status">
          {!saveStatus.saved ? (
            <span className="status-unsaved" title="Trajectory has unsaved changes">
              <span className="status-indicator">●</span>
              <span className="status-text">Unsaved</span>
            </span>
          ) : saveStatus.autoSaveTime ? (
            <span className="status-saved" title={`Auto-saved at ${new Date(saveStatus.autoSaveTime).toLocaleTimeString()}`}>
              <span className="status-indicator">✓</span>
              <span className="status-text">Auto-saved {formatAutoSaveTime(saveStatus.autoSaveTime)}</span>
            </span>
          ) : (
            <span className="status-saved">
              <span className="status-indicator">✓</span>
              <span className="status-text">Saved</span>
            </span>
          )}
        </div>
      </div>

      <div className="toolbar-group toolbar-help">
        <button 
          className="toolbar-btn help-btn"
          title="Show planner shortcuts"
          aria-label="Show planner shortcuts"
          aria-expanded={showShortcutHelp}
          onClick={() => setShowShortcutHelp((prev) => !prev)}
        >
          <span className="btn-icon">⌨️</span>
        </button>
        {showShortcutHelp && (
          <div className="toolbar-shortcut-popover" role="dialog" aria-label="Planner shortcuts">
            <div className="toolbar-shortcut-popover__header">
              <strong>Planner shortcuts</strong>
              <button
                type="button"
                className="toolbar-shortcut-popover__close"
                onClick={() => setShowShortcutHelp(false)}
                aria-label="Close planner shortcuts"
              >
                ✕
              </button>
            </div>
            <ul className="toolbar-shortcut-popover__list">
              <li><kbd>A</kbd> Toggle Add Waypoint mode</li>
              <li><kbd>Ctrl</kbd> + <kbd>Z</kbd> Undo last action</li>
              <li><kbd>Ctrl</kbd> + <kbd>Y</kbd> Redo last action</li>
              <li><kbd>Ctrl</kbd> + <kbd>S</kbd> Save trajectory</li>
              <li><kbd>Ctrl</kbd> + <kbd>O</kbd> Load trajectory</li>
              <li><kbd>Delete</kbd> Delete selected waypoint</li>
              <li><kbd>Esc</kbd> Cancel current operation</li>
              <li><kbd>Enter</kbd> Save inline field edit</li>
            </ul>
          </div>
        )}
      </div>
    </div>
  );
};

TrajectoryToolbar.propTypes = {
  // Original props
  isAddingWaypoint: PropTypes.bool.isRequired,
  onToggleAddWaypoint: PropTypes.func.isRequired,
  onClearTrajectory: PropTypes.func.isRequired,
  onExportTrajectory: PropTypes.func.isRequired,
  showTerrain: PropTypes.bool.isRequired,
  onToggleTerrain: PropTypes.func.isRequired,
  sceneMode: PropTypes.string.isRequired,
  onSceneModeChange: PropTypes.func.isRequired,
  waypointCount: PropTypes.number.isRequired,
  
  canUndo: PropTypes.bool,
  canRedo: PropTypes.bool,
  undoDescription: PropTypes.string,
  redoDescription: PropTypes.string,
  onUndo: PropTypes.func,
  onRedo: PropTypes.func,
  onSave: PropTypes.func,
  onLoad: PropTypes.func,
  onImport: PropTypes.func,
  onSendToSwarm: PropTypes.func,
  canSendToSwarm: PropTypes.bool,
  saveStatus: PropTypes.shape({
    saved: PropTypes.bool,
    autoSaveTime: PropTypes.number
  }),
  trajectoryName: PropTypes.string
};

export default TrajectoryToolbar;
