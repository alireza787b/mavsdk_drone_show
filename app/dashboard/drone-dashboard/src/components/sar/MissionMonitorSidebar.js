// src/components/sar/MissionMonitorSidebar.js
/**
 * Monitor mode sidebar: drone status cards and findings review.
 */

import React from 'react';
import DroneStatusCard from './DroneStatusCard';
import FindingReviewPanel from './FindingReviewPanel';
import MissionRecoveryPanel from './MissionRecoveryPanel';
import {
  buildQuickScoutGeometrySummary,
  formatQuickScoutArea,
  formatQuickScoutDuration,
  getQuickScoutMissionPhaseLabel,
  getQuickScoutMissionTemplateLabel,
} from '../../utilities/quickScoutMissionPresentation';

const MissionMonitorSidebar = ({
  missionStatus,
  findings,
  onDroneClick,
  onFindingClick,
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
  selectedFinding,
  onFindingSelect,
  savingFinding,
  deletingFinding,
  onSaveFinding,
  onDeleteFinding,
  onFocusFinding,
  onSeedFollowUpFromFinding,
}) => {
  const droneStates = missionStatus?.drone_states || {};
  const sortedDrones = Object.values(droneStates).sort((a, b) =>
    (a.hw_id || '').localeCompare(b.hw_id || '')
  );
  const operationPhase = missionStatus?.operation_phase || 'planning';
  const statusSummary = missionStatus?.status_summary || '';
  const operatorGuidance = missionStatus?.recommended_operator_action || '';
  const lastCommandSummary = missionStatus?.last_command_summary || null;
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
                <span className="qs-launch-review__metric-label">Phase</span>
                <strong className="qs-launch-review__metric-value">
                  {getQuickScoutMissionPhaseLabel(operationPhase)}
                </strong>
              </div>
              <div className="qs-launch-review__metric">
                <span className="qs-launch-review__metric-label">Coverage Time</span>
                <strong className="qs-launch-review__metric-value">
                  {formatQuickScoutDuration(estimatedCoverageTimeS)}
                </strong>
              </div>
            </div>

            {statusSummary ? (
              <div className="qs-launch-review__brief" style={{ marginTop: 10 }}>
                <span className="qs-launch-review__brief-label">Operational Status</span>
                <p>{statusSummary}</p>
                {operatorGuidance ? <p style={{ marginTop: 6 }}>{operatorGuidance}</p> : null}
              </div>
            ) : null}

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

            {lastCommandSummary?.message ? (
              <div className="qs-launch-review__brief" style={{ marginTop: 10 }}>
                <span className="qs-launch-review__brief-label">Last Control Outcome</span>
                <div className="qs-launch-review__chip-row">
                  {lastCommandSummary?.action ? (
                    <span className="qs-inline-chip">
                      {String(lastCommandSummary.action).replace(/_/g, ' ')}
                    </span>
                  ) : null}
                  {lastCommandSummary?.effect ? (
                    <span className="qs-inline-chip">
                      {String(lastCommandSummary.effect).replace(/_/g, ' ')}
                    </span>
                  ) : null}
                </div>
                <p>{lastCommandSummary.message}</p>
                {lastCommandSummary.operator_guidance ? (
                  <p style={{ marginTop: 6 }}>{lastCommandSummary.operator_guidance}</p>
                ) : null}
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
              Select or reopen a mission to monitor live drone progress and findings.
            </div>
          )}
        </div>

        {/* Findings */}
        <div className="qs-config-section">
          <div className="qs-config-title">Findings ({findings?.length || 0})</div>
          {findings && findings.length > 0 ? (
            <div className="qs-finding-list">
              {findings.map((finding) => (
                <div
                  key={finding.id}
                  className={`qs-finding-item ${selectedFinding?.id === finding.id ? 'selected' : ''}`}
                  onClick={() => {
                    onFindingSelect?.(finding);
                    onFindingClick?.(finding);
                  }}
                >
                  <div className={`qs-finding-marker ${finding.priority || 'medium'}`} />
                  <div className="qs-finding-item__body">
                    <strong>{finding.summary || 'Unreviewed observation'}</strong>
                    <span>
                      {(finding.type || 'other').replace(/_/g, ' ')} · {(finding.status || 'new').replace(/_/g, ' ')}
                    </span>
                  </div>
                  <span className="qs-finding-item__priority">
                    {finding.priority}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="qs-empty-copy" style={{ marginBottom: 10 }}>
              Mark findings from the map to capture observations, triage them, and keep the mission handoff clean.
            </div>
          )}

          <FindingReviewPanel
            finding={selectedFinding}
            saving={savingFinding}
            deleting={deletingFinding}
            onSaveFinding={onSaveFinding}
            onDeleteFinding={onDeleteFinding}
            onFocusFinding={onFocusFinding}
            onSeedFollowUpFromFinding={onSeedFollowUpFromFinding}
          />
        </div>
      </div>
    </div>
  );
};

export default MissionMonitorSidebar;
