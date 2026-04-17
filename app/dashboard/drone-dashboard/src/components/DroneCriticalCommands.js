import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import {
  FaBan,
  FaCrosshairs,
  FaHandPaper,
  FaHome,
  FaPlaneArrival,
  FaPlaneDeparture,
  FaSkull,
} from 'react-icons/fa';

import ConfirmationModal from './ConfirmationModal';
import InfoHint from './InfoHint';
import PrecisionMoveDialog from './PrecisionMoveDialog';
import { buildActionCommand } from '../services/droneApiService';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import '../styles/DroneCriticalCommands.css';

const PRIMARY_COMMAND_SLOT = {
  grounded: {
    actionType: DRONE_ACTION_TYPES.TAKE_OFF,
    icon: FaPlaneDeparture,
    label: 'Take Off',
    description: 'Climb using the configured takeoff altitude',
    tone: 'neutral',
    requiresArmed: false,
  },
  airborne: {
    actionType: DRONE_ACTION_TYPES.LAND,
    icon: FaPlaneArrival,
    label: 'Land',
    description: 'Land this drone immediately',
    tone: 'neutral',
    requiresArmed: true,
  },
};

const SECONDARY_COMMANDS = [
  {
    actionType: DRONE_ACTION_TYPES.HOLD,
    icon: FaHandPaper,
    label: 'Hold',
    description: 'Freeze the drone in place',
    tone: 'neutral',
    requiresArmed: true,
  },
  {
    actionType: DRONE_ACTION_TYPES.RETURN_RTL,
    icon: FaHome,
    label: 'RTL',
    description: 'Return this drone to launch',
    tone: 'warning',
    requiresArmed: true,
  },
  {
    actionType: DRONE_ACTION_TYPES.KILL_TERMINATE,
    icon: FaSkull,
    label: 'Kill',
    description: 'Emergency motor stop only',
    tone: 'danger',
    requiresArmed: true,
  },
];

function getDisabledReason(command, isArmed, runtimeStatus) {
  if (!runtimeStatus || runtimeStatus.level === 'unknown' || runtimeStatus.level === 'offline') {
    return 'Command link unavailable. Recover telemetry before sending per-drone overrides.';
  }

  if (command.requiresArmed && !isArmed) {
    return 'This action becomes available after takeoff.';
  }

  return null;
}

function getPanelNote(isArmed, runtimeStatus) {
  if (!runtimeStatus || runtimeStatus.level === 'unknown' || runtimeStatus.level === 'offline') {
    return 'Recover telemetry to enable per-drone overrides.';
  }

  if (!isArmed) {
    return 'Take Off uses the configured altitude. Hold, RTL, and Kill activate after launch.';
  }

  if (runtimeStatus.level === 'degraded') {
    return 'Link is delayed. Use overrides only if you still have command authority.';
  }

  return 'Use for isolated intervention on this one drone.';
}

