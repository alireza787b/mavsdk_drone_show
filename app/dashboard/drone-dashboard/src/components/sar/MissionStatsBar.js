// src/components/sar/MissionStatsBar.js
import React from 'react';
import { getQuickScoutMissionPhaseLabel } from '../../utilities/quickScoutMissionPresentation';

const formatTime = (seconds) => {
  if (!seconds || seconds <= 0) return '--:--';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, '0')}`;
};

const MissionStatsBar = ({ missionStatus }) => {
  if (!missionStatus) return null;

  const coverage = missionStatus.total_coverage_percent || 0;
  const elapsed = missionStatus.elapsed_time_s || 0;
  const state = missionStatus.state || 'unknown';
  const phase = missionStatus.operation_phase || 'planning';
  const droneCount = Object.keys(missionStatus.drone_states || {}).length;
  const statusSummary = missionStatus.status_summary || 'Awaiting mission activity.';
  const guidance = missionStatus.recommended_operator_action || null;

  return (
    <div className="qs-stats-bar">
      <div className="qs-stat">
        <span className="qs-stat-label">Status:</span>
        <span className={`qs-stat-value ${state === 'executing' ? 'success' : state === 'paused' ? 'warning' : ''}`}>
          {state.toUpperCase()}
        </span>
      </div>
      <div className="qs-stat">
        <span className="qs-stat-label">Phase:</span>
        <span className="qs-stat-value">{getQuickScoutMissionPhaseLabel(phase)}</span>
      </div>
      <div className="qs-stat">
        <span className="qs-stat-label">Drones:</span>
        <span className="qs-stat-value">{droneCount}</span>
      </div>
      <div className="qs-stat">
        <span className="qs-stat-label">Coverage:</span>
        <span className="qs-stat-value success">{coverage.toFixed(1)}%</span>
      </div>
      <div className="qs-progress-bar">
        <div className="qs-progress-fill" style={{ '--qs-progress-percent': `${coverage}%` }} />
      </div>
      <div className="qs-stat">
        <span className="qs-stat-label">Elapsed:</span>
        <span className="qs-stat-value">{formatTime(elapsed)}</span>
      </div>
      <div className="qs-empty-copy qs-stats-summary">
        {statusSummary}
        {guidance ? ` ${guidance}` : ''}
      </div>
    </div>
  );
};

export default MissionStatsBar;
