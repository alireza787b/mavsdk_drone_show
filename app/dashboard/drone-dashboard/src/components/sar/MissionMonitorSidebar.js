// src/components/sar/MissionMonitorSidebar.js
/**
 * Monitor mode sidebar: drone status cards and POI list.
 */

import React from 'react';
import DroneStatusCard from './DroneStatusCard';
import MissionRecoveryPanel from './MissionRecoveryPanel';
import {
  buildQuickScoutGeometrySummary,
  formatQuickScoutArea,
  formatQuickScoutDuration,
  getQuickScoutMissionTemplateLabel,
} from '../../utilities/quickScoutMissionPresentation';

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
  missionLabel,
  missionTemplate,
  missionBrief,
  totalAreaSqM,
  estimatedCoverageTimeS,
  searchArea,
  searchCenter,
  searchRadiusM,
  searchPath,
  corridorWidthM,
}) => {
  const droneStates = missionStatus?.drone_states || {};
  const sortedDrones = Object.values(droneStates).sort((a, b) =>
    (a.hw_id || '').localeCompare(b.hw_id || '')
  );
  const geometrySummary = buildQuickScoutGeometrySummary({
    missionTemplate,
    totalAreaSqM,
    searchArea,
    searchCenter,
    searchRadiusM,
    searchPath,
    corridorWidthM,
  });

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

        {currentMissionId && (
          <div className="qs-config-section">
            <div className="qs-config-title">Mission Package</div>
            <div className="qs-launch-review__grid">
              <div className="qs-launch-review__metric">
                <span className="qs-launch-review__metric-label">Mission</span>
                <strong className="qs-launch-review__metric-value">
                  {missionLabel || currentMissionId}
                </strong>
              </div>
              <div className="qs-launch-review__metric">
                <span className="qs-launch-review__metric-label">Template</span>
                <strong className="qs-launch-review__metric-value">
                  {getQuickScoutMissionTemplateLabel(missionTemplate)}
                </strong>
              </div>
              <div className="qs-launch-review__metric">
                <span className="qs-launch-review__metric-label">Area</span>
                <strong className="qs-launch-review__metric-value">
                  {formatQuickScoutArea(totalAreaSqM)}
                </strong>
              </div>
              <div className="qs-launch-review__metric">
                <span className="qs-launch-review__metric-label">Coverage Time</span>
                <strong className="qs-launch-review__metric-value">
                  {formatQuickScoutDuration(estimatedCoverageTimeS)}
                </strong>
              </div>
            </div>

            <div className="qs-launch-review__brief" style={{ marginTop: 10 }}>
              <span className="qs-launch-review__brief-label">{geometrySummary.title}</span>
              <div className="qs-launch-review__chip-row">
                {geometrySummary.chips.map((chip) => (
                  <span key={chip} className="qs-inline-chip">{chip}</span>
                ))}
              </div>
              <p>{geometrySummary.note}</p>
            </div>

            {missionBrief ? (
              <div className="qs-empty-copy" style={{ marginTop: 8 }}>
                {missionBrief}
              </div>
            ) : null}
          </div>
        )}

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