const DroneCriticalCommands = ({
  droneId,
  isArmed = false,
  runtimeStatus = null,
  targetLabel = '',
  targetDescriptor = '',
  canCancelMission = false,
  currentMissionLabel = '',
}) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const [precisionMoveDialogOpen, setPrecisionMoveDialogOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { commandLifecycleCallbacks } = useCommandActivity();
  const resolvedTargetLabel = targetLabel || `Drone ${droneId}`;
  const resolvedTargetDescriptor = targetDescriptor || `Per-drone override: drone ${droneId}`;
  const jogDisabledReason = getDisabledReason(
    {
      actionType: DRONE_ACTION_TYPES.PRECISION_MOVE,
      label: 'Jog',
      requiresArmed: true,
    },
    isArmed,
    runtimeStatus,
  );
  const cancelDisabledReason = !runtimeStatus || runtimeStatus.level === 'unknown' || runtimeStatus.level === 'offline'
    ? 'Command link unavailable. Recover telemetry before cancelling a mission.'
    : !canCancelMission
      ? 'No active mission is available to cancel on this drone.'
      : null;

  const commands = useMemo(
    () => {
      const primaryCommand = isArmed ? PRIMARY_COMMAND_SLOT.airborne : PRIMARY_COMMAND_SLOT.grounded;
      return [primaryCommand, ...SECONDARY_COMMANDS].map((command) => ({
        ...command,
        disabledReason: getDisabledReason(command, isArmed, runtimeStatus),
      }));
    },
    [isArmed, runtimeStatus],
  );
  const panelNote = getPanelNote(isArmed, runtimeStatus);

  const handleCommandClick = (command) => {
    if (command.disabledReason) {
      toast.info(command.disabledReason);
      return;
    }

    setPendingAction(command);
    setModalOpen(true);
  };

  const handleOpenPrecisionMove = () => {
    if (jogDisabledReason) {
      toast.info(jogDisabledReason);
      return;
    }

    setPrecisionMoveDialogOpen(true);
  };

  const handleRequestMissionCancel = () => {
    if (cancelDisabledReason) {
      toast.info(cancelDisabledReason);
      return;
    }

    setPendingAction({
      actionType: DRONE_MISSION_TYPES.NONE,
      label: 'Cancel Mission',
      description: currentMissionLabel
        ? `Cancel ${currentMissionLabel} for this drone`
        : 'Cancel the active mission for this drone',
      tone: 'warning',
      kind: 'mission-cancel',
    });
    setModalOpen(true);
  };

  const handleConfirm = async () => {
    if (!pendingAction || !droneId) {
      setModalOpen(false);
      return;
    }

    setModalOpen(false);

    const commandData = pendingAction.kind === 'mission-cancel'
      ? {
        missionType: String(DRONE_MISSION_TYPES.NONE),
        triggerTime: '0',
        target_drones: [droneId],
        uiMeta: {
          operatorLabel: 'Cancel Mission',
          targetLabel: resolvedTargetLabel,
          targetDescriptor: resolvedTargetDescriptor,
        },
      }
      : buildActionCommand(
        pendingAction.actionType,
        [droneId],
        0,
      );

    commandData.uiMeta = {
      ...(commandData.uiMeta || {}),
      operatorLabel: pendingAction.label,
      targetLabel: resolvedTargetLabel,
      targetDescriptor: resolvedTargetDescriptor,
    };

    try {
      setSubmitting(true);
      await submitCommandWithLifecycleFeedback(commandData, {
        ...commandLifecycleCallbacks,
      });
    } catch (error) {
      console.error('Error sending command:', error);
      toast.error(`Failed to send "${pendingAction.label}" to ${resolvedTargetLabel}.`);
    } finally {
      setSubmitting(false);
      setPendingAction(null);
    }
  };

  const handleCancel = () => {
    setModalOpen(false);
    setPendingAction(null);
  };

  const handleSubmitPrecisionMove = async (commandData, options = {}) => {
    try {
      setSubmitting(true);
      const response = await submitCommandWithLifecycleFeedback({
        ...commandData,
        target_drones: [droneId],
        uiMeta: {
          ...(commandData.uiMeta || {}),
          targetLabel: resolvedTargetLabel,
          targetDescriptor: resolvedTargetDescriptor,
        },
      }, {
        ...commandLifecycleCallbacks,
      });
      const didSend = response?.success !== false;
      if (didSend && options.closeOnSuccess !== false) {
        setPrecisionMoveDialogOpen(false);
      }
      return didSend;
    } catch (error) {
      console.error('Failed to submit per-drone precision move', error);
      toast.error(`Failed to send Precision Move to ${resolvedTargetLabel}.`);
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  const handleSubmitPrecisionMoveHold = async (commandData, options = {}) => {
    try {
      setSubmitting(true);
      const response = await submitCommandWithLifecycleFeedback({
        ...commandData,
        target_drones: [droneId],
        uiMeta: {
          ...(commandData.uiMeta || {}),
          targetLabel: resolvedTargetLabel,
          targetDescriptor: resolvedTargetDescriptor,
        },
      }, {
        ...commandLifecycleCallbacks,
      });
      const didSend = response?.success !== false;
      if (didSend && options.closeOnSuccess !== false) {
        setPrecisionMoveDialogOpen(false);
      }
      return didSend;
    } catch (error) {
      console.error('Failed to send per-drone Hold override', error);
      toast.error(`Failed to send Hold to ${resolvedTargetLabel}.`);
      return false;
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="critical-commands-panel">
      <div className="critical-commands-panel__header">
        <div className="critical-commands-panel__title-row">
          <span className="critical-commands-panel__title">Actions</span>
          <InfoHint content={panelNote} label="Action guidance" placement="bottom" />
        </div>
        <div className="critical-commands-panel__utilities">
          <button
            type="button"
            className="critical-commands-panel__utility"
            onClick={handleOpenPrecisionMove}
            disabled={Boolean(jogDisabledReason) || submitting}
            aria-disabled={Boolean(jogDisabledReason) || submitting}
            title={jogDisabledReason || `Open jog control for ${resolvedTargetLabel}`}
          >
            <FaCrosshairs aria-hidden="true" />
            <span className="critical-commands-panel__utility-label">Jog</span>
          </button>
          <button
            type="button"
            className="critical-commands-panel__utility critical-commands-panel__utility--warning"
            onClick={handleRequestMissionCancel}
            disabled={Boolean(cancelDisabledReason) || submitting}
            aria-disabled={Boolean(cancelDisabledReason) || submitting}
            title={cancelDisabledReason || `Cancel current mission for ${resolvedTargetLabel}`}
          >
            <FaBan aria-hidden="true" />
            <span className="critical-commands-panel__utility-label">Cancel</span>
          </button>
        </div>
      </div>

      <div className="critical-commands-container">
        {commands.map((command) => {
          const Icon = command.icon;
          const disabled = Boolean(command.disabledReason);

          return (
            <button
              key={command.actionType}
              type="button"
              className={`critical-command-button ${command.tone}`}
              title={disabled ? `${command.label}: ${command.disabledReason}` : `${command.label}: ${command.description}`}
              onClick={() => handleCommandClick(command)}
              disabled={disabled || submitting}
              aria-disabled={disabled || submitting}
            >
              <span className="critical-command-button__icon">
                <Icon aria-hidden="true" />
              </span>
              <span className="critical-command-button__label">{command.label}</span>
            </button>
          );
        })}
      </div>

      <ConfirmationModal
        isOpen={modalOpen}
        title={pendingAction?.tone === 'danger' ? 'Confirm Critical Action' : 'Confirm Action'}
        message={
          pendingAction
            ? `${pendingAction.description}. Confirm ${pendingAction.label} for ${resolvedTargetLabel}?`
            : ''
        }
        confirmLabel={pendingAction?.label || 'Confirm'}
        cancelLabel="Cancel"
        isDanger={pendingAction?.tone === 'danger'}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />

      <PrecisionMoveDialog
        isOpen={precisionMoveDialogOpen}
        targetLabel={resolvedTargetLabel}
        targetDescriptor={resolvedTargetDescriptor}
        targetCount={1}
        submitting={submitting}
        scopeLocked
        onClose={() => {
          if (!submitting) {
            setPrecisionMoveDialogOpen(false);
          }
        }}
        onEditTargetScope={() => {}}
        onSubmit={handleSubmitPrecisionMove}
        onSubmitHold={handleSubmitPrecisionMoveHold}
      />
    </div>
  );
};

DroneCriticalCommands.propTypes = {
  droneId: PropTypes.string.isRequired,
  isArmed: PropTypes.bool,
  targetLabel: PropTypes.string,
  targetDescriptor: PropTypes.string,
  canCancelMission: PropTypes.bool,
  currentMissionLabel: PropTypes.string,
  runtimeStatus: PropTypes.shape({
    level: PropTypes.string,
    label: PropTypes.string,
    tooltip: PropTypes.string,
  }),
};

export default DroneCriticalCommands;
