// src/components/sar/DroneStatusCard.js
import React from 'react';

const DroneStatusCard = ({ droneState, onClick }) => {
  if (!droneState) return null;

  const {
    hw_id,
    state,
    coverage_percent,
    current_waypoint_index,
    total_waypoints,
    status_note,
  } = droneState;

  return (
    <div className={`qs-drone-card ${state || 'ready'}`} onClick={onClick}>
      <div className="qs-drone-card-header">
        <span className="qs-drone-card-name">Drone {hw_id}</span>
        <span className={`qs-state-badge ${state || 'ready'}`}>
          {(state || 'ready').toUpperCase()}
        </span>
      </div>
      <div className="qs-drone-card-progress">
        <div
          className="qs-drone-card-progress-fill"
          style={{ width: `${coverage_percent || 0}%` }}
        />
      </div>
      <div className="qs-drone-card-stats">
        <span>{(coverage_percent || 0).toFixed(1)}%</span>
        <span>WP {current_waypoint_index || 0}/{total_waypoints || 0}</span>
      </div>
      {status_note ? (
        <div className="qs-empty-copy" style={{ marginTop: 6 }}>
          {status_note}
        </div>
      ) : null}
    </div>
  );
};

export default DroneStatusCard;
