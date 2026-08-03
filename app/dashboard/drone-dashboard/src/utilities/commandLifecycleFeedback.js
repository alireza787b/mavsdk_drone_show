import { toast } from 'react-toastify';

import { getCommandName } from '../constants/droneConstants';
import { COMMAND_METADATA_BY_KEY, getCommandMetadata } from '../constants/missionCatalog';
import { getCommandStatus, sendDroneCommand } from '../services/droneApiService';
import { getFriendlyMissionName } from './missionUtils';

const PERSISTENT_MISSION_TYPES = new Set([
  COMMAND_METADATA_BY_KEY.SMART_SWARM.value,
]);
const TERMINAL_PHASE = 'terminal';
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ERRORS = 3;
const DEFAULT_TRACK_TIMEOUT_MS = 120000;
const DEFAULT_LATE_RECONCILIATION_WINDOW_MS = 30000;
const DEFAULT_LATE_RECONCILIATION_POLL_INTERVAL_MS = 3000;
const DEFAULT_PROGRESS_LABELS = {
  preparing: 'Checking launch readiness',
  awaiting_ack: 'Collecting acknowledgments',
  scheduled: 'Scheduled, waiting for trigger time',
  pending_execution: 'Accepted, waiting for execution start',
  executing: 'Execution in progress',
  finishing: 'Finishing on remaining drones',
  completed: 'Completed',
  partial: 'Completed with partial coverage',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timeout: 'Tracking timed out',
  superseded: 'Superseded',
};

function resolveFirstStatusWaitMs(overrideTimeoutMs) {
  const override = Number(overrideTimeoutMs);
  if (Number.isFinite(override) && override > 0) {
    return override;
  }
  return DEFAULT_TRACK_TIMEOUT_MS;
}

function resolveLocalTrackerDeadline(status, currentDeadlineMs) {
  const timeoutAt = Number(status?.timeout_at);
  const observedAt = Number(status?.observed_at);
  if (
    Number.isFinite(timeoutAt)
    && Number.isFinite(observedAt)
    && timeoutAt > observedAt
  ) {
    return Date.now() + (timeoutAt - observedAt);
  }
  return currentDeadlineMs;
}

