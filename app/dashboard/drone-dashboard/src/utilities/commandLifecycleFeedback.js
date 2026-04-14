import { toast } from 'react-toastify';

import { getCommandName } from '../constants/droneConstants';
import { getCommandStatus, sendDroneCommand } from '../services/droneApiService';

const OVERRIDE_COMMANDS = new Set([101, 102, 104, 105]);
const TERMINAL_PHASE = 'terminal';
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ERRORS = 3;
const DEFAULT_TRACK_TIMEOUT_MS = 120000;
const DEFAULT_PROGRESS_LABELS = {
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

function resolveTrackTimeoutMs(response, overrideTimeoutMs) {
  const override = Number(overrideTimeoutMs);
  if (Number.isFinite(override) && override > 0) {
    return override;
  }

  const serverTimeout = Number(response?.tracking_timeout_ms);
  if (Number.isFinite(serverTimeout) && serverTimeout > 0) {
    return serverTimeout;
  }

  return DEFAULT_TRACK_TIMEOUT_MS;
}

function normalizeMissionType(missionType) {
  const numeric = Number(missionType);
  return Number.isFinite(numeric) ? numeric : missionType;
}

function formatCommandLabel(commandData, response) {
  return commandData?.uiMeta?.operatorLabel
    || response?.mission_name
    || getCommandName(normalizeMissionType(commandData?.missionType));
}

function getAcceptedCount(response) {
  const summary = response?.ack_summary || response?.results_summary || {};
  return Number(summary.accepted ?? response?.submitted_count ?? 0);
}

function getTargetCount(response) {
  const count = Array.isArray(response?.target_drones) ? response.target_drones.length : 0;
  return count;
}

function getAckSummary(response) {
  const summary = response?.ack_summary || response?.results_summary || {};
  const accepted = Number(summary.accepted || 0);
  const offline = Number(summary.offline || 0);
  const rejected = Number(summary.rejected || 0);
  const errors = Number(summary.errors || 0);
  const expected = getTargetCount(response);

  return {
    expected,
    received: accepted + offline + rejected + errors,
    accepted,
    offline,
    rejected,
    errors,
  };
}

function isFutureTrigger(triggerTime, referenceNowMs = Date.now()) {
  const trigger = Number(triggerTime);
  const nowSeconds = Math.floor(Number(referenceNowMs || Date.now()) / 1000);
  return Number.isFinite(trigger) && trigger > nowSeconds;
}

function formatTriggerTime(triggerTime) {
  const numeric = Number(triggerTime);
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return null;
  }

  return new Date(numeric * 1000).toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    timeZone: 'UTC',
    timeZoneName: 'short',
  });
}

function normalizeTargetDrones(commandData, response, status) {
  const candidates = status?.target_drones || response?.target_drones || commandData?.target_drones || [];
  return Array.isArray(candidates) ? candidates.map((value) => String(value)) : [];
}

function buildInitialProgress(commandData, response) {
  const acks = getAckSummary(response);
  const accepted = acks.accepted;
  const expected = acks.expected;
  const referenceNowMs = Number(response?.timestamp || Date.now());

  if ((response?.tracking_phase || null) === 'awaiting_ack') {
    if (acks.received === 0) {
      return {
        stage: 'awaiting_ack',
        label: DEFAULT_PROGRESS_LABELS.awaiting_ack,
        message: `Waiting for acknowledgments from ${Math.max(expected, 1)} targeted drone(s).`,
      };
    }

    return {
      stage: 'awaiting_ack',
      label: DEFAULT_PROGRESS_LABELS.awaiting_ack,
      message: `Received ${acks.received}/${Math.max(expected, 1)} acknowledgments so far.`,
    };
  }

  if (isFutureTrigger(commandData?.triggerTime, referenceNowMs)) {
    return {
      stage: 'scheduled',
      label: DEFAULT_PROGRESS_LABELS.scheduled,
      message: `${accepted}/${Math.max(expected, 1)} targeted drone(s) accepted the command. Waiting for the scheduled trigger time.`,
      scheduled_trigger_time: Number(commandData?.triggerTime) * 1000,
    };
  }

  return {
    stage: 'pending_execution',
    label: DEFAULT_PROGRESS_LABELS.pending_execution,
    message: `${accepted}/${Math.max(expected, 1)} targeted drone(s) accepted the command. Waiting for execution start reports from ${Math.max(accepted || expected, 1)} drone(s).`,
  };
}

function buildLifecycleSnapshot({
  commandData,
  commandLabel,
  response = null,
  status = null,
  trackingIssue = null,
}) {
  const missionType = normalizeMissionType(commandData?.missionType);
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
    : getAckSummary(response);
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
  const baseProgress = status?.progress || buildInitialProgress(commandData, response);
  const progress = {
    stage: baseProgress?.stage || null,
    label: baseProgress?.label || DEFAULT_PROGRESS_LABELS[baseProgress?.stage] || 'Command update',
    message: baseProgress?.message || null,
    scheduledTriggerTime: baseProgress?.scheduled_trigger_time ?? null,
    ackPending: Number(baseProgress?.ack_pending ?? Math.max(0, acks.expected - acks.received)),
    executionPending: Number(baseProgress?.execution_pending ?? Math.max(0, acks.accepted - executions.succeeded - executions.active)),
    active: Number(baseProgress?.active ?? executions.active ?? 0),
    completed: Number(baseProgress?.completed ?? executions.succeeded ?? 0),
    remaining: Number(baseProgress?.remaining ?? executions.remaining ?? Math.max(0, acks.accepted - executions.succeeded)),
  };
  const phase = status?.phase || response?.tracking_phase || null;
  const outcome = status?.outcome || null;
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
    trackingIssue,
    progress,
    acks,
    executions,
    triggerTime: Number(commandData?.triggerTime || 0),
    canCancelMission: missionType > 0 && missionType < 100,
    updatedAtMs,
  };
}

