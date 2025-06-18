// src/components/trajectory/WaypointPanel.js
import React, { useState } from 'react';
import {
  FaTrash,
  FaArrowUp,
  FaArrowDown,
  FaCrosshairs,
  FaClock,
  FaMountain,
  FaTachometerAlt,
  FaRulerVertical,
  FaChevronDown,
  FaChevronRight,
  FaMapMarkerAlt
} from 'react-icons/fa';
import '../../styles/WaypointPanel.css';

const WaypointPanel = ({
  waypoints,
  selectedWaypointId,
  onSelectWaypoint,
  onUpdateWaypoint,
  onDeleteWaypoint,
  onMoveWaypoint,
  onFlyTo,
}) => {
  const [expandedItems, setExpandedItems] = useState(new Set());

  const selectedWaypoint = waypoints.find(wp => wp.id === selectedWaypointId);

  const toggleExpand = (id) => {
    const newExpanded = new Set(expandedItems);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedItems(newExpanded);
  };

  const formatCoordinate = (value, isLat) => {
    const absValue = Math.abs(value);
    const degrees = Math.floor(absValue);
    const minutes = Math.floor((absValue - degrees) * 60);
    const seconds = ((absValue - degrees - minutes / 60) * 3600).toFixed(2);
    const direction = isLat 
      ? (value >= 0 ? 'N' : 'S')
      : (value >= 0 ? 'E' : 'W');
    
    return `${degrees}°${minutes}'${seconds}" ${direction}`;
  };

  return (
    <div className="waypoint-panel">
      <div className="panel-header">
        <h3>
          <FaMapMarkerAlt className="header-icon" />
          Waypoints ({waypoints.length})
        </h3>
      </div>

      {waypoints.length === 0 ? (
        <div className="empty-state">
          <p>No waypoints added yet.</p>
          <p className="hint">Click "Add Waypoint" and then click on the map to add waypoints.</p>
        </div>
      ) : (
        <div className="waypoint-list">
          {waypoints.map((waypoint, index) => {
            const isExpanded = expandedItems.has(waypoint.id);
            const isSelected = selectedWaypointId === waypoint.id;
            
            return (
              <div
                key={waypoint.id}
                className={`waypoint-item ${isSelected ? 'selected' : ''}`}
              >
                <div 
                  className="waypoint-header"
                  onClick={() => onSelectWaypoint(waypoint.id)}
                >
                  <button
                    className="expand-btn"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleExpand(waypoint.id);
                    }}
                  >
                    {isExpanded ? <FaChevronDown /> : <FaChevronRight />}
                  </button>
                  
                  <span className={`waypoint-number ${index === 0 ? 'start' : index === waypoints.length - 1 ? 'end' : ''}`}>
                    {index + 1}
                  </span>
                  
                  <input
                    className="waypoint-name"
                    value={waypoint.name}
                    onChange={(e) =>
                      onUpdateWaypoint(waypoint.id, { name: e.target.value })
                    }
                    onClick={(e) => e.stopPropagation()}
                  />
                  
                  <div className="waypoint-actions">
                    <button
                      className="action-btn"
                      onClick={(e) => {
                        e.stopPropagation();
                        onFlyTo(waypoint);
                      }}
                      title="Fly to waypoint"
                    >
                      <FaCrosshairs />
                    </button>
                    {index > 0 && (
                      <button
                        className="action-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onMoveWaypoint(index, index - 1);
                        }}
                        title="Move up"
                      >
                        <FaArrowUp />
                      </button>
                    )}
                    {index < waypoints.length - 1 && (
                      <button
                        className="action-btn"
                        onClick={(e) => {
                          e.stopPropagation();
                          onMoveWaypoint(index, index + 1);
                        }}
                        title="Move down"
                      >
                        <FaArrowDown />
                      </button>
                    )}
                    <button
                      className="action-btn delete"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (window.confirm(`Delete ${waypoint.name}?`)) {
                          onDeleteWaypoint(waypoint.id);
                        }
                      }}
                      title="Delete waypoint"
                    >
                      <FaTrash />
                    </button>
                  </div>
                </div>

                <div className="waypoint-summary">
                  <span>Alt: {waypoint.altitude.toFixed(0)}m</span>
                  <span>AGL: {(waypoint.altitude - waypoint.terrainHeight).toFixed(0)}m</span>
                  <span>Time: {waypoint.time.toFixed(1)}s</span>
                </div>

                {isExpanded && (
                  <div className="waypoint-details">
                    <div className="detail-section">
                      <h4>Coordinates</h4>
                      <div className="detail-row">
                        <span className="detail-label">Latitude:</span>
                        <span className="detail-value">{waypoint.latitude.toFixed(6)}°</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">Longitude:</span>
                        <span className="detail-value">{waypoint.longitude.toFixed(6)}°</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">DMS:</span>
                        <span className="detail-value small">
                          {formatCoordinate(waypoint.latitude, true)}<br />
                          {formatCoordinate(waypoint.longitude, false)}
                        </span>
                      </div>
                    </div>

                    <div className="detail-section">
                      <h4>Altitude</h4>
                      <div className="detail-row">
                        <span className="detail-label">
                          <FaRulerVertical /> MSL:
                        </span>
                        <input
                          type="number"
                          className="detail-input"
                          value={waypoint.altitude}
                          onChange={(e) =>
                            onUpdateWaypoint(waypoint.id, {
                              altitude: parseFloat(e.target.value) || 0,
                            })
                          }
                          step="1"
                        />
                        <span className="detail-unit">m</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">
                          <FaMountain /> Terrain:
                        </span>
                        <span className="detail-value">{waypoint.terrainHeight.toFixed(1)}m</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">AGL:</span>
                        <span className="detail-value highlight">
                          {(waypoint.altitude - waypoint.terrainHeight).toFixed(1)}m
                        </span>
                      </div>
                    </div>

                    <div className="detail-section">
                      <h4>Flight Parameters</h4>
                      <div className="detail-row">
                        <span className="detail-label">
                          <FaClock /> Time:
                        </span>
                        <input
                          type="number"
                          className="detail-input"
                          value={waypoint.time}
                          onChange={(e) =>
                            onUpdateWaypoint(waypoint.id, {
                              time: parseFloat(e.target.value) || 0,
                            })
                          }
                          step="0.1"
                        />
                        <span className="detail-unit">s</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">
                          <FaTachometerAlt /> Speed:
                        </span>
                        <input
                          type="number"
                          className="detail-input"
                          value={waypoint.speed || 10}
                          onChange={(e) =>
                            onUpdateWaypoint(waypoint.id, {
                              speed: parseFloat(e.target.value) || 10,
                            })
                          }
                          step="0.1"
                        />
                        <span className="detail-unit">m/s</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default WaypointPanel;
