// src/components/DroneCriticalCommands.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { toast } from 'react-toastify';
import { FaSkull, FaHome, FaPlaneArrival } from 'react-icons/fa'; 
import ConfirmationModal from './ConfirmationModal';
import { sendDroneCommand } from '../services/droneApiService'; 
import '../styles/DroneCriticalCommands.css';

/**
 * DroneCriticalCommands
 * 
 * Props:
 * - droneId (string): The unique ID of the drone (e.g. drone.hw_ID) 
 *   to which we send commands.
 */
const DroneCriticalCommands = ({ droneId }) => {
  const [modalOpen, setModalOpen] = useState(false);
  const [pendingAction, setPendingAction] = useState(null);

  /**
   * Available critical commands.
   * For clarity, we define a small array of objects describing each command:
   * actionType => matches your DRONE_ACTION_TYPES or backend missionType
   * icon => React component from react-icons
   * label => Short label for tooltips or text
   * isDanger => If true, show the modal confirm button in 'danger' style
   */
  const CRITICAL_COMMANDS = [
    {
      actionType: 'RETURN_RTL',
      icon: <FaHome />,
      label: 'Return',
      isDanger: false,
    },
    {
      actionType: 'LAND',
      icon: <FaPlaneArrival />,
      label: 'Land',
      isDanger: false,
    },
    {
      actionType: 'KILL_TERMINATE',
      icon: <FaSkull />,
      label: 'Kill',
      isDanger: true,
    },
  ];

  // User clicks an icon => show modal => store which action we want to send
  const handleCommandClick = (command) => {
    setPendingAction(command);
    setModalOpen(true);
  };

  // If user confirms => send command to only this drone
  const handleConfirm = async () => {
    if (!pendingAction || !droneId) {
      setModalOpen(false);
      return;
    }

    // Close modal so it doesn't linger
    setModalOpen(false);

    // Build the command data
    const commandData = {
      missionType: pendingAction.actionType, 
      target_drones: [droneId],
      triggerTime: '0', 
    };

    try {
      const response = await sendDroneCommand(commandData);
      if (response.status === 'success') {
        toast.success(
          `Command "${pendingAction.label}" sent to drone ${droneId} successfully!`
        );
      } else {
        toast.error(
          `Error sending command "${pendingAction.label}" to drone ${droneId}: ` +
            (response.message || 'Unknown error')
        );
      }
    } catch (error) {
      console.error('Error sending command:', error);
      toast.error(
        `Failed to send command "${pendingAction.label}" to drone ${droneId}. Check console.`
      );
    } finally {
      setPendingAction(null);
    }
  };

  // If user cancels or clicks outside => just close
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
            ? `Are you sure you want to "${pendingAction.label}" drone ${droneId}?`
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
