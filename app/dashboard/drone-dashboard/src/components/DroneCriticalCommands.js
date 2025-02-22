// src/components/DroneCriticalCommands.js
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import { FaSkull, FaHome, FaPlaneArrival, FaHandPaper } from 'react-icons/fa';
import ConfirmationModal from './ConfirmationModal';
import { buildActionCommand, sendDroneCommand } from '../services/droneApiService';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import '../styles/DroneCriticalCommands.css';

/**
 * DroneCriticalCommands
 *
 * Renders four critical commands (Hold, Land, Return, Kill) for a single drone.
 */
const DroneCriticalCommands = ({ droneId }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);

  /**
   * Limit to 4 commands for now, but easily extensible later.
   */
  const CRITICAL_COMMANDS = [
    {
      actionType: DRONE_ACTION_TYPES.HOLD, // numeric 102
      icon: <FaHandPaper style={{ color: '#4caf50' }} />, // green-ish
      label: 'Hold',
      isDanger: false,
    },
    {
      actionType: DRONE_ACTION_TYPES.LAND, // numeric 101
      icon: <FaPlaneArrival style={{ color: '#008cba' }} />, // blue-ish
      label: 'Land',
      isDanger: false,
    },
    {
      actionType: DRONE_ACTION_TYPES.RETURN_RTL, // numeric 104
      icon: <FaHome style={{ color: '#ff9800' }} />, // orange
      label: 'Return',
      isDanger: false,
    },
    {
      actionType: DRONE_ACTION_TYPES.KILL_TERMINATE, // numeric 105
      icon: <FaSkull style={{ color: '#f44336' }} />, // red
      label: 'Kill',
      isDanger: true,
    },
  ];

  // User clicks an icon => open modal
  const handleCommandClick = (command) => {
    setPendingAction(command);
    setModalOpen(true);
  };

  // Confirm => send to backend
  const handleConfirm = async () => {
    if (!pendingAction || !droneId) {
      setModalOpen(false);
      return;
    }

    // Close modal
    setModalOpen(false);

    // Build standardized command object
    const commandData = buildActionCommand(
      pendingAction.actionType,
      [droneId], // single drone
      0 // immediate
    );

    try {
      const response = await sendDroneCommand(commandData);
      if (response.status === 'success') {
        toast.success(
          `Command "${pendingAction.label}" sent to drone ${droneId} successfully!`
        );
      } else {
        toast.error(
          `Error sending command "${pendingAction.label}" to drone ${droneId}: ${
            response.message || 'Unknown error'
          }`
        );
      }
    } catch (error) {
      console.error('Error sending command:', error);
      toast.error(`Failed to send "${pendingAction.label}" to drone ${droneId}.`);
    } finally {
      setPendingAction(null);
    }
  };

  // Cancel => close modal
  const handleCancel = () => {
    setModalOpen(false);
    setPendingAction(null);
  };

  return (
    <div className="critical-commands-container">
      {CRITICAL_COMMANDS.map((cmd) => (
        <button
          key={cmd.actionType}
          className={`critical-command-button ${cmd.isDanger ? 'danger' : ''}`}
          title={cmd.label}
          onClick={() => handleCommandClick(cmd)}
        >
          {cmd.icon}
        </button>
      ))}

      <ConfirmationModal
        isOpen={modalOpen}
        title={pendingAction?.isDanger ? 'Confirm Critical Action' : 'Confirm Action'}
        message={
          pendingAction
            ? `Are you sure you want to ${pendingAction.label} drone ${droneId}?`
            : ''
        }
        confirmLabel={pendingAction?.label || 'Yes'}
        cancelLabel="Cancel"
        isDanger={pendingAction?.isDanger || false}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </div>
  );
};

DroneCriticalCommands.propTypes = {
  droneId: PropTypes.string.isRequired,
};

export default DroneCriticalCommands;
