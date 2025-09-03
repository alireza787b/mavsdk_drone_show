// src/components/trajectory/WaypointPanel.js
// PHASE 1 ENHANCEMENTS: Inline waypoint editing + MSL labeling

import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { getSpeedStatus, validateSpeed } from '../../utilities/SpeedCalculator';

const WaypointPanel = ({
  waypoints,
  selectedWaypointId,
  onSelectWaypoint,
  onUpdateWaypoint,
  onDeleteWaypoint,
  onMoveWaypoint,
  onFlyTo
}) => {
  // ENHANCED: Inline editing + panel collapse state management
  const [editingWaypointId, setEditingWaypointId] = useState(null);
  const [editValues, setEditValues] = useState({});
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(window.innerWidth <= 768);
  const editInputRef = useRef(null);

  // Auto-focus when entering edit mode
  useEffect(() => {
    if (editingWaypointId && editInputRef.current) {
      editInputRef.current.focus();
      editInputRef.current.select();
    }
  }, [editingWaypointId]);

  // Handle window resize for responsive behavior
  useEffect(() => {
    const handleResize = () => {
      const newIsMobile = window.innerWidth <= 768;
      setIsMobile(newIsMobile);
      
      // Auto-collapse on mobile if there are many waypoints
      if (newIsMobile && waypoints.length > 3) {
        setIsCollapsed(true);
      }
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [waypoints.length]);

  // Auto-collapse on mobile when waypoints increase
  useEffect(() => {
    if (isMobile && waypoints.length > 5) {
      setIsCollapsed(true);
    }
  }, [waypoints.length, isMobile]);

  if (!waypoints || waypoints.length === 0) {
    return (
      <div className="waypoint-panel">
        <div className="waypoint-panel-header">
          <h3>Waypoints</h3>
        </div>
        <p>No waypoints yet. Click on the map to add waypoints with custom altitude and timing.</p>
      </div>
    );
  }

  // PHASE 1: Inline editing handlers
  const handleEditStart = (waypoint, field) => {
    setEditingWaypointId(waypoint.id);
    setEditValues({
      field,
      latitude: waypoint.latitude,
      longitude: waypoint.longitude,
      altitude: waypoint.altitude,
      timeFromStart: waypoint.timeFromStart || waypoint.time || 0
    });
  };

  const handleEditSave = () => {
    if (!editingWaypointId) return;

    const updates = {};
    const { field } = editValues;

    // Validate and apply changes based on field type
    switch (field) {
      case 'coordinates':
        const lat = parseFloat(editValues.latitude);
        const lng = parseFloat(editValues.longitude);
        if (!isNaN(lat) && !isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
          updates.latitude = lat;
          updates.longitude = lng;
        } else {
          alert('Invalid coordinates. Latitude: -90 to 90, Longitude: -180 to 180');
          return;
        }
        break;
      
      case 'altitude':
        const alt = parseFloat(editValues.altitude);
        if (!isNaN(alt) && alt >= 1 && alt <= 10000) {
          updates.altitude = alt;
        } else {
          alert('Altitude must be between 1 and 10000 meters MSL');
          return;
        }
        break;
      
      case 'time':
        const time = parseFloat(editValues.timeFromStart);
        const waypoint = waypoints.find(wp => wp.id === editingWaypointId);
        const waypointIndex = waypoints.findIndex(wp => wp.id === editingWaypointId);
        const prevWaypoint = waypointIndex > 0 ? waypoints[waypointIndex - 1] : null;
        const nextWaypoint = waypointIndex < waypoints.length - 1 ? waypoints[waypointIndex + 1] : null;
        
        if (!isNaN(time) && time >= 0) {
          // Validate time constraints
          if (prevWaypoint && time <= (prevWaypoint.timeFromStart || 0)) {
            alert(`Time must be greater than previous waypoint time (${(prevWaypoint.timeFromStart || 0)}s)`);
            return;
          }
          if (nextWaypoint && time >= (nextWaypoint.timeFromStart || 0)) {
            alert(`Time must be less than next waypoint time (${(nextWaypoint.timeFromStart || 0)}s)`);
            return;
          }
          updates.timeFromStart = time;
          updates.time = time; // Legacy compatibility
        } else {
          alert('Time must be a positive number');
          return;
        }
        break;
    }

    onUpdateWaypoint(editingWaypointId, updates);
    handleEditCancel();
  };

  const handleEditCancel = () => {
    setEditingWaypointId(null);
    setEditValues({});
  };

  const handleEditKeyPress = (e) => {
    if (e.key === 'Enter') {
      handleEditSave();
    } else if (e.key === 'Escape') {
      handleEditCancel();
    }
  };

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

  // PHASE 1: Render editable field
  const renderEditableField = (waypoint, field, value, displayValue) => {
    const isEditing = editingWaypointId === waypoint.id && editValues.field === field;
    
    if (isEditing) {
      if (field === 'coordinates') {
        return (
          <div className="edit-coordinates">
            <input
              ref={editInputRef}
              type="number"
              step="any"
              value={editValues.latitude}
              onChange={(e) => setEditValues(prev => ({ ...prev, latitude: e.target.value }))}
              onKeyDown={handleEditKeyPress}
              className="edit-input edit-input-small"
              placeholder="Latitude"
            />
            <input
              type="number"
              step="any"
              value={editValues.longitude}
              onChange={(e) => setEditValues(prev => ({ ...prev, longitude: e.target.value }))}
              onKeyDown={handleEditKeyPress}
              className="edit-input edit-input-small"
              placeholder="Longitude"
            />
            <div className="edit-buttons">
              <button onClick={handleEditSave} className="edit-btn save-btn" title="Save (Enter)">✓</button>
              <button onClick={handleEditCancel} className="edit-btn cancel-btn" title="Cancel (Esc)">✕</button>
            </div>
          </div>
        );
      } else {
        return (
          <div className="edit-single">
            <input
              ref={editInputRef}
              type="number"
              step={field === 'time' ? '0.1' : field === 'altitude' ? '1' : 'any'}
              value={editValues[field === 'altitude' ? 'altitude' : field === 'time' ? 'timeFromStart' : 'value']}
              onChange={(e) => setEditValues(prev => ({ 
                ...prev, 
                [field === 'altitude' ? 'altitude' : field === 'time' ? 'timeFromStart' : 'value']: e.target.value 
              }))}
              onKeyDown={handleEditKeyPress}
              className="edit-input"
              placeholder={field === 'altitude' ? 'Altitude MSL (m)' : field === 'time' ? 'Time (s)' : ''}
            />
            <div className="edit-buttons">
              <button onClick={handleEditSave} className="edit-btn save-btn" title="Save (Enter)">✓</button>
              <button onClick={handleEditCancel} className="edit-btn cancel-btn" title="Cancel (Esc)">✕</button>
            </div>
          </div>
        );
      }
    }

    return (
      <span 
        className="detail-value editable" 
        onClick={() => handleEditStart(waypoint, field)}
        title="Click to edit"
      >
        {displayValue}
      </span>
    );
  };

  return (
    <div className={`waypoint-panel ${isCollapsed ? 'collapsed' : 'expanded'} ${isMobile ? 'mobile' : 'desktop'}`}>
      <div className="waypoint-panel-header">
        <div className="header-title-section">
          <h3>Waypoints ({waypoints.length})</h3>
          {waypoints.some(wp => wp.estimatedSpeed > 20) && (
            <div className="speed-warning-summary">
              <span className="speed-indicator speed-impossible">⚠</span>
              {!isCollapsed && <span className="warning-text">High speed detected</span>}
            </div>
          )}
        </div>
        <div className="panel-controls">
          <button
            className={`collapse-toggle ${isCollapsed ? 'collapsed' : 'expanded'}`}
            onClick={() => setIsCollapsed(!isCollapsed)}
            title={isCollapsed ? 'Expand waypoint panel' : 'Collapse waypoint panel'}
            aria-label={isCollapsed ? 'Expand waypoint panel' : 'Collapse waypoint panel'}
          >
            {isCollapsed ? '📋' : '▼'}
          </button>
        </div>
      </div>
      
      {!isCollapsed && (
        <div className="waypoint-list">
          {waypoints.map((waypoint, index) => (
          <div 
            key={waypoint.id}
            className={`waypoint-item ${selectedWaypointId === waypoint.id ? 'selected' : ''} ${
              index > 0 && !waypoint.speedFeasible ? 'speed-warning' : ''
            } ${editingWaypointId === waypoint.id ? 'editing' : ''}`}
            onClick={() => editingWaypointId !== waypoint.id && onSelectWaypoint(waypoint.id)}
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
                  disabled={editingWaypointId === waypoint.id}
                >
                  📍
                </button>
                <button 
                  onClick={(e) => { 
                    e.stopPropagation(); 
                    if (editingWaypointId === waypoint.id) {
                      handleEditCancel();
                    } else {
                      onDeleteWaypoint(waypoint.id); 
                    }
                  }}
                  title={editingWaypointId === waypoint.id ? "Cancel edit" : "Delete waypoint"}
                  className="action-btn delete-btn"
                >
                  {editingWaypointId === waypoint.id ? '✕' : '🗑️'}
                </button>
              </div>
            </div>
            
            <div className="waypoint-details">
              <div className="detail-row">
                <span className="detail-label">Position:</span>
                {renderEditableField(
                  waypoint, 
                  'coordinates', 
                  { lat: waypoint.latitude, lng: waypoint.longitude },
                  `${waypoint.latitude.toFixed(6)}, ${waypoint.longitude.toFixed(6)}`
                )}
              </div>
              
              <div className="detail-row">
                <span className="detail-label">Altitude MSL:</span>
                {renderEditableField(
                  waypoint, 
                  'altitude', 
                  waypoint.altitude,
                  `${waypoint.altitude.toFixed(1)}m`
                )}
              </div>
              
              <div className="detail-row">
                <span className="detail-label">Time:</span>
                {renderEditableField(
                  waypoint, 
                  'time', 
                  waypoint.timeFromStart || waypoint.time || 0,
                  formatTime(waypoint.timeFromStart || waypoint.time || 0)
                )}
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

            {/* PHASE 1: Edit mode help text */}
            {editingWaypointId === waypoint.id && (
              <div className="edit-help">
                <small>Press Enter to save, Escape to cancel</small>
              </div>
            )}
          </div>
          ))}
        </div>
      )}
      
      {/* Summary statistics - always show for quick reference */}
      {waypoints.length > 1 && (
        <div className={`waypoint-summary ${isCollapsed ? 'collapsed' : 'expanded'}`}>
          <div className="summary-item">
            <span className="summary-label">{isCollapsed ? 'Pts:' : 'Total Points:'}</span>
            <span className="summary-value">{waypoints.length}</span>
          </div>
          
          <div className="summary-item">
            <span className="summary-label">{isCollapsed ? 'Time:' : 'Duration:'}</span>
            <span className="summary-value">
              {formatTime(waypoints[waypoints.length - 1]?.timeFromStart || 0)}
            </span>
          </div>
          
          {!isCollapsed && (
            <>
              <div className="summary-item">
                <span className="summary-label">Max Speed:</span>
                <span className="summary-value">
                  {Math.max(...waypoints.slice(1).map(wp => wp.estimatedSpeed || 0)).toFixed(1)}m/s
                </span>
              </div>
              
              <div className="summary-item">
                <span className="summary-label">Max Alt MSL:</span>
                <span className="summary-value">
                  {Math.max(...waypoints.map(wp => wp.altitude)).toFixed(1)}m
                </span>
              </div>
            </>
          )}
        </div>
      )}

      {/* Enhanced instructions - responsive */}
      {waypoints.length > 0 && !editingWaypointId && !isCollapsed && (
        <div className="edit-instructions">
          <small>
            💡 {isMobile ? 'Tap to edit values' : 'Click any value to edit inline'}. 
            {!isMobile && 'Drag waypoints on map to reposition.'}
          </small>
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