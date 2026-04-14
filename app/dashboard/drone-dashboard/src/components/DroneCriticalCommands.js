import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import { FaHandPaper, FaHome, FaPlaneArrival, FaPlaneDeparture, FaSkull } from 'react-icons/fa';

import ConfirmationModal from './ConfirmationModal';
import InfoHint from './InfoHint';
import { buildActionCommand } from '../services/droneApiService';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { useCommandActivity } from '../contexts/CommandActivityContext';
import '../styles/DroneCriticalCommands.css';

const AIRBORNE_COMMANDS = [
  {
    actionType: DRONE_ACTION_TYPES.HOLD,
    icon: FaHandPaper,
    label: 'Hold',
    description: 'Freeze the drone in place',
    tone: 'neutral',
    requiresArmed: true,
  },
  {
    actionType: DRONE_ACTION_TYPES.LAND,
    icon: FaPlaneArrival,
    label: 'Land',
    description: 'Land this drone immediately',
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

const GROUNDED_COMMANDS = [
  {
    actionType: DRONE_ACTION_TYPES.TAKE_OFF,
    icon: FaPlaneDeparture,
    label: 'Take Off',
    description: 'Climb using the configured takeoff altitude',
    tone: 'neutral',
    requiresArmed: false,
  },
];

function getDisabledReason(command, isArmed, runtimeStatus) {
  if (!runtimeStatus || runtimeStatus.level === 'unknown' || runtimeStatus.level === 'offline') {
    return 'Command link unavailable. Recover telemetry before sending per-drone overrides.';
  }

  if (command.requiresArmed && !isArmed) {
    return 'This override is only relevant while the drone is airborne.';
  }

  return null;
}

function getPanelNote(isArmed, runtimeStatus) {
  if (!runtimeStatus || runtimeStatus.level === 'unknown' || runtimeStatus.level === 'offline') {
    return 'Recover telemetry to enable per-drone overrides.';
  }

  if (!isArmed) {
    return 'Take Off uses the configured altitude. Airborne actions appear after launch.';
  }

  if (runtimeStatus.level === 'degraded') {
    return 'Link is delayed. Use overrides only if you still have command authority.';
  }

  return 'Use for isolated intervention on this one drone.';
}

const DroneCriticalCommands = ({ droneId, isArmed = false, runtimeStatus = null }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);
  const { commandLifecycleCallbacks } = useCommandActivity();

  const commands = useMemo(
    () => (isArmed ? AIRBORNE_COMMANDS : GROUNDED_COMMANDS).map((command) => ({
      ...command,
      disabledReason: getDisabledReason(command, isArmed, runtimeStatus),
    })),
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

  const handleConfirm = async () => {
    if (!pendingAction || !droneId) {
      setModalOpen(false);
      return;
    }

    setModalOpen(false);

    const commandData = buildActionCommand(
      pendingAction.actionType,
      [droneId],
      0,
    );
    commandData.uiMeta = {
      operatorLabel: pendingAction.label,
      targetLabel: `Drone ${droneId}`,
      targetDescriptor: `Per-drone override: drone ${droneId}`,
    };

    try {
      await submitCommandWithLifecycleFeedback(commandData, {
        ...commandLifecycleCallbacks,
      });
    } catch (error) {
      console.error('Error sending command:', error);
      toast.error(`Failed to send "${pendingAction.label}" to drone ${droneId}.`);
    } finally {
      setPendingAction(null);
    }
  };

  const handleCancel = () => {
    setModalOpen(false);
    setPendingAction(null);
  };

  return (
    <div className="critical-commands-panel">
      <div className="critical-commands-panel__header">
        <span className="critical-commands-panel__title">Actions</span>
        <InfoHint content={panelNote} label="Airborne override guidance" />
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
              disabled={disabled}
              aria-disabled={disabled}
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
            ? `${pendingAction.description}. Are you sure you want to ${pendingAction.label} drone ${droneId}?`
            : ''
        }
        confirmLabel={pendingAction?.label || 'Confirm'}
        cancelLabel="Cancel"
        isDanger={pendingAction?.tone === 'danger'}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </div>
  );
};

DroneCriticalCommands.propTypes = {
  droneId: PropTypes.string.isRequired,
  isArmed: PropTypes.bool,
  runtimeStatus: PropTypes.shape({
    level: PropTypes.string,
    label: PropTypes.string,
    tooltip: PropTypes.string,
  }),
};

export default DroneCriticalCommands;
