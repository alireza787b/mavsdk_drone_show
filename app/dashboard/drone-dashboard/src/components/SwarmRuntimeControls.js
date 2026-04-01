import React, { useState } from 'react';
import PropTypes from 'prop-types';
import {
  FaCrosshairs,
  FaPauseCircle,
  FaPlay,
  FaPlaneArrival,
  FaProjectDiagram,
  FaHome,
} from 'react-icons/fa';
import { toast } from 'react-toastify';

import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import { formatDroneLabel } from '../utilities/missionIdentityUtils';
import {
  buildSwarmRuntimeCommand,
  getSwarmRuntimeStartBlockerReason,
  getSwarmRuntimeTelemetrySummary,
  resolveSwarmRuntimeTargets,
  SWARM_RUNTIME_ACTIONS,
  SWARM_RUNTIME_SCOPE,
} from '../utilities/swarmRuntimeUtils';

const ACTION_ICONS = {
  START: <FaPlay />,
  STOP_HOLD: <FaPauseCircle />,
  LAND: <FaPlaneArrival />,
  RTL: <FaHome />,
};

function buildRuntimeBrief(targetDrones = []) {
  const roleCounts = targetDrones.reduce((counts, drone) => {
    if (drone?.role === 'topLeader') {
      counts.topLeaders += 1;
    } else if (drone?.role === 'relayLeader') {
      counts.relayLeaders += 1;
    } else if (drone?.role === 'follower') {
      counts.followers += 1;
    }
    return counts;
  }, {
    topLeaders: 0,
    relayLeaders: 0,
    followers: 0,
  });

  const followerFrames = [...new Set(
    targetDrones
      .filter((drone) => drone?.follow !== '0')
      .map((drone) => drone?.frame)
      .filter(Boolean)
  )];

  const warningCount = targetDrones.reduce(
    (count, drone) => count + (Array.isArray(drone?.warnings) ? drone.warnings.length : 0),
    0
  );

  let frameSummary = 'Leader-only scope';
  if (followerFrames.length === 1) {
    frameSummary = followerFrames[0] === 'body'
      ? 'Body-relative offsets'
      : 'Geographic NED offsets';
  } else if (followerFrames.length > 1) {
    frameSummary = 'Mixed NED + body offsets';
  }

  return {
    roleCounts,
    warningCount,
    frameSummary,
    hasBodyFrameFollowers: followerFrames.includes('body'),
    previewDrones: targetDrones.slice(0, 4),
    remainingCount: Math.max(targetDrones.length - 4, 0),
  };
}

