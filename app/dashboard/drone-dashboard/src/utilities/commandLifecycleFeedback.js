import { toast } from 'react-toastify';

import { getCommandName } from '../constants/droneConstants';
import { getCommandStatus, sendDroneCommand } from '../services/droneApiService';

const OVERRIDE_COMMANDS = new Set([101, 102, 104, 105]);
const TERMINAL_PHASE = 'terminal';
const POLL_INTERVAL_MS = 1500;
const MAX_POLL_ERRORS = 3;
const DEFAULT_TRACK_TIMEOUT_MS = 120000;

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

function isFutureTrigger(triggerTime) {
  const trigger = Number(triggerTime);
  const nowSeconds = Math.floor(Date.now() / 1000);
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

function buildSubmissionToastMessage(commandData, response) {
  const commandLabel = formatCommandLabel(commandData, response);
  const accepted = getAcceptedCount(response);
  const summary = response?.ack_summary || response?.results_summary || {};
  const offline = Number(summary.offline || 0);
  const rejected = Number(summary.rejected || 0);
  const errors = Number(summary.errors || 0);
  const targetCount = getTargetCount(response);
  const targetSummary = targetCount > 0
    ? `${accepted}/${targetCount} targeted drone${targetCount === 1 ? '' : 's'} accepted`
    : `${accepted} drone${accepted === 1 ? '' : 's'} accepted`;
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
      message: `${commandLabel} scheduled. ${scheduledTime}. ${targetSummary}.`,
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

function stripUiMeta(commandData = {}) {
  const { uiMeta, ...apiPayload } = commandData;
  return apiPayload;
}

function emitToast(level, message) {
  const normalizedLevel = level === 'warning' ? 'warn' : level;
  const method = toast[normalizedLevel] || toast.info;
  method(message);
}

async function trackCommandLifecycle(commandId, commandLabel, initialPhase, timeoutMs) {
  let lastPhase = initialPhase || null;
  let pollErrors = 0;
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const status = await getCommandStatus(commandId);
      pollErrors = 0;

      if (status?.phase === 'in_progress' && lastPhase !== 'in_progress') {
        emitToast('info', `${commandLabel} started. Monitoring completion...`);
      }

      if (status?.phase === TERMINAL_PHASE) {
        const terminalToast = buildTerminalToast(status, commandLabel);
        emitToast(terminalToast.level, terminalToast.message);
        return status;
      }

      lastPhase = status?.phase || lastPhase;
      await new Promise((resolve) => setTimeout(resolve, POLL_INTERVAL_MS));
    } catch (error) {
      pollErrors += 1;
      if (pollErrors >= MAX_POLL_ERRORS) {
        emitToast(
          'warning',
          `${commandLabel} was accepted, but command tracking updates are currently unavailable.`
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
  return null;
}

export async function submitCommandWithLifecycleFeedback(commandData, options = {}) {
  const response = await sendDroneCommand(stripUiMeta(commandData));
  const commandLabel = formatCommandLabel(commandData, response);
  const submissionToast = buildSubmissionToastMessage(commandData, response);
  emitToast(submissionToast.level, submissionToast.message);

  if (response?.success && response?.command_id && getAcceptedCount(response) > 0) {
    void trackCommandLifecycle(
      response.command_id,
      commandLabel,
      response.tracking_phase,
      options.trackTimeoutMs || DEFAULT_TRACK_TIMEOUT_MS,
    );
  }

  return response;
}
