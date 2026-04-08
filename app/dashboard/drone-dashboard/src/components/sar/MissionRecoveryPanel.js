import React from 'react';

const ACTIVE_STATES = new Set(['executing', 'paused']);

const formatRelativeTime = (timestamp) => {
  if (!timestamp) return 'No updates';
  const deltaSeconds = Math.max(0, Math.round(Date.now() / 1000 - timestamp));
  if (deltaSeconds < 60) return 'Updated just now';
  if (deltaSeconds < 3600) return `Updated ${Math.floor(deltaSeconds / 60)}m ago`;
  if (deltaSeconds < 86400) return `Updated ${Math.floor(deltaSeconds / 3600)}h ago`;
  return `Updated ${Math.floor(deltaSeconds / 86400)}d ago`;
};

const formatArea = (areaSqM) => {
  if (!areaSqM || areaSqM <= 0) return '--';
  if (areaSqM >= 10000) return `${(areaSqM / 10000).toFixed(1)} ha`;
  return `${Math.round(areaSqM)} m²`;
};

const formatMissionId = (missionId) => {
  if (!missionId) return 'Unknown mission';
  if (missionId.length <= 18) return missionId;
  return `${missionId.slice(0, 8)}…${missionId.slice(-6)}`;
};

const getMissionDisplayName = (mission) => mission?.mission_label || formatMissionId(mission?.mission_id);

const MissionRecoveryPanel = ({
  missions = [],
  currentMissionId = null,
  recoveringMissionId = null,
  loading = false,
  onRecoverMission,
  onStartFreshPlan,
  showStartFresh = false,
}) => {
  const hasAnyMission = missions.length > 0 || currentMissionId;
  if (!hasAnyMission && !showStartFresh) {
    return null;
  }

  return (
    <div className="qs-config-section">
      <div className="qs-recovery-header">
        <div>
          <div className="qs-config-title" style={{ marginBottom: 4 }}>
            Mission Workspace
          </div>
          <div className="qs-recovery-subtitle">
            Reopen a saved QuickScout mission or start a fresh search plan.
          </div>
        </div>
        {showStartFresh && (
          <button
            type="button"
            className="qs-btn qs-btn-secondary"
            onClick={onStartFreshPlan}
          >
            New Search
          </button>
        )}
      </div>

      {missions.length === 0 ? (
        <div className="qs-empty-copy">
          {loading
            ? 'Loading saved QuickScout missions…'
            : 'No saved QuickScout missions yet. Plan a search area to create the first mission package.'}
        </div>
      ) : (
        <div className="qs-mission-catalog">
          {missions.map((mission) => {
            const isCurrent = mission.mission_id === currentMissionId;
            const isRecovering = mission.mission_id === recoveringMissionId;
            const actionLabel = isRecovering ? 'Opening…' : isCurrent ? 'Viewing' : 'Open';

            return (
              <div
                key={mission.mission_id}
                className={`qs-mission-card ${isCurrent ? 'active' : ''}`}
              >
                <div className="qs-mission-card-header">
                  <div className="qs-mission-name-row">
                    <span className="qs-mission-name" title={mission.mission_id}>
                      {getMissionDisplayName(mission)}
                    </span>
                    <span className={`qs-state-badge ${mission.state}`}>
                      {mission.state}
                    </span>
                    {ACTIVE_STATES.has(mission.state) && (
                      <span className="qs-inline-chip">Live</span>
                    )}
                  </div>
                  <button
                    type="button"
                    className="qs-mission-open"
                    onClick={() => onRecoverMission && onRecoverMission(mission.mission_id)}
                    disabled={isRecovering || isCurrent}
                  >
                    {actionLabel}
                  </button>
                </div>

                <div className="qs-mission-meta">
                  <span>{mission.drone_count} drone{mission.drone_count === 1 ? '' : 's'}</span>
                  <span>{formatArea(mission.total_area_sq_m)}</span>
                  <span>{formatRelativeTime(mission.updated_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default MissionRecoveryPanel;