const SwarmRuntimeControls = ({
  viewModel,
  selectedDroneId = null,
  selectedClusterId = null,
  dirtyIds = [],
  pendingSyncIds = [],
  telemetryById = {},
  onReviewSelection = null,
  onOpenMissionConfig = null,
}) => {
  const [scope, setScope] = useState(SWARM_RUNTIME_SCOPE.DRONE);
  const [pendingActionKey, setPendingActionKey] = useState(null);
  const { commandLifecycleCallbacks } = useCommandActivity();

  const {
    selectedDrone,
    cluster: selectedCluster,
    targetIds,
    scopeLabel,
    targetSummary,
  } = resolveSwarmRuntimeTargets(viewModel, scope, selectedDroneId, selectedClusterId);
  const targetDrones = targetIds
    .map((targetId) => viewModel?.dronesById?.[targetId])
    .filter(Boolean);
  const runtimeBrief = buildRuntimeBrief(targetDrones);
  const liveSummary = getSwarmRuntimeTelemetrySummary(targetIds, telemetryById);
  const reviewDroneId = scope === SWARM_RUNTIME_SCOPE.CLUSTER
    ? (selectedCluster?.leaderId || selectedDrone?.hw_id || null)
    : (selectedDrone?.hw_id || null);
  const missionConfigDroneId = scope === SWARM_RUNTIME_SCOPE.CLUSTER
    ? (selectedCluster?.leaderId || null)
    : (selectedDrone?.hw_id || null);

  const startBlockerReason = getSwarmRuntimeStartBlockerReason({
    scope,
    selectedDrone,
    selectedCluster,
    targetIds,
    targetDrones,
    dirtyIds,
    pendingSyncIds,
  });
  const targetedIdSet = new Set(targetIds.map((targetId) => String(targetId)));
  const scopedDirtyIds = dirtyIds.filter((targetId) => targetedIdSet.has(String(targetId)));
  const scopedPendingIds = pendingSyncIds.filter((targetId) => targetedIdSet.has(String(targetId)));
  const nonTargetDirtyCount = dirtyIds.length - scopedDirtyIds.length;
  const nonTargetPendingCount = pendingSyncIds.length - scopedPendingIds.length;
  const hasAnalysisOnlySelection = scope === SWARM_RUNTIME_SCOPE.CLUSTER && selectedClusterId === 'all';
  const hasExplicitClusterOverride = scope === SWARM_RUNTIME_SCOPE.CLUSTER
    && selectedClusterId
    && selectedClusterId !== 'all'
    && selectedCluster?.id === selectedClusterId
    && selectedDrone?.clusterId
    && selectedDrone.clusterId !== selectedClusterId;
  const reviewButtonLabel = scope === SWARM_RUNTIME_SCOPE.CLUSTER ? 'Review leader' : 'Review selected drone';
  const missionConfigButtonLabel = scope === SWARM_RUNTIME_SCOPE.CLUSTER
    ? 'Mission Config (leader)'
    : 'Mission Config';

  const actions = [
    SWARM_RUNTIME_ACTIONS.START,
    SWARM_RUNTIME_ACTIONS.STOP_HOLD,
    SWARM_RUNTIME_ACTIONS.LAND,
    SWARM_RUNTIME_ACTIONS.RTL,
  ];

  const handleAction = async (actionKey) => {
    const action = SWARM_RUNTIME_ACTIONS[actionKey];
    if (!action) {
      return;
    }

    if (actionKey === 'START' && startBlockerReason) {
      toast.error(startBlockerReason);
      return;
    }

    if (targetIds.length === 0) {
      toast.error('No valid Smart Swarm targets are available for this scope.');
      return;
    }

    const confirmationText = [
      `${action.label} will be sent to ${scopeLabel}.`,
      targetSummary,
      '',
      'Single-drone actions remain independent and do not stop Smart Swarm on other drones.',
      '',
      'Continue?',
    ].join('\n');

    if (!window.confirm(confirmationText)) {
      return;
    }

    setPendingActionKey(actionKey);
    try {
      const commandData = buildSwarmRuntimeCommand(actionKey, targetIds);
      commandData.uiMeta = {
        operatorLabel: action.operatorLabel,
        targetLabel: scopeLabel,
        targetDescriptor: targetSummary,
      };
      await submitCommandWithLifecycleFeedback(commandData, {
        ...commandLifecycleCallbacks,
      });
    } catch (error) {
      console.error(`Failed to submit ${action.label}:`, error);
      toast.error(`Failed to submit ${action.label}.`);
    } finally {
      setPendingActionKey(null);
    }
  };

  return (
    <section className="swarm-panel swarm-runtime-panel">
      <div className="swarm-panel__header">
        <div>
          <span className="swarm-selection-panel__eyebrow">Runtime Control</span>
          <h2>Smart Swarm Runtime</h2>
          <p>
            Use selected-drone scope when mixed missions are active. Switch to selected-cluster scope only when
            you intentionally want to start or override the current executable cluster as a group.
          </p>
        </div>
      </div>

      <div className="swarm-runtime-scope">
        <button
          type="button"
          className={`swarm-runtime-scope__button ${scope === SWARM_RUNTIME_SCOPE.DRONE ? 'active' : ''}`}
          onClick={() => setScope(SWARM_RUNTIME_SCOPE.DRONE)}
        >
          <FaCrosshairs />
          Selected Drone
        </button>
        <button
          type="button"
          className={`swarm-runtime-scope__button ${scope === SWARM_RUNTIME_SCOPE.CLUSTER ? 'active' : ''}`}
          onClick={() => setScope(SWARM_RUNTIME_SCOPE.CLUSTER)}
        >
          <FaProjectDiagram />
          Selected Cluster
        </button>
      </div>

      <div className="swarm-runtime-target">
        <strong>{scopeLabel}</strong>
        <span>{targetSummary}</span>
        {startBlockerReason ? (
          <div className="swarm-runtime-target__note warning">{startBlockerReason}</div>
        ) : null}
        {(scopedDirtyIds.length > 0 || scopedPendingIds.length > 0) ? (
          <div className="swarm-runtime-target__note">
            Runtime overrides are always sent immediately. Start Smart Swarm uses the saved assignments for the targeted drones only.
          </div>
        ) : null}
        {(nonTargetDirtyCount > 0 || nonTargetPendingCount > 0) ? (
          <div className="swarm-runtime-target__note">
            Other swarm edits exist outside this target set. They do not block this runtime scope.
          </div>
        ) : null}
        {hasAnalysisOnlySelection ? (
          <div className="swarm-runtime-target__note">
            &quot;All executable clusters&quot; is analysis-only. Cluster runtime scope falls back to the selected drone&apos;s executable cluster, or the first executable cluster if none is selected.
          </div>
        ) : null}
        {hasExplicitClusterOverride ? (
          <div className="swarm-runtime-target__note">
            Cluster runtime scope follows the selected formation-analysis cluster, not necessarily the selected drone&apos;s cluster.
          </div>
        ) : null}
      </div>

      {targetDrones.length > 0 && (
        <div className="swarm-runtime-brief">
          <div className="swarm-runtime-brief__header">
            <div>
              <span className="swarm-selection-panel__eyebrow">Formation Preview</span>
              <strong>Verify target layout and live readiness before sending runtime commands.</strong>
              <p className="swarm-runtime-brief__summary">
                This panel previews the saved follow chain for the current target set and shows a live readiness snapshot when telemetry is available.
              </p>
            </div>
            <div className="swarm-runtime-brief__actions">
              {reviewDroneId && onReviewSelection && (
                <button
                  type="button"
                  className="swarm-runtime-brief__action-button"
                  onClick={() => onReviewSelection(reviewDroneId)}
                >
                  {reviewButtonLabel}
                </button>
              )}
              {missionConfigDroneId && onOpenMissionConfig && (
                <button
                  type="button"
                  className="swarm-runtime-brief__action-button ghost"
                  onClick={() => onOpenMissionConfig(missionConfigDroneId)}
                >
                  {missionConfigButtonLabel}
                </button>
              )}
            </div>
          </div>

          <div className="swarm-runtime-brief__stats">
            <span>{targetDrones.length} drone{targetDrones.length === 1 ? '' : 's'}</span>
            <span>{runtimeBrief.roleCounts.topLeaders} top leader{runtimeBrief.roleCounts.topLeaders === 1 ? '' : 's'}</span>
            <span>{runtimeBrief.roleCounts.relayLeaders} relay</span>
            <span>{runtimeBrief.roleCounts.followers} follower{runtimeBrief.roleCounts.followers === 1 ? '' : 's'}</span>
            <span>{runtimeBrief.frameSummary}</span>
            {runtimeBrief.warningCount > 0 && (
              <span>{runtimeBrief.warningCount} design warning{runtimeBrief.warningCount === 1 ? '' : 's'}</span>
            )}
          </div>

          <div className="swarm-runtime-brief__live">
            <span className="swarm-runtime-brief__live-label">Live Readiness</span>
            <div className="swarm-runtime-brief__stats">
              <span>{liveSummary.total} target drone{liveSummary.total === 1 ? '' : 's'}</span>
              {liveSummary.readyCount > 0 && (
                <span>{liveSummary.readyCount} ready</span>
              )}
              {liveSummary.blockedCount > 0 && (
                <span>{liveSummary.blockedCount} blocked</span>
              )}
              {liveSummary.reviewCount > 0 && (
                <span>{liveSummary.reviewCount} review</span>
              )}
              {liveSummary.linkIssueCount > 0 && (
                <span>{liveSummary.linkIssueCount} telemetry delayed</span>
              )}
              {liveSummary.waitingCount > 0 && (
                <span>{liveSummary.waitingCount} waiting for telemetry</span>
              )}
              {liveSummary.telemetryCount === 0 && (
                <span>Waiting for telemetry snapshot</span>
              )}
            </div>
          </div>

          <div className="swarm-runtime-brief__roster">
            {runtimeBrief.previewDrones.map((drone) => (
              <div key={drone.hw_id} className="swarm-runtime-brief__roster-item">
                <strong>{drone.title}{drone.alias ? ` · ${drone.alias}` : ''}</strong>
                <span>
                  {drone.follow === '0'
                    ? 'Independent leader'
                    : `Follows ${formatDroneLabel(drone.follow)} · ${drone.offsetSummary}`}
                </span>
              </div>
            ))}
            {runtimeBrief.remainingCount > 0 && (
              <div className="swarm-runtime-brief__roster-item more">
                <strong>+{runtimeBrief.remainingCount} more target drones</strong>
                <span>Use Review selection if you need to inspect the full chain before launch.</span>
              </div>
            )}
          </div>

          {runtimeBrief.hasBodyFrameFollowers && (
            <div className="swarm-runtime-target__note">
              Body-frame followers rotate with leader heading in flight. Confirm that this is intentional before start.
            </div>
          )}
        </div>
      )}

      <div className="swarm-runtime-actions">
        {actions.map((action) => {
          const isDisabled = pendingActionKey !== null
            || targetIds.length === 0
            || (action.key === 'START' && Boolean(startBlockerReason));

          return (
            <button
              key={action.key}
              type="button"
              className={`swarm-runtime-action ${action.tone}`}
              onClick={() => handleAction(action.key)}
              disabled={isDisabled}
            >
              <span className="swarm-runtime-action__icon">{ACTION_ICONS[action.key]}</span>
              <span className="swarm-runtime-action__copy">
                <strong>{action.label}</strong>
                <small>{action.description}</small>
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
};

SwarmRuntimeControls.propTypes = {
  viewModel: PropTypes.shape({
    drones: PropTypes.array,
    dronesById: PropTypes.object,
    clusters: PropTypes.array,
  }).isRequired,
  selectedDroneId: PropTypes.string,
  selectedClusterId: PropTypes.string,
  dirtyIds: PropTypes.arrayOf(PropTypes.string),
  pendingSyncIds: PropTypes.arrayOf(PropTypes.string),
  telemetryById: PropTypes.object,
  onReviewSelection: PropTypes.func,
  onOpenMissionConfig: PropTypes.func,
};

export default SwarmRuntimeControls;