function resolvePositiveDuration(value, fallback) {
  const numeric = Number(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : fallback;
}

function normalizeMissionType(missionType) {
  const numeric = Number(missionType);
  return Number.isFinite(numeric) ? numeric : missionType;
}

function titleCaseSegment(segment) {
  if (!segment) {
    return '';
  }

  if (segment.toUpperCase() === segment && segment.length <= 4) {
    return segment;
  }

  return segment.charAt(0).toUpperCase() + segment.slice(1).toLowerCase();
}

function humanizeCommandToken(value) {
  if (value === undefined || value === null || value === '') {
    return '';
  }

  const friendly = getFriendlyMissionName(value);
  if (friendly && friendly !== value) {
    return friendly;
  }

  return String(value)
    .trim()
    .replace(/[_-]+/g, ' ')
    .split(/\s+/)
    .map((segment) => titleCaseSegment(segment))
    .join(' ');
}

function formatCommandLabel(commandData, response) {
  return commandData?.uiMeta?.operatorLabel
    || humanizeCommandToken(response?.mission_name)
    || humanizeCommandToken(getCommandName(normalizeMissionType(commandData?.mission_type)));
}

function isPersistentMission(commandData = {}, response = null, status = null) {
  const missionType = normalizeMissionType(
    status?.mission_type ?? response?.mission_type ?? commandData?.mission_type
  );
  return PERSISTENT_MISSION_TYPES.has(Number(missionType));
}

function buildUnclassifiedAckSummary(response) {
  const expected = Array.isArray(response?.target_drones) ? response.target_drones.length : 0;
  return {
    expected,
    received: 0,
    accepted: 0,
    offline: 0,
    rejected: 0,
    errors: 0,
  };
}

function normalizeTargetDrones(commandData, response, status) {
  const candidates = status?.target_drones || response?.target_drones || commandData?.target_drone_ids || [];
  return Array.isArray(candidates) ? candidates.map((value) => String(value)) : [];
}

function countDetails(details) {
  return details && typeof details === 'object' ? Object.keys(details).length : 0;
}

function formatCount(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function buildLateEvidence(status, originalOutcome) {
  const reports = status?.late_reports || {};
  const ackReports = reports?.acks || {};
  const startReports = reports?.execution_starts || {};
  const executionReports = reports?.executions || {};
  const acknowledgments = Number(ackReports.received ?? countDetails(ackReports.details));
  const executionStarts = Number(startReports.received ?? countDetails(startReports.details));
  const executions = Number(executionReports.received ?? countDetails(executionReports.details));
  const succeeded = Number(executionReports.succeeded || 0);
  const failed = Number(executionReports.failed || 0);

  if (acknowledgments <= 0 && executionStarts <= 0 && executions <= 0) {
    return null;
  }

  let result = 'acknowledgment';
  let label = 'Late delivery evidence';
  let message = `${formatCount(acknowledgments, 'late acknowledgment report')} arrived after tracking closed. `
    + `Delivery and execution outcome remain unconfirmed; the original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
  let toastLevel = 'warning';

  if (executions > 0) {
    if (failed > 0 && succeeded > 0) {
      result = 'mixed';
      label = 'Late evidence: mixed results';
      message = `${formatCount(executions, 'late execution report')} arrived: ${succeeded} succeeded and ${failed} failed. `
        + `The original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
      toastLevel = 'warning';
    } else if (failed > 0) {
      result = 'failed';
      label = 'Late evidence: execution failed';
      message = `${formatCount(failed, 'drone')} reported execution failure after tracking closed. `
        + `The original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
      toastLevel = 'error';
    } else if (succeeded > 0) {
      result = 'succeeded';
      label = 'Late evidence: execution succeeded';
      message = `${formatCount(succeeded, 'drone')} reported successful execution after tracking closed. `
        + `The original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
      // Keep a successful late report informational because it does not rewrite
      // the original terminal timeout into a successful tracker outcome.
      toastLevel = 'info';
    } else {
      result = 'execution_report';
      label = 'Late execution evidence';
      message = `${formatCount(executions, 'late execution report')} arrived after tracking closed. `
        + `The original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
    }
  } else if (executionStarts > 0) {
    result = 'started';
    label = 'Late evidence: execution started';
    message = `${formatCount(executionStarts, 'drone')} reported execution start after tracking closed, but no terminal execution result is available. `
      + `The original tracker outcome remains ${originalOutcome || 'unchanged'}.`;
  }

  return {
    hasEvidence: true,
    result,
    label,
    message,
    toastLevel,
    originalOutcome: originalOutcome || null,
    acknowledgments,
    executionStarts,
    executions,
    succeeded,
    failed,
  };
}

function lateEvidenceFingerprint(lateEvidence) {
  if (!lateEvidence) {
    return '';
  }

  return [
    lateEvidence.acknowledgments,
    lateEvidence.executionStarts,
    lateEvidence.executions,
    lateEvidence.succeeded,
    lateEvidence.failed,
  ].join(':');
}

function hasDeliveryUnknown(status) {
  return Object.values(status?.acks?.details || {}).some(
    (ack) => ack?.delivery_state === 'delivery_unknown'
  );
}

function shouldReconcileTerminalStatus(status) {
  if (status?.phase !== TERMINAL_PHASE) {
    return false;
  }

  const outcome = status?.outcome || status?.status;
  if (outcome === 'timeout') {
    return true;
  }

  // A normal completed/partial result has already resolved transport
  // uncertainty. Only retain the bounded window for an unresolved terminal
  // failure that still carries an explicit delivery-unknown classification.
  return outcome === 'failed' && hasDeliveryUnknown(status);
}

function buildInitialProgress(commandData, response) {
  return {
    stage: 'preparing',
    label: 'Accepted for tracking',
    message: response?.message || 'The GCS created command tracking. Checking preparation and dispatch state now.',
  };
}

function buildLifecycleSnapshot({
  commandData,
  commandLabel,
  response = null,
  status = null,
  trackingIssue = null,
}) {
  const missionType = normalizeMissionType(commandData?.mission_type);
  const targetDrones = normalizeTargetDrones(commandData, response, status);
  const acks = status?.acks
    ? {
      expected: Number(status.acks.expected || 0),
      received: Number(status.acks.received || 0),
      accepted: Number(status.acks.accepted || 0),
      offline: Number(status.acks.offline || 0),
      rejected: Number(status.acks.rejected || 0),
      errors: Number(status.acks.errors || 0),
    }
    : buildUnclassifiedAckSummary(response);
  const executions = status?.executions
    ? {
      expected: Number(status.executions.expected || 0),
      succeeded: Number(status.executions.succeeded || 0),
      failed: Number(status.executions.failed || 0),
      active: Number(status.executions.active || 0),
      remaining: Number(status.executions.remaining || 0),
    }
    : {
      expected: acks.accepted,
      succeeded: 0,
      failed: 0,
      active: 0,
      remaining: acks.accepted,
  };
  const phase = status?.phase || null;
  const outcome = status?.outcome || null;
  const lateEvidence = buildLateEvidence(status, outcome || status?.status || null);
  const deliveryUnconfirmed = phase !== TERMINAL_PHASE
    && acks.accepted === 0
    && hasDeliveryUnknown(status);
  const baseProgress = status?.progress || buildInitialProgress(commandData, response);
  const progress = {
    stage: baseProgress?.stage || null,
    label: lateEvidence?.label
      || (deliveryUnconfirmed ? 'Delivery unconfirmed' : null)
      || baseProgress?.label
      || DEFAULT_PROGRESS_LABELS[baseProgress?.stage]
      || 'Command update',
    message: lateEvidence?.message
      || (deliveryUnconfirmed
        ? 'Command delivery is unconfirmed. Monitoring the existing command ID for execution evidence; do not submit a replacement command.'
        : null)
      || baseProgress?.message
      || null,
    scheduledTriggerTime: baseProgress?.scheduled_trigger_time ?? null,
    ackPending: Number(baseProgress?.ack_pending ?? Math.max(0, acks.expected - acks.received)),
    executionPending: Number(baseProgress?.execution_pending ?? Math.max(0, acks.accepted - executions.succeeded - executions.active)),
    active: Number(baseProgress?.active ?? executions.active ?? 0),
    completed: Number(baseProgress?.completed ?? executions.succeeded ?? 0),
    remaining: Number(baseProgress?.remaining ?? executions.remaining ?? Math.max(0, acks.accepted - executions.succeeded)),
  };
  const isTerminal = phase === TERMINAL_PHASE;
  const updatedAtMs = Number(
    status?.updated_at
      || status?.completed_at
      || status?.execution_started_at
      || status?.submitted_at
      || response?.timestamp
      || Date.now()
  );

  return {
    commandId: response?.command_id || status?.command_id || null,
    commandLabel,
    missionType,
    missionName: response?.mission_name || status?.mission_name || commandLabel,
    targetDrones,
    targetLabel: commandData?.uiMeta?.targetLabel || (targetDrones.length > 0
      ? `${targetDrones.length} selected drone${targetDrones.length === 1 ? '' : 's'}`
      : 'All configured drones'),
    targetDescriptor: commandData?.uiMeta?.targetDescriptor || (targetDrones.length > 0
      ? `Selected drones: ${targetDrones.join(', ')}`
      : 'Target scope: all configured drones'),
    phase,
    outcome,
    isTerminal,
    isPersistentMode: isPersistentMission(commandData, response, status),
    trackingIssue,
    lateEvidence,
    progress,
    acks,
    executions,
    triggerTime: Number(commandData?.trigger_time || 0),
    canCancelMission: missionType !== COMMAND_METADATA_BY_KEY.NONE.value
      && getCommandMetadata(missionType)?.kind === 'mission',
    updatedAtMs,
  };
}

function extractTriggerTime(commandData = {}, status = null) {
  const directValue = commandData?.trigger_time;
  if (directValue !== undefined && directValue !== null && directValue !== '') {
    return directValue;
  }

  const params = status?.params || {};
  return params.trigger_time ?? 0;
}

export function buildLifecycleSnapshotFromStatus(status) {
  if (!status) {
    return null;
  }

  const missionType = normalizeMissionType(status?.mission_type);
  const targetDrones = Array.isArray(status?.target_drones)
    ? status.target_drones.map((value) => String(value))
    : [];
  const commandLabel = humanizeCommandToken(status?.mission_name)
    || humanizeCommandToken(getCommandName(missionType));

  return buildLifecycleSnapshot({
    commandData: {
      mission_type: missionType,
      trigger_time: extractTriggerTime({}, status),
      target_drone_ids: targetDrones,
      uiMeta: {
        operatorLabel: commandLabel,
      },
    },
    commandLabel,
    status,
  });
}

function buildSubmissionToastMessage(commandData, response) {
  const commandLabel = formatCommandLabel(commandData, response);
  const targetCount = Array.isArray(response?.target_drones) ? response.target_drones.length : 0;
  const targetSummary = targetCount > 0
    ? ` for ${targetCount} target drone${targetCount === 1 ? '' : 's'}`
    : '';

  return {
    level: 'info',
    message: `${commandLabel} accepted for tracking${targetSummary}. Monitoring preparation, dispatch, and execution now.`,
  };
}

function buildTerminalSuffix(status) {
  const executions = status?.executions || {};
  const failed = Number(executions.failed || 0);
  const expected = Number(status?.acks?.expected || executions.expected || 0);
  const succeeded = Number(executions.succeeded || 0);
  const offline = Number(status?.acks?.offline || 0);
  const rejected = Number(status?.acks?.rejected || 0);
  const errors = Number(status?.acks?.errors || 0);
  const parts = [];

  if (expected > 0) {
    parts.push(`${succeeded}/${expected} succeeded`);
  }
  if (offline > 0) {
    parts.push(`${offline} offline`);
  }
  if (rejected > 0) {
    parts.push(`${rejected} rejected`);
  }
  if (errors > 0) {
    parts.push(`${errors} errors`);
  }
  if (failed > 0) {
    parts.push(`${failed} failed`);
  }

  return parts.length > 0 ? ` (${parts.join(', ')})` : '';
}

function buildTerminalToast(status, commandLabel) {
  const summarySuffix = buildTerminalSuffix(status);

  switch (status?.outcome || status?.status) {
    case 'completed':
      return {
        level: 'success',
        message: `${commandLabel} completed successfully${summarySuffix}.`,
      };
    case 'partial':
      return {
        level: 'warning',
        message: `${commandLabel} completed with partial coverage${summarySuffix}.`,
      };
    case 'superseded':
      return {
        level: 'warning',
        message: `${commandLabel} was superseded by a newer command${summarySuffix}.`,
      };
    case 'cancelled':
      return {
        level: 'warning',
        message: `${commandLabel} was cancelled${summarySuffix}.`,
      };
    case 'timeout':
      return {
        level: 'warning',
        message: status?.error_summary || `${commandLabel} tracking timed out; command delivery and final execution outcome are not confirmed.`,
      };
    case 'failed':
    default:
      return {
        level: 'error',
        message: status?.error_summary || `${commandLabel} failed${summarySuffix}.`,
      };
  }
}

function buildProgressToast(status, commandLabel) {
  const progress = status?.progress;
  if (!progress?.stage) {
    return null;
  }

  switch (progress.stage) {
    case 'executing':
      return {
        level: 'info',
        message: `${commandLabel} started. ${progress.message || 'Execution is active.'}`,
      };
    case 'finishing':
      return {
        level: 'info',
        message: `${commandLabel} is still completing. ${progress.message || 'Waiting for remaining drones to finish.'}`,
      };
    default:
      return null;
  }
}

function buildTrackingUncertainMessage(commandLabel, snapshot, reason) {
  const stage = snapshot?.progress?.stage || null;
  const accepted = Number(snapshot?.acks?.accepted || 0);
  const suffix = reason === 'timeout'
    ? 'Tracking did not close before the timeout.'
    : 'Live tracking updates are currently unavailable.';

  if (stage === 'preparing') {
    return `${commandLabel}: ${suffix} Launch readiness, command delivery, and execution are not confirmed. The last known state remains visible.`;
  }

  if (accepted > 0 || ['scheduled', 'pending_execution', 'executing', 'finishing'].includes(stage)) {
    return `${commandLabel}: ${suffix} The final execution outcome is not confirmed. The last known state remains visible.`;
  }

  return `${commandLabel}: ${suffix} Command delivery and execution are not confirmed. The last known state remains visible.`;
}

function emitToast(level, message) {
  const normalizedLevel = level === 'warning' ? 'warn' : level;
  const method = toast[normalizedLevel] || toast.info;
  method(message);
}

function emitLateEvidence(commandLabel, snapshot, status, callbacks) {
  const lateEvidence = snapshot?.lateEvidence;
  if (!lateEvidence) {
    return;
  }

  emitToast(lateEvidence.toastLevel, `${commandLabel}: ${lateEvidence.message}`);
  callbacks.onLateEvidence?.(snapshot, status);
}

async function reconcileUncertainLifecycle({
  commandId,
  commandLabel,
  callbacks,
  context,
  initialStatus = null,
  initialSnapshot = null,
  terminalReported = false,
  windowMs,
  pollIntervalMs,
}) {
  const deadline = Date.now() + windowMs;
  let lastLateFingerprint = '';
  let pollErrors = 0;
  let lifecycleReopened = false;

  if (initialSnapshot?.lateEvidence) {
    lastLateFingerprint = lateEvidenceFingerprint(initialSnapshot.lateEvidence);
    emitLateEvidence(commandLabel, initialSnapshot, initialStatus, callbacks);
  }

  while (Date.now() < deadline) {
    const remainingMs = deadline - Date.now();
    await new Promise((resolve) => setTimeout(resolve, Math.min(pollIntervalMs, remainingMs)));

    try {
      const status = await getCommandStatus(commandId);
      pollErrors = 0;
      const snapshot = buildLifecycleSnapshot({
        commandData: context.commandData,
        commandLabel,
        response: context.response,
        status,
      });

      callbacks.onStatusUpdate?.(snapshot, status);

      if (status?.phase !== TERMINAL_PHASE) {
        // This is possible for a delivery-unknown command when stronger
        // execution evidence legitimately reopens an uncertain failed state.
        lifecycleReopened = terminalReported;
      } else if (!terminalReported || lifecycleReopened) {
        // A local frontend timeout already produced an uncertainty warning. Do
        // not repeat that warning when the backend timeout becomes visible.
        // A different authoritative terminal result still deserves its normal
        // operator notification.
        if ((status?.outcome || status?.status) !== 'timeout') {
          const terminalToast = buildTerminalToast(status, commandLabel);
          emitToast(terminalToast.level, terminalToast.message);
        }
        callbacks.onTrackingComplete?.(snapshot, status);
        terminalReported = true;
        lifecycleReopened = false;
      }

      const fingerprint = lateEvidenceFingerprint(snapshot.lateEvidence);
      if (fingerprint && fingerprint !== lastLateFingerprint) {
        lastLateFingerprint = fingerprint;
        emitLateEvidence(commandLabel, snapshot, status, callbacks);
      }

      if (status?.phase === TERMINAL_PHASE && !shouldReconcileTerminalStatus(status)) {
        return status;
      }
    } catch (error) {
      pollErrors += 1;
      if (pollErrors >= MAX_POLL_ERRORS) {
        return null;
      }
    }
  }

  return null;
}

async function trackCommandLifecycle(
  commandId,
  commandLabel,
  initialPhase,
  timeoutMs,
  callbacks = {},
  context = {},
  reconciliationOptions = {},
) {
  let lastPhase = initialPhase || null;
  let lastProgressStage = null;
  let pollErrors = 0;
  let deadline = Date.now() + timeoutMs;
  let lastSnapshot = null;
  const reconciliationWindowMs = resolvePositiveDuration(
    reconciliationOptions.windowMs,
    DEFAULT_LATE_RECONCILIATION_WINDOW_MS,
  );
  const reconciliationPollIntervalMs = resolvePositiveDuration(
    reconciliationOptions.pollIntervalMs,
    DEFAULT_LATE_RECONCILIATION_POLL_INTERVAL_MS,
  );

  while (Date.now() < deadline) {
    try {
      const status = await getCommandStatus(commandId);
      deadline = resolveLocalTrackerDeadline(status, deadline);
      pollErrors = 0;
      const progressStage = status?.progress?.stage || null;
      const snapshot = buildLifecycleSnapshot({
        commandData: context.commandData,
        commandLabel,
        response: context.response,
        status,
      });
      lastSnapshot = snapshot;

      callbacks.onStatusUpdate?.(snapshot, status);

      if (progressStage && progressStage !== lastProgressStage) {
        const progressToast = buildProgressToast(status, commandLabel);
        if (progressToast) {
          emitToast(progressToast.level, progressToast.message);
        }
      }

      if (status?.phase === TERMINAL_PHASE) {
        const terminalToast = buildTerminalToast(status, commandLabel);
        emitToast(terminalToast.level, terminalToast.message);
        callbacks.onTrackingComplete?.(snapshot, status);

        if (shouldReconcileTerminalStatus(status)) {
          await reconcileUncertainLifecycle({
            commandId,
            commandLabel,
            callbacks,
            context,
            initialStatus: status,
            initialSnapshot: snapshot,
            terminalReported: true,
            windowMs: reconciliationWindowMs,
            pollIntervalMs: reconciliationPollIntervalMs,
          });
        }
        return status;
      }

      lastPhase = status?.phase || lastPhase;
      lastProgressStage = progressStage || lastProgressStage;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    } catch (error) {
      pollErrors += 1;
      if (pollErrors >= MAX_POLL_ERRORS) {
        emitToast(
          'warning',
          buildTrackingUncertainMessage(commandLabel, lastSnapshot || buildLifecycleSnapshot({
            commandData: context.commandData,
            commandLabel,
            response: context.response,
            status: null,
          }), 'unavailable')
        );
        callbacks.onTrackingUnavailable?.(
          lastSnapshot
            ? {
              ...lastSnapshot,
              trackingIssue: 'unavailable',
              updatedAtMs: Date.now(),
            }
            : buildLifecycleSnapshot({
              commandData: context.commandData,
              commandLabel,
              response: context.response,
              status: null,
              trackingIssue: 'unavailable',
            }),
          error,
        );
        return null;
      }
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    }
  }

  emitToast(
    'warning',
    buildTrackingUncertainMessage(commandLabel, lastSnapshot || buildLifecycleSnapshot({
      commandData: context.commandData,
      commandLabel,
      response: context.response,
      status: null,
    }), 'timeout')
  );
  callbacks.onTrackingUnavailable?.(
    lastSnapshot
      ? {
        ...lastSnapshot,
        trackingIssue: 'timeout',
        updatedAtMs: Date.now(),
      }
      : buildLifecycleSnapshot({
        commandData: context.commandData,
        commandLabel,
        response: context.response,
        status: null,
        trackingIssue: 'timeout',
      }),
    null,
  );

  // The frontend and backend deadlines can race, especially when a POST was
  // delivered but its response was lost. Keep a small, bounded reconciliation
  // window on the existing command ID so a backend timeout and any later
  // execution evidence can still reach the operator.
  await reconcileUncertainLifecycle({
    commandId,
    commandLabel,
    callbacks,
    context,
    initialSnapshot: lastSnapshot,
    terminalReported: false,
    windowMs: reconciliationWindowMs,
    pollIntervalMs: reconciliationPollIntervalMs,
  });
  return null;
}

export async function submitCommandWithLifecycleFeedback(commandData, options = {}) {
  const response = await sendDroneCommand(commandData);
  if (response?.accepted_for_tracking !== true || !response?.command_id) {
    throw new Error('GCS returned an invalid command-submission receipt');
  }
  const commandLabel = formatCommandLabel(commandData, response);
  const submissionToast = buildSubmissionToastMessage(commandData, response);
  emitToast(submissionToast.level, submissionToast.message);
  const persistentMission = isPersistentMission(commandData, response, null);

  const initialSnapshot = buildLifecycleSnapshot({
    commandData,
    commandLabel,
    response,
  });
  options.onSubmissionTracked?.(initialSnapshot, response);

  // Persistent modes are refreshed through the shared active-command monitor.
  // Finite commands also get immediate lifecycle polling for operator feedback.
  if (!persistentMission) {
    void trackCommandLifecycle(
      response.command_id,
      commandLabel,
      null,
      resolveFirstStatusWaitMs(options.trackTimeoutMs),
      {
        onStatusUpdate: options.onStatusUpdate,
        onTrackingComplete: options.onTrackingComplete,
        onTrackingUnavailable: options.onTrackingUnavailable,
        onLateEvidence: options.onLateEvidence,
      },
      {
        commandData,
        response,
      },
      {
        windowMs: options.lateReconciliationWindowMs,
        pollIntervalMs: options.lateReconciliationPollIntervalMs,
      },
    );
  }

  return response;
}
