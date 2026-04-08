// src/components/sar/MissionMonitorSidebar.js
/**
 * Monitor mode sidebar: drone status cards and POI list.
 */

import React from 'react';
import DroneStatusCard from './DroneStatusCard';
import MissionRecoveryPanel from './MissionRecoveryPanel';

const MissionMonitorSidebar = ({
  missionStatus,
  pois,
  onDroneClick,
  onPOIClick,
  missionCatalog,
  currentMissionId,
  recoveringMissionId,
  loadingMissionCatalog,
  onRecoverMission,
}) => {
  const droneStates = missionStatus?.drone_states || {};
  const sortedDrones = Object.values(droneStates).sort((a, b) =>
    (a.hw_id || '').localeCompare(b.hw_id || '')
  );

  return (
    <div className="qs-sidebar">
      <div className="qs-sidebar-header">Mission Monitor</div>
      <div className="qs-sidebar-content">
        <MissionRecoveryPanel
          missions={missionCatalog}
          currentMissionId={currentMissionId}
          recoveringMissionId={recoveringMissionId}
          loading={loadingMissionCatalog}
          onRecoverMission={onRecoverMission}
        />

        {/* Drone Status Cards */}
        <div className="qs-config-section">
          <div className="qs-config-title">Drones ({sortedDrones.length})</div>
          {sortedDrones.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {sortedDrones.map((ds) => (
                <DroneStatusCard
                  key={ds.hw_id}
                  droneState={ds}
                  onClick={() => onDroneClick && onDroneClick(ds.hw_id)}
                />
              ))}
            </div>
          ) : (
            <div className="qs-empty-copy">
              Select or reopen a mission to monitor live drone progress and POIs.
            </div>
          )}
        </div>

        {/* POI List */}
        {pois && pois.length > 0 && (
          <div className="qs-config-section">
            <div className="qs-config-title">Points of Interest ({pois.length})</div>
            <div className="qs-poi-list">
              {pois.map((poi) => (
                <div
                  key={poi.id}
                  className="qs-poi-item"
                  onClick={() => onPOIClick && onPOIClick(poi)}
                >
                  <div className={`qs-poi-marker ${poi.priority || 'medium'}`} />
                  <span>{poi.type || 'Unknown'}</span>
                  <span style={{ marginLeft: 'auto', color: 'var(--color-text-tertiary)' }}>
                    {poi.priority}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default MissionMonitorSidebar;
