// src/components/CommandSender.js

import React, { useMemo, useReducer, useState } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import PrecisionMoveDialog from './PrecisionMoveDialog';
import CommandPreflightSummary from './CommandPreflightSummary';
import ClusterScopeBar from './ClusterScopeBar';
import { toast } from 'react-toastify';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faRocket, faCog } from '@fortawesome/free-solid-svg-icons';
import {
  DRONE_MISSION_TYPES,
  DRONE_ACTION_TYPES,
  getCommandName,
} from '../constants/droneConstants';
import {
  submitCommandWithLifecycleFeedback,
} from '../utilities/commandLifecycleFeedback';
import {
  formatClockOffsetLabel,
  formatCommandAbsoluteTime,
  getFleetReferenceClock,
} from '../utilities/commandScheduling';
import {
  DRONE_SEARCH_HELP_TEXT,
  DRONE_SEARCH_PLACEHOLDER,
  getDroneDisplayIdentity,
  matchesDroneSearchQuery,
} from '../utilities/dronePresentation';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  filterClustersByScope,
} from '../utilities/swarmDesignUtils';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import '../styles/CommandSender.css';
import { FIELD_NAMES } from '../constants/fieldMappings';

const CommandSender = ({ drones, swarmData = null }) => {
  const [activeTab, setActiveTab] = useState('missionTrigger');
  const [targetMode, setTargetMode] = useState('all'); // 'all', 'cluster', or 'selected'
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [targetQuery, setTargetQuery] = useState('');
  const [selectedClusterScope, setSelectedClusterScope] = useState('');
  const [modalOpen, setModalOpen] = useState(false);
  const [precisionMoveDialogOpen, setPrecisionMoveDialogOpen] = useState(false);
  const [currentCommandData, setCurrentCommandData] = useState(null);
  const [confirmationMessage, setConfirmationMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [, forceClockTick] = useReducer((value) => value + 1, 0);
  const {
    primaryMonitor: commandMonitor,
    recentCommandMonitors,
    dismissCommandMonitor,
    commandLifecycleCallbacks,
  } = useCommandActivity();

  React.useEffect(() => {
    const interval = setInterval(forceClockTick, 1000);
    return () => clearInterval(interval);
  }, []);

  const browserNowMs = Date.now();
  const fleetClock = useMemo(
    () => getFleetReferenceClock(drones, browserNowMs),
    [browserNowMs, drones],
  );
  const clockOffsetLabel = formatClockOffsetLabel(fleetClock.offsetMs);
  const selectedLookup = useMemo(
    () => new Set(selectedDrones.map((value) => String(value))),
    [selectedDrones],
  );
  const visibleSelectionDrones = useMemo(
    () => drones.filter((drone) => matchesDroneSearchQuery(drone, targetQuery)),
    [drones, targetQuery],
  );
  const swarmViewModel = useMemo(
    () => (Array.isArray(swarmData) ? buildSwarmViewModel(swarmData, drones) : null),
    [drones, swarmData],
  );
  const clusterTargetOptions = useMemo(
    () => buildClusterScopeOptions(swarmViewModel?.clusters || [], drones.length)
      .filter((option) => option.id !== 'all' && option.id !== 'attention'),
    [drones.length, swarmViewModel?.clusters],
  );
  const activeClusterTarget = useMemo(
    () => clusterTargetOptions.find((option) => String(option.id) === String(selectedClusterScope)) || null,
    [clusterTargetOptions, selectedClusterScope],
  );
  const clusterTargetIds = useMemo(() => {
    if (!swarmViewModel || !selectedClusterScope) {
      return [];
    }

    return Array.from(
      new Set(
        filterClustersByScope(swarmViewModel.clusters, selectedClusterScope)
          .flatMap((cluster) => cluster.drones.map((drone) => String(drone.hw_id))),
      ),
    );
  }, [selectedClusterScope, swarmViewModel]);

  React.useEffect(() => {
    if (clusterTargetOptions.length === 0) {
      if (targetMode === 'cluster') {
        setTargetMode('all');
      }
      if (selectedClusterScope) {
        setSelectedClusterScope('');
      }
      return;
    }

    if (!clusterTargetOptions.some((option) => String(option.id) === String(selectedClusterScope))) {
      setSelectedClusterScope(String(clusterTargetOptions[0].id));
    }
  }, [clusterTargetOptions, selectedClusterScope, targetMode]);

  const scopedTargetIds = useMemo(() => {
    if (targetMode === 'selected') {
      return selectedDrones.map((value) => String(value));
    }

    if (targetMode === 'cluster') {
      return clusterTargetIds;
    }

    return [];
  }, [clusterTargetIds, selectedDrones, targetMode]);

  const targetCount = targetMode === 'selected'
    ? selectedLookup.size
    : targetMode === 'cluster'
      ? clusterTargetIds.length
      : drones.length;
  const targetLabel = targetMode === 'selected'
    ? `${selectedDrones.length} selected drone${selectedDrones.length === 1 ? '' : 's'}`
    : targetMode === 'cluster'
      ? `${activeClusterTarget?.label || 'Cluster'} · ${clusterTargetIds.length} drone${clusterTargetIds.length === 1 ? '' : 's'}`
      : `all ${drones.length} drone${drones.length === 1 ? '' : 's'}`;
  const targetDescriptor = targetMode === 'selected'
    ? `Selected drones: ${selectedDrones.join(', ')}`
    : targetMode === 'cluster'
      ? (activeClusterTarget?.description || 'Cluster scope follows the current saved Smart Swarm topology.')
      : 'Target scope: all configured drones';
  const monitorTargetDescriptor = commandMonitor?.targetDescriptor || targetDescriptor;

  const buildTargetContext = (commandData = {}) => {
    const explicitTargets = Array.isArray(commandData.target_drones) && commandData.target_drones.length > 0
      ? commandData.target_drones.map((value) => String(value))
      : null;
    const scopedTargets = targetMode === 'selected'
      ? selectedDrones.map((value) => String(value))
      : targetMode === 'cluster'
        ? clusterTargetIds
        : [];
    const effectiveTargets = explicitTargets || scopedTargets;
    const effectiveMode = explicitTargets ? 'selected' : targetMode;

    return {
      effectiveTargets,
      targetLabel: effectiveMode === 'selected'
        ? `${effectiveTargets.length} selected drone${effectiveTargets.length === 1 ? '' : 's'}`
        : effectiveMode === 'cluster'
          ? `${activeClusterTarget?.label || 'Cluster'} · ${effectiveTargets.length} drone${effectiveTargets.length === 1 ? '' : 's'}`
        : `all ${drones.length} drone${drones.length === 1 ? '' : 's'}`,
      targetDescriptor: effectiveMode === 'selected'
        ? `Selected drones: ${effectiveTargets.join(', ')}`
        : effectiveMode === 'cluster'
          ? (activeClusterTarget?.description || 'Cluster scope follows the current saved Smart Swarm topology.')
        : 'Target scope: all configured drones',
    };
  };

  const ensureTargetScopeReady = (targetContext) => {
    if (targetMode === 'selected' && targetContext.effectiveTargets.length === 0) {
      toast.error('No drones selected. Please select at least one drone.');
      return false;
    }

    if (targetMode === 'cluster' && targetContext.effectiveTargets.length === 0) {
      toast.error('No executable cluster is selected. Choose a valid cluster target first.');
      return false;
    }

    return true;
  };

  const prepareCommandForDispatch = (commandData = {}) => {
    const targetContext = buildTargetContext(commandData);
    const hasExplicitTargets = Array.isArray(commandData?.target_drones) && commandData.target_drones.length > 0;

    if (!hasExplicitTargets && !ensureTargetScopeReady(targetContext)) {
      return null;
    }

    const missionName = getCommandName(commandData.missionType);

    return {
      ...commandData,
      ...(targetContext.effectiveTargets.length > 0 ? { target_drones: targetContext.effectiveTargets } : {}),
      uiMeta: {
        ...(commandData.uiMeta || {}),
        operatorLabel: commandData?.uiMeta?.operatorLabel || missionName,
        targetLabel: targetContext.targetLabel,
        targetDescriptor: targetContext.targetDescriptor,
      },
    };
  };

  const submitPreparedCommand = async (commandData) => {
    setLoading(true);
    try {
      await submitCommandWithLifecycleFeedback(commandData, {
        ...commandLifecycleCallbacks,
      });
      return true;
    } catch (error) {
      console.error('Error sending command:', error);
      const detail = error?.response?.data?.detail || error?.message || 'Error sending command. Please check console for details.';
      toast.error(detail);
      return false;
    } finally {
      setLoading(false);
    }
  };

  const getMonitorTone = (monitor) => {
    if (!monitor) {
      return 'neutral';
    }

    if (monitor.trackingIssue === 'unavailable' || monitor.trackingIssue === 'timeout') {
      return 'warning';
    }

    switch (monitor.progress?.stage) {
      case 'completed':
        return 'success';
      case 'failed':
        return 'danger';
      case 'partial':
      case 'cancelled':
      case 'timeout':
      case 'superseded':
        return 'warning';
      case 'executing':
      case 'finishing':
        return 'active';
      case 'awaiting_ack':
      case 'scheduled':
      case 'pending_execution':
      default:
        return 'neutral';
    }
  };

  const commandMonitorMetrics = useMemo(() => {
    if (!commandMonitor) {
      return [];
    }

    const metrics = [
      {
        label: 'Accepted',
        value: `${commandMonitor.acks?.accepted ?? 0}/${commandMonitor.acks?.expected ?? 0}`,
      },
    ];

    if ((commandMonitor.progress?.ackPending ?? 0) > 0 || commandMonitor.progress?.stage === 'awaiting_ack') {
      metrics.push({
        label: 'Awaiting ACK',
        value: String(commandMonitor.progress?.ackPending ?? 0),
      });
    }

    if ((commandMonitor.acks?.offline ?? 0) > 0) {
      metrics.push({
        label: 'Offline',
        value: String(commandMonitor.acks.offline),
      });
    }

    if ((commandMonitor.acks?.rejected ?? 0) > 0) {
      metrics.push({
        label: 'Rejected',
        value: String(commandMonitor.acks.rejected),
      });
    }

    if ((commandMonitor.acks?.errors ?? 0) > 0) {
      metrics.push({
        label: 'Errors',
        value: String(commandMonitor.acks.errors),
      });
    }

    if ((commandMonitor.executions?.expected ?? 0) > 0 || commandMonitor.progress?.stage === 'executing' || commandMonitor.progress?.stage === 'finishing') {
      metrics.push(
        {
          label: 'Active',
          value: String(commandMonitor.progress?.active ?? 0),
        },
        {
          label: 'Completed',
          value: String(commandMonitor.progress?.completed ?? 0),
        },
        {
          label: 'Remaining',
          value: String(commandMonitor.progress?.remaining ?? 0),
        },
      );
    }

    return metrics;
  }, [commandMonitor]);

  const monitorScheduledTime = useMemo(() => {
    const scheduledMs = Number(commandMonitor?.progress?.scheduledTriggerTime || 0);
    if (Number.isFinite(scheduledMs) && scheduledMs > 0) {
      return formatCommandAbsoluteTime(Math.floor(scheduledMs / 1000));
    }

    if (commandMonitor?.triggerTime) {
      return formatCommandAbsoluteTime(commandMonitor.triggerTime);
    }

    return null;
  }, [commandMonitor]);

  const renderConfirmationDetails = () => {
    if (!currentCommandData) {
      return null;
    }

    const uiMeta = currentCommandData.uiMeta || {};
    const showExecution = currentCommandData?.uiMeta?.triggerSummary
      && currentCommandData.uiMeta.triggerSummary !== 'Immediate on acceptance';
    const detailRows = [
      {
        label: 'Targets',
        value: currentCommandData?.uiMeta?.targetLabel || targetLabel,
      },
      ...(showExecution
        ? [{
          label: 'Execution',
          value: uiMeta.triggerSummary || formatCommandAbsoluteTime(currentCommandData.triggerTime),
        }]
        : []),
      ...((clockOffsetLabel && showExecution)
        ? [{
          label: 'Clock note',
          value: `Scheduling uses the GCS-aligned clock. ${clockOffsetLabel}.`,
        }]
        : []),
      ...((uiMeta.details || []).map((detail) => ({
        label: detail.label,
        value: detail.value,
      }))),
    ];

    return detailRows.map((detail) => (
      <p key={`${detail.label}-${detail.value}`}>
        <strong>{detail.label}:</strong> {detail.value}
      </p>
    ));
  };

  // Handle new command from child components (MissionTrigger/DroneActions)
  const handleSendCommand = (commandData) => {
    const preparedCommand = prepareCommandForDispatch(commandData);
    if (!preparedCommand) {
      return;
    }

    const missionName = getCommandName(preparedCommand.missionType);
    setCurrentCommandData(preparedCommand);
    setConfirmationMessage(
      preparedCommand.uiMeta?.confirmationMessage
        || `${missionName} → ${preparedCommand.uiMeta?.targetLabel || targetLabel}. Confirm dispatch.`
    );
    setModalOpen(true);
  };

  const handleRequestPrecisionMove = () => {
    const targetContext = buildTargetContext({});
    if (!ensureTargetScopeReady(targetContext)) {
      return;
    }

    setPrecisionMoveDialogOpen(true);
  };

  const handleClosePrecisionMoveDialog = () => {
    if (!loading) {
      setPrecisionMoveDialogOpen(false);
    }
  };

  const handleSubmitPrecisionMove = async (commandData) => {
    const preparedCommand = prepareCommandForDispatch(commandData);
    if (!preparedCommand) {
      return false;
    }

    const didSend = await submitPreparedCommand(preparedCommand);
    if (didSend) {
      setPrecisionMoveDialogOpen(false);
    }
    return didSend;
  };

  // Confirm and send the command
  const handleConfirmSendCommand = async () => {
    if (currentCommandData) {
      const commandToSend = currentCommandData;
      setModalOpen(false);
      await submitPreparedCommand(commandToSend);
      setCurrentCommandData(null);
    }
  };

  // Cancel the command
  const handleCancelSendCommand = () => {
    setModalOpen(false);
    setCurrentCommandData(null);
  };

  const handleDismissCommandMonitor = () => {
    if (!commandMonitor?.commandId) {
      return;
    }

    dismissCommandMonitor(commandMonitor.commandId);
  };

  const handleDismissRecentMonitor = (commandId) => {
    dismissCommandMonitor(commandId);
  };

  const handlePrepareMissionCancel = () => {
    if (!commandMonitor) {
      return;
    }

    handleSendCommand({
      missionType: String(DRONE_MISSION_TYPES.NONE),
      triggerTime: '0',
      target_drones: commandMonitor.targetDrones,
      uiMeta: {
        operatorLabel: getCommandName(DRONE_MISSION_TYPES.NONE),
        confirmationMessage: `Cancel ${commandMonitor.commandLabel} for ${commandMonitor.targetLabel}?`,
        triggerSummary: 'Immediate cancel on acceptance',
        details: [
          {
            label: 'Reason',
            value: 'Stops the scheduled or active mission on the same targets immediately after drone acceptance.',
          },
          {
            label: 'Current stage',
            value: commandMonitor.progress?.label || 'Mission in progress',
          },
        ],
      },
    });
  };

  // Drone selection functions
  const toggleDroneSelection = (droneId) => {
    setSelectedDrones((prev) =>
      prev.includes(droneId)
        ? prev.filter((id) => id !== droneId)
        : [...prev, droneId]
    );
  };

  const selectVisibleDrones = () => {
    const visibleDroneIds = visibleSelectionDrones.map((drone) => drone[FIELD_NAMES.HW_ID]);
    setSelectedDrones((prev) => Array.from(new Set([...prev, ...visibleDroneIds])));
  };

  const deselectAllDrones = () => {
    setSelectedDrones([]);
  };

  return (
      <div className="command-sender-container">
        <div className="command-sender-header-row">
          <div className="command-sender-header-copy">
            <p className="command-sender-eyebrow">Mission dispatch</p>
            <h2 className="command-sender-header">Command Control</h2>
            <p className="command-sender-subheader">
              Set scope, verify readiness, dispatch.
            </p>
          </div>
        </div>

      {/* Target Selection UI */}
      <div className="target-selection">
        <div className="target-selection__row">
          <div>
            <label htmlFor="targetMode" className="target-selection__label">Command target</label>
            <p className="target-selection__hint">Whole fleet, one saved cluster, or a manual subset.</p>
          </div>
          <div className="target-selection__controls">
            <span className="target-selection__scope">{targetLabel}</span>
            <select
              id="targetMode"
              value={targetMode}
              onChange={(e) => setTargetMode(e.target.value)}
            >
              <option value="all">All Drones</option>
              {clusterTargetOptions.length > 0 && (
                <option value="cluster">Cluster</option>
              )}
              <option value="selected">Select Drones</option>
            </select>
          </div>
        </div>

        {targetMode === 'cluster' && (
          <div className="drone-selection drone-selection--cluster">
            <ClusterScopeBar
              label="Cluster target"
              options={clusterTargetOptions}
              selectedId={selectedClusterScope}
              onSelect={setSelectedClusterScope}
              summary="Uses the current saved Smart Swarm topology."
            />
            <div className="selected-count">
              {activeClusterTarget
                ? `${activeClusterTarget.label} · ${clusterTargetIds.length} target drone${clusterTargetIds.length === 1 ? '' : 's'}`
                : 'No executable clusters are available yet.'}
            </div>
          </div>
        )}

        {targetMode === 'selected' && (
            <div className="drone-selection">
            <div className="drone-selection__toolbar">
              <label className="drone-selection__search">
                <span>Search targets</span>
                <input
                  type="search"
                  value={targetQuery}
                  onChange={(event) => setTargetQuery(event.target.value)}
                  placeholder={DRONE_SEARCH_PLACEHOLDER}
                  aria-label="Search drone targets by position, hardware ID, or callsign"
                />
              </label>
              <div className="selection-buttons">
              <button type="button" onClick={selectVisibleDrones}>Select visible</button>
              <button type="button" onClick={deselectAllDrones}>Clear</button>
              </div>
            </div>
            <div className="drone-grid">
              {visibleSelectionDrones.map((drone) => {
                const identity = getDroneDisplayIdentity(drone);

                return (
                <button
                  type="button"
                  key={drone[FIELD_NAMES.HW_ID]}
                  className={`command-drone-target ${
                    selectedDrones.includes(drone[FIELD_NAMES.HW_ID]) ? 'selected' : ''
                  }`}
                  onClick={() => toggleDroneSelection(drone[FIELD_NAMES.HW_ID])}
                >
                  <strong>{identity.primary}</strong>
                  {identity.secondary && <small>{identity.secondary}</small>}
                </button>
              )})}
            </div>
            {visibleSelectionDrones.length === 0 && (
              <div className="drone-selection__empty">
                No drones match the current search.
              </div>
            )}
            <div className="selected-count">
              Selected: {selectedDrones.length}
              {targetQuery && ` · ${visibleSelectionDrones.length} visible match${visibleSelectionDrones.length === 1 ? '' : 'es'}`}
            </div>
            <details className="command-inline-help">
              <summary>Search help</summary>
              <p>{DRONE_SEARCH_HELP_TEXT}</p>
            </details>
          </div>
        )}
      </div>

      <CommandPreflightSummary
        drones={drones}
        targetMode={targetMode}
        targetDroneIds={scopedTargetIds}
        targetSummaryLabel={targetLabel}
        referenceNowMs={fleetClock.referenceNowMs}
        clockOffsetLabel={clockOffsetLabel}
      />

      {commandMonitor && (
        <>
        <section className={`command-monitor command-monitor--${getMonitorTone(commandMonitor)}`}>
          <div className="command-monitor__header">
            <div>
              <p className="command-monitor__eyebrow">Live Command Monitor</p>
              <h3>{commandMonitor.commandLabel}</h3>
              <p className="command-monitor__summary">{commandMonitor.progress?.message}</p>
            </div>
            <div className="command-monitor__header-meta">
              <span className={`command-monitor__badge command-monitor__badge--${getMonitorTone(commandMonitor)}`}>
                {commandMonitor.progress?.label || 'Command update'}
              </span>
              <span className="command-monitor__command-id">ID {commandMonitor.commandId}</span>
            </div>
          </div>

          <div className="command-monitor__meta">
            <span>{commandMonitor.targetLabel}</span>
            <span>{monitorTargetDescriptor}</span>
            {monitorScheduledTime && <span>Trigger: {monitorScheduledTime}</span>}
          </div>

          {commandMonitor.trackingIssue && (
            <p className="command-monitor__notice">
              Tracking updates are currently {commandMonitor.trackingIssue === 'timeout' ? 'timed out' : 'unavailable'}.
              The last known command state remains visible here.
            </p>
          )}

          <div className="command-monitor__metrics" role="list" aria-label="Command monitor metrics">
            {commandMonitorMetrics.map((metric) => (
              <div key={`${metric.label}-${metric.value}`} className="command-monitor__metric" role="listitem">
                <span className="command-monitor__metric-label">{metric.label}</span>
                <strong className="command-monitor__metric-value">{metric.value}</strong>
              </div>
            ))}
          </div>

          <div className="command-monitor__actions">
            {commandMonitor.canCancelMission && !commandMonitor.isTerminal && commandMonitor.missionType !== DRONE_MISSION_TYPES.NONE && (
              <button
                type="button"
                className="command-monitor__action command-monitor__action--danger"
                onClick={handlePrepareMissionCancel}
              >
                {commandMonitor.progress?.stage === 'scheduled' ? 'Cancel Before Trigger' : 'Cancel Mission'}
              </button>
            )}
            {(commandMonitor.isTerminal || commandMonitor.trackingIssue) && (
              <button
                type="button"
                className="command-monitor__action command-monitor__action--secondary"
                onClick={handleDismissCommandMonitor}
              >
                Dismiss
              </button>
            )}
          </div>
        </section>
        {recentCommandMonitors.length > 0 && (
          <section className="command-monitor-history" aria-label="Recent commands">
            <div className="command-monitor-history__header">
              <strong>Recent Commands</strong>
              <span>Older command snapshots remain visible here when newer commands arrive.</span>
            </div>
            <div className="command-monitor-history__list">
              {recentCommandMonitors.map((monitor) => (
                <article
                  key={monitor.commandId}
                  className={`command-monitor-history__item command-monitor-history__item--${getMonitorTone(monitor)}`}
                >
                  <div className="command-monitor-history__content">
                    <div className="command-monitor-history__topline">
                      <strong>{monitor.commandLabel}</strong>
                      <span className={`command-monitor__badge command-monitor__badge--${getMonitorTone(monitor)}`}>
                        {monitor.progress?.label || 'Command update'}
                      </span>
                    </div>
                    <p>{monitor.progress?.message}</p>
                    <div className="command-monitor-history__meta">
                      <span>{monitor.targetLabel}</span>
                      <span>ID {monitor.commandId}</span>
                    </div>
                  </div>
                  <button
                    type="button"
                    className="command-monitor__action command-monitor__action--secondary"
                    onClick={() => handleDismissRecentMonitor(monitor.commandId)}
                  >
                    Dismiss
                  </button>
                </article>
              ))}
            </div>
          </section>
        )}
        </>
      )}

      {/* Tab Navigation with Expert UI/UX Icons */}
      <div className="command-tabs">
        <button
          className={`command-tab ${activeTab === 'missionTrigger' ? 'active' : ''}`}
          onClick={() => setActiveTab('missionTrigger')}
          title="Mission Trigger - Schedule and execute complex mission operations"
        >
          <FontAwesomeIcon icon={faRocket} className="command-tab__icon" />
          <span className="command-tab__text">Mission Trigger</span>
        </button>
        <button
          className={`command-tab ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
          title="Actions - Execute immediate flight control and system commands"
        >
          <FontAwesomeIcon icon={faCog} className="command-tab__icon" />
          <span className="command-tab__text">Actions</span>
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'missionTrigger' && (
          <MissionTrigger
            missionTypes={DRONE_MISSION_TYPES}
            onSendCommand={handleSendCommand}
            referenceNowMs={fleetClock.referenceNowMs}
            clockOffsetLabel={clockOffsetLabel}
            targetMode={targetMode}
            selectedDrones={selectedDrones}
            targetDroneIds={scopedTargetIds}
            targetSummaryLabel={targetLabel}
          />
        )}
        {activeTab === 'actions' && (
          <DroneActions
            actionTypes={DRONE_ACTION_TYPES}
            onSendCommand={handleSendCommand}
            onRequestPrecisionMove={handleRequestPrecisionMove}
            targetCount={targetCount}
            referenceNowMs={fleetClock.referenceNowMs}
            clockOffsetLabel={clockOffsetLabel}
          />
        )}
      </div>

      <PrecisionMoveDialog
        isOpen={precisionMoveDialogOpen}
        targetLabel={targetLabel}
        targetDescriptor={targetDescriptor}
        targetCount={targetCount}
        submitting={loading}
        onClose={handleClosePrecisionMoveDialog}
        onSubmit={handleSubmitPrecisionMove}
      />

      {/* Confirmation Modal - Rendered via Portal for proper viewport centering */}
      {modalOpen && ReactDOM.createPortal(
        <div className="modal-overlay" onClick={handleCancelSendCommand}>
          <div className="modal-content" onClick={(event) => event.stopPropagation()}>
            <h3>Confirm Command</h3>
            <p>{confirmationMessage}</p>
            <p className="command-confirmation-target-note">
              {currentCommandData?.uiMeta?.targetDescriptor || targetDescriptor}
            </p>
            {currentCommandData && (
              <div className="command-confirmation-details">
                {renderConfirmationDetails()}
              </div>
            )}
            <div className="modal-actions">
              <button className="confirm-button" onClick={handleConfirmSendCommand}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelSendCommand}>
                No
              </button>
            </div>
          </div>
        </div>,
        document.body,
      )}

      {/* Loading Spinner */}
      {loading && (
        <div className="loading-overlay">
          <div className="loading-spinner"></div>
        </div>
      )}
    </div>
  );
};

CommandSender.propTypes = {
  drones: PropTypes.array.isRequired,
  swarmData: PropTypes.array,
};

export default CommandSender;
