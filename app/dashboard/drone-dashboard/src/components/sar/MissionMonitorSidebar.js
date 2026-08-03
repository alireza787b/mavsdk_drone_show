// src/components/sar/MissionMonitorSidebar.js
/**
 * Monitor mode sidebar: drone status cards and findings review.
 */

import React from 'react';
import DroneStatusCard from './DroneStatusCard';
import FindingReviewPanel from './FindingReviewPanel';
import MissionHandoffPanel from './MissionHandoffPanel';
import MissionRecoveryPanel from './MissionRecoveryPanel';
import {
  buildQuickScoutGeometrySummary,
  formatQuickScoutArea,
  formatQuickScoutDuration,
  getQuickScoutCommandLifecycleMessage,
  getQuickScoutMissionPhaseLabel,
  getQuickScoutMissionTemplateLabel,
} from '../../utilities/quickScoutMissionPresentation';

const MissionMonitorSidebar = ({
  missionStatus,
  statusError,
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
  missionHandoff,
  loadingMissionHandoff,
  onCopyMissionHandoff,
  onExportMissionHandoff,
}) => {
  const droneStates = missionStatus?.drone_states || {};
  const sortedDrones = Object.values(droneStates).sort((a, b) => {
    const leftPos = Number.isFinite(Number(a.pos_id)) ? Number(a.pos_id) : Number.POSITIVE_INFINITY;
    const rightPos = Number.isFinite(Number(b.pos_id)) ? Number(b.pos_id) : Number.POSITIVE_INFINITY;
    if (leftPos !== rightPos) {
      return leftPos - rightPos;
    }
    return (a.hw_id || '').localeCompare(b.hw_id || '');
  });
  const operationPhase = missionStatus?.operation_phase || 'planning';
  const statusSummary = missionStatus?.status_summary || '';
  const operatorGuidance = missionStatus?.recommended_operator_action || '';
  const latestCommandBatch = missionStatus?.latest_command_batch || null;
  const commandTargetCounts = Object.values(latestCommandBatch?.targets || {}).reduce((counts, target) => {
    const state = target?.state || 'tracking_unavailable';
    counts[state] = (counts[state] || 0) + 1;
    return counts;
  }, {});
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

        {statusError ? (
          <div className="qs-empty-copy qs-gap-bottom" role="alert">
            Mission status refresh failed: {statusError}. Last displayed state may be stale.
          </div>
        ) : null}

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
              <div className="qs-launch-review__brief qs-stack-offset-lg">
                <span className="qs-launch-review__brief-label">Operational Status</span>
                <p>{statusSummary}</p>
                {operatorGuidance ? <p className="qs-stack-tight">{operatorGuidance}</p> : null}
              </div>
            ) : null}

            <div className="qs-launch-review__brief qs-stack-offset-lg">
              <span className="qs-launch-review__brief-label">{geometrySummary.title}</span>
              <div className="qs-launch-review__chip-row">
                {geometrySummary.chips.map((chip) => (
                  <span key={chip} className="qs-inline-chip">{chip}</span>
                ))}
              </div>
              <p>{geometrySummary.note}</p>
            </div>

            {missionBrief ? (
              <div className="qs-empty-copy qs-stack-offset">
                {missionBrief}
              </div>
            ) : null}

            {latestCommandBatch ? (
              <div className="qs-launch-review__brief qs-stack-offset-lg">
                <span className="qs-launch-review__brief-label">Latest Tracked Command</span>
                <div className="qs-launch-review__chip-row">
                  {latestCommandBatch.action ? (
                    <span className="qs-inline-chip">
                      {String(latestCommandBatch.action).replace(/_/g, ' ')}
                    </span>
                  ) : null}
                  {latestCommandBatch.state ? (
                    <span className="qs-inline-chip">
                      {String(latestCommandBatch.state).replace(/_/g, ' ')}
                    </span>
                  ) : null}
                  {Object.entries(commandTargetCounts).map(([state, count]) => (
                    <span className="qs-inline-chip" key={state}>
                      {count} {String(state).replace(/_/g, ' ')}
                    </span>
                  ))}
                </div>
                <p>{getQuickScoutCommandLifecycleMessage(latestCommandBatch)}</p>
                {latestCommandBatch.trigger_time ? (
                  <p className="qs-stack-tight">
                    Shared trigger: {new Date(latestCommandBatch.trigger_time * 1000).toLocaleString()}
                  </p>
                ) : null}
                {latestCommandBatch.receipt?.tracking_url ? (
                  <a href={latestCommandBatch.receipt.tracking_url} target="_blank" rel="noreferrer">
                    Open command tracker
                  </a>
                ) : null}
              </div>
            ) : null}
          </div>
        )}

        <MissionHandoffPanel
          handoff={missionHandoff}
          loading={loadingMissionHandoff}
          onCopyBrief={onCopyMissionHandoff}
          onExportJson={onExportMissionHandoff}
        />

        {/* Drone Status Cards */}
        <div className="qs-config-section">
          <div className="qs-config-title">Drones ({sortedDrones.length})</div>
          {sortedDrones.length > 0 ? (
            <div className="qs-drone-status-list">
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
            <div className="qs-empty-copy qs-gap-bottom">
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
