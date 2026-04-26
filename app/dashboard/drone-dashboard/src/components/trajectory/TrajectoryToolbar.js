// src/components/trajectory/TrajectoryToolbar.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  MdAddLocationAlt,
  MdCheckCircle,
  MdClose,
  MdDelete,
  MdExplore,
  MdFileDownload,
  MdFileUpload,
  MdFolderOpen,
  MdKeyboard,
  MdRedo,
  MdSave,
  MdTerrain,
  MdUndo,
} from 'react-icons/md';
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
  terrainControlsAvailable = true,
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
  saveStatus = { dirty: false, autoSaveTime: null, persistedAt: null },
  trajectoryName = '',
  canSendToSwarm = false,
  missionReadiness = {
    posture: {
      tone: 'neutral',
      label: 'Not ready',
      summary: 'Add waypoints before assigning this route to a cluster.',
      transferLabel: 'Assign to Cluster',
    },
  },
}) => {
  const [showShortcutHelp, setShowShortcutHelp] = useState(false);
  const isDirty = typeof saveStatus?.dirty === 'boolean' ? saveStatus.dirty : !saveStatus?.saved;
  const handoffPosture = missionReadiness?.posture || {};
  const handoffTone = handoffPosture.tone || 'neutral';
  const handoffLabel = handoffPosture.label || 'Not ready';
  const handoffSummary = handoffPosture.summary || 'Add waypoints before assigning this route to a cluster.';
  const handoffActionLabel = handoffPosture.transferLabel || 'Assign to Cluster';

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
          data-help="Add Waypoint Mode (A)"
        >
          <MdAddLocationAlt className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Add Waypoint</span>
        </button>
        
        <div className="toolbar-separator" />
        
        <button 
          className={`toolbar-btn undo-btn ${!canUndo ? 'disabled' : ''}`}
          onClick={onUndo}
          disabled={!canUndo}
          data-help={canUndo ? `Undo: ${undoDescription} (Ctrl+Z)` : 'Nothing to undo'}
        >
          <MdUndo className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Undo</span>
        </button>
        
        <button 
          className={`toolbar-btn redo-btn ${!canRedo ? 'disabled' : ''}`}
          onClick={onRedo}
          disabled={!canRedo}
          data-help={canRedo ? `Redo: ${redoDescription} (Ctrl+Y)` : 'Nothing to redo'}
        >
          <MdRedo className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Redo</span>
        </button>
      </div>

      <div className="toolbar-group toolbar-file">
        <button 
          className="toolbar-btn save-btn"
          onClick={onSave}
          data-help="Save Trajectory (Ctrl+S)"
        >
          <MdSave className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Save</span>
          {isDirty && <span className="unsaved-indicator" aria-hidden="true" />}
        </button>
        
        <button 
          className="toolbar-btn load-btn"
          onClick={onLoad}
          data-help="Load Trajectory (Ctrl+O)"
        >
          <MdFolderOpen className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Load</span>
        </button>

        <button
          className="toolbar-btn import-btn"
          onClick={onImport}
          data-help="Import a leader-route CSV or planner JSON"
        >
          <MdFileUpload className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Import</span>
        </button>
        
        <button 
          className={`toolbar-btn export-btn ${waypointCount === 0 ? 'disabled' : ''}`}
          onClick={onExportTrajectory} 
          disabled={waypointCount === 0}
          data-help="Export the current leader route"
        >
          <MdFileDownload className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Export</span>
        </button>

        <button
          className={`toolbar-btn primary-btn ${!canSendToSwarm ? 'disabled' : ''}`}
          onClick={onSendToSwarm}
          disabled={!canSendToSwarm}
          data-help={canSendToSwarm ? `${handoffActionLabel}. ${handoffSummary}` : 'Add at least one waypoint before assigning a leader path to a cluster'}
        >
          <MdExplore className="btn-icon" aria-hidden="true" />
          <span className="btn-text">{handoffActionLabel}</span>
        </button>
        
        <button 
          className={`toolbar-btn clear-btn danger ${waypointCount === 0 ? 'disabled' : ''}`}
          onClick={onClearTrajectory} 
          disabled={waypointCount === 0}
          data-help="Clear All Waypoints"
        >
          <MdDelete className="btn-icon" aria-hidden="true" />
          <span className="btn-text">Clear</span>
        </button>
      </div>
      
      <div className="toolbar-group toolbar-view">
        {terrainControlsAvailable ? (
          <>
            <button
              className={`toolbar-btn terrain-btn ${showTerrain ? 'active' : ''}`}
              onClick={onToggleTerrain}
              data-help="Toggle 3D Terrain"
            >
              <MdTerrain className="btn-icon" aria-hidden="true" />
              <span className="btn-text">Terrain</span>
            </button>

            <div className="view-mode-selector">
              <label className="view-mode-label">View:</label>
              <select
                value={sceneMode}
                onChange={(e) => onSceneModeChange(e.target.value)}
                className="view-mode-select"
                data-help="Change View Mode"
              >
                <option value="3D">3D</option>
                <option value="2D">2D</option>
                <option value="Columbus">Columbus</option>
              </select>
            </div>
          </>
        ) : (
          <div
            className="trajectory-map-fallback-note"
            data-help="Mapbox 3D terrain controls are unavailable in the Leaflet fallback map. Authoring remains available in 2D."
          >
            <span className="trajectory-map-fallback-note__label">Map</span>
            <strong className="trajectory-map-fallback-note__value">2D fallback</strong>
          </div>
        )}
      </div>
      
      <div className="toolbar-group toolbar-status">
        <div
          className={`trajectory-handoff-status trajectory-handoff-status--${handoffTone}`}
          data-help={handoffSummary}
        >
          <span className="trajectory-handoff-status__label">Handoff</span>
          <strong className="trajectory-handoff-status__value">{handoffLabel}</strong>
        </div>

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
          {isDirty ? (
            <span
              className="status-unsaved"
              data-help={saveStatus.autoSaveTime
                ? `Working draft auto-saved at ${new Date(saveStatus.autoSaveTime).toLocaleTimeString()}`
                : 'Trajectory draft has unsaved library changes'}
            >
              <span className="status-indicator status-indicator--pending" aria-hidden="true" />
              <span className="status-text">
                {saveStatus.autoSaveTime
                  ? `Draft auto-saved ${formatAutoSaveTime(saveStatus.autoSaveTime)}`
                  : 'Unsaved draft'}
              </span>
            </span>
          ) : saveStatus.persistedAt ? (
            <span className="status-saved" data-help={`Saved at ${new Date(saveStatus.persistedAt).toLocaleTimeString()}`}>
              <MdCheckCircle className="status-indicator" aria-hidden="true" />
              <span className="status-text">Saved</span>
            </span>
          ) : saveStatus.autoSaveTime ? (
            <span className="status-saved" data-help={`Auto-saved at ${new Date(saveStatus.autoSaveTime).toLocaleTimeString()}`}>
              <MdCheckCircle className="status-indicator" aria-hidden="true" />
              <span className="status-text">Auto-saved {formatAutoSaveTime(saveStatus.autoSaveTime)}</span>
            </span>
          ) : (
            <span className="status-saved">
              <MdCheckCircle className="status-indicator" aria-hidden="true" />
              <span className="status-text">Saved</span>
            </span>
          )}
        </div>
      </div>

      <div className="toolbar-group toolbar-help">
        <button 
          className="toolbar-btn help-btn"
          data-help="Show planner shortcuts"
          aria-label="Show planner shortcuts"
          aria-expanded={showShortcutHelp}
          onClick={() => setShowShortcutHelp((prev) => !prev)}
        >
          <MdKeyboard className="btn-icon" aria-hidden="true" />
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
                <MdClose aria-hidden="true" />
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
  terrainControlsAvailable: PropTypes.bool,
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
  missionReadiness: PropTypes.shape({
    posture: PropTypes.shape({
      tone: PropTypes.string,
      label: PropTypes.string,
      summary: PropTypes.string,
      transferLabel: PropTypes.string,
    }),
  }),
  saveStatus: PropTypes.shape({
    dirty: PropTypes.bool,
    saved: PropTypes.bool,
    autoSaveTime: PropTypes.number,
    persistedAt: PropTypes.number,
  }),
  trajectoryName: PropTypes.string
};

export default TrajectoryToolbar;