function extractTriggerTime(commandData = {}, status = null) {
  const directValue = commandData?.triggerTime;
  if (directValue !== undefined && directValue !== null && directValue !== '') {
    return directValue;
  }

  const params = status?.params || {};
  return params.triggerTime ?? params.trigger_time ?? 0;
}

export function buildLifecycleSnapshotFromStatus(status) {
  if (!status) {
    return null;
  }

  const missionType = normalizeMissionType(status?.mission_type);
  const targetDrones = Array.isArray(status?.target_drones)
    ? status.target_drones.map((value) => String(value))
    : [];
  const commandLabel = status?.mission_name || getCommandName(missionType);

  return buildLifecycleSnapshot({
    commandData: {
      missionType,
      triggerTime: extractTriggerTime({}, status),
      target_drones: targetDrones,
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
  const acks = getAckSummary(response);
  const accepted = acks.accepted;
  const summary = response?.ack_summary || response?.results_summary || {};
  const offline = Number(summary.offline || 0);
  const rejected = Number(summary.rejected || 0);
  const errors = Number(summary.errors || 0);
  const targetCount = acks.expected || getTargetCount(response);
  const pendingAcknowledgments = targetCount > 0 && acks.received < targetCount;
  const targetSummary = targetCount > 0
    ? `${accepted}/${targetCount} targeted drone${targetCount === 1 ? '' : 's'} accepted`
    : `${accepted} drone${accepted === 1 ? '' : 's'} accepted`;
  const pendingAckSummary = targetCount > 0
    ? `${accepted}/${targetCount} acknowledgments received so far`
    : `${acks.received} acknowledgments received so far`;
  const scheduledTime = commandData?.uiMeta?.triggerSummary
    || (isFutureTrigger(commandData?.triggerTime)
      ? formatTriggerTime(commandData?.triggerTime)
      : null);

  if (!response?.success) {
    return {
      level: 'error',
      message: response?.message || `${commandLabel} was not accepted.`,
    };
  }

  if (scheduledTime) {
    return {
      level: offline > 0 || rejected > 0 || errors > 0 ? 'warning' : 'info',
      message: pendingAcknowledgments
        ? `${commandLabel} scheduled. ${scheduledTime}. ${pendingAckSummary}. Monitoring remaining acknowledgments.`
        : `${commandLabel} scheduled. ${scheduledTime}. ${targetSummary}.`,
    };
  }

  if (offline > 0 && rejected === 0 && errors === 0) {
    return {
      level: 'warning',
      message: `${commandLabel} accepted. ${targetSummary}. ${offline} offline.`,
    };
  }

  if (rejected > 0 || errors > 0) {
    return {
      level: 'warning',
      message: `${commandLabel} accepted. ${targetSummary}. ${rejected} rejected, ${errors} errors.`,
    };
  }

  if (pendingAcknowledgments) {
    return {
      level: 'info',
      message: `${commandLabel} submitted. ${pendingAckSummary}. Monitoring remaining acknowledgments and outcome in background.`,
    };
  }

  if (OVERRIDE_COMMANDS.has(normalizeMissionType(commandData?.missionType))) {
    return {
      level: 'info',
      message: `${commandLabel} accepted. ${targetSummary}. Monitoring outcome in background.`,
    };
  }

  return {
    level: 'success',
    message: `${commandLabel} accepted. ${targetSummary}. Monitoring outcome in background.`,
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
        message: status?.error_summary || `${commandLabel} was accepted, but final outcome is currently unknown.`,
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

function stripUiMeta(commandData = {}) {
  const { uiMeta, ...apiPayload } = commandData;
  return apiPayload;
}

function emitToast(level, message) {
  const normalizedLevel = level === 'warning' ? 'warn' : level;
  const method = toast[normalizedLevel] || toast.info;
  method(message);
}

async function trackCommandLifecycle(commandId, commandLabel, initialPhase, timeoutMs, callbacks = {}, context = {}) {
  let lastPhase = initialPhase || null;
  let lastProgressStage = null;
  let pollErrors = 0;
  const deadline = Date.now() + timeoutMs;
  let lastSnapshot = null;

  while (Date.now() < deadline) {
    try {
      const status = await getCommandStatus(commandId);
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
          `${commandLabel} was accepted, but command tracking updates are currently unavailable.`
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
    `${commandLabel} was accepted, but final status is still unknown after the tracking timeout.`
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
  return null;
}

export async function submitCommandWithLifecycleFeedback(commandData, options = {}) {
  const response = await sendDroneCommand(stripUiMeta(commandData));
  const commandLabel = formatCommandLabel(commandData, response);
  const submissionToast = buildSubmissionToastMessage(commandData, response);
  emitToast(submissionToast.level, submissionToast.message);

  if (response?.success && response?.command_id && getAcceptedCount(response) > 0) {
    const initialSnapshot = buildLifecycleSnapshot({
      commandData,
      commandLabel,
      response,
    });
    options.onCommandAccepted?.(initialSnapshot, response);
  }

  if (response?.success && response?.command_id && getAcceptedCount(response) > 0) {
    void trackCommandLifecycle(
      response.command_id,
      commandLabel,
      response.tracking_phase,
      resolveTrackTimeoutMs(response, options.trackTimeoutMs),
      {
        onStatusUpdate: options.onStatusUpdate,
        onTrackingComplete: options.onTrackingComplete,
        onTrackingUnavailable: options.onTrackingUnavailable,
      },
      {
        commandData,
        response,
      },
    );
  }

  return response;
}
