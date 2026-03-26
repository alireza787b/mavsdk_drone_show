// src/components/CommandSender.js

import React, { useState } from 'react';
import ReactDOM from 'react-dom';
import PropTypes from 'prop-types';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import { toast } from 'react-toastify';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faRocket, faCog } from '@fortawesome/free-solid-svg-icons';
import {
  DRONE_MISSION_TYPES,
  DRONE_ACTION_TYPES,
  getCommandName,
} from '../constants/droneConstants';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import '../styles/CommandSender.css';
import { FIELD_NAMES } from '../constants/fieldMappings';

const CommandSender = ({ drones }) => {
  const [activeTab, setActiveTab] = useState('missionTrigger');
  const [targetMode, setTargetMode] = useState('all'); // 'all' or 'selected'
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentCommandData, setCurrentCommandData] = useState(null);
  const [confirmationMessage, setConfirmationMessage] = useState('');
  const [loading, setLoading] = useState(false);

  const formatTriggerTime = (unixSeconds) => {
    if (!unixSeconds) return 'Immediate';
    const date = new Date(Number(unixSeconds) * 1000);
    if (Number.isNaN(date.getTime())) return 'Immediate';
    return date.toLocaleString();
  };

  // Handle new command from child components (MissionTrigger/DroneActions)
  const handleSendCommand = (commandData) => {
    let targetDronesList = 'All Drones';
    if (targetMode === 'selected') {
      if (selectedDrones.length === 0) {
        toast.error('No drones selected. Please select at least one drone.');
        return;
      }
      targetDronesList = selectedDrones.join(', ');
    }

    const missionName = getCommandName(commandData.missionType);
    setCurrentCommandData(commandData);
    setConfirmationMessage(
      `Command "${missionName}" will be sent to: ${targetDronesList}. Are you sure?`
    );
    setModalOpen(true);
  };

  // Confirm and send the command
  const handleConfirmSendCommand = async () => {
    if (currentCommandData) {
      setModalOpen(false);
      setLoading(true);
      try {
        const commandDataToSend = { ...currentCommandData };
        if (targetMode === 'selected') {
          commandDataToSend.target_drones = selectedDrones;
        }

        await submitCommandWithLifecycleFeedback(commandDataToSend);
      } catch (error) {
        console.error('Error sending command:', error);
        toast.error('Error sending command. Please check console for details.');
      } finally {
        setLoading(false);
        setCurrentCommandData(null);
      }
    }
  };

  // Cancel the command
  const handleCancelSendCommand = () => {
    setModalOpen(false);
    setCurrentCommandData(null);
  };

  // Drone selection functions
  const toggleDroneSelection = (droneId) => {
    setSelectedDrones((prev) =>
      prev.includes(droneId)
        ? prev.filter((id) => id !== droneId)
        : [...prev, droneId]
    );
  };

  const selectAllDrones = () => {
    const allDroneIds = drones.map((drone) => drone[FIELD_NAMES.HW_ID]);
    setSelectedDrones(allDroneIds);
  };

  const deselectAllDrones = () => {
    setSelectedDrones([]);
  };

  return (
    <div className="command-sender-container">
      <h2 className="command-sender-header">Command Control</h2>

      {/* Target Selection UI */}
      <div className="target-selection">
        <label htmlFor="targetMode" style={{ marginRight: '10px' }}>Command Target:</label>
        <select
          id="targetMode"
          value={targetMode}
          onChange={(e) => setTargetMode(e.target.value)}
        >
          <option value="all">All Drones</option>
          <option value="selected">Select Drones</option>
        </select>

        {targetMode === 'selected' && (
          <div className="drone-selection">
            <div className="selection-buttons">
              <button onClick={selectAllDrones}>Select All</button>
              <button onClick={deselectAllDrones}>Deselect All</button>
            </div>
            <div className="drone-grid">
              {drones.map((drone) => (
                <div
                  key={drone[FIELD_NAMES.HW_ID]}
                  className={`drone-item ${
                    selectedDrones.includes(drone[FIELD_NAMES.HW_ID]) ? 'selected' : ''
                  }`}
                  onClick={() => toggleDroneSelection(drone[FIELD_NAMES.HW_ID])}
                >
                  {drone[FIELD_NAMES.HW_ID]}
                </div>
              ))}
            </div>
            <div className="selected-count">
              Selected Drones: {selectedDrones.length}
            </div>
          </div>
        )}
      </div>

      {/* Tab Navigation with Expert UI/UX Icons */}
      <div className="tab-bar">
        <button
          className={`tab-button ${activeTab === 'missionTrigger' ? 'active' : ''}`}
          onClick={() => setActiveTab('missionTrigger')}
          title="Mission Trigger - Schedule and execute complex mission operations"
        >
          <FontAwesomeIcon icon={faRocket} className="tab-icon" />
          <span className="tab-text">Mission Trigger</span>
        </button>
        <button
          className={`tab-button ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
          title="Actions - Execute immediate flight control and system commands"
        >
          <FontAwesomeIcon icon={faCog} className="tab-icon" />
          <span className="tab-text">Actions</span>
        </button>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'missionTrigger' && (
          <MissionTrigger
            missionTypes={DRONE_MISSION_TYPES}
            onSendCommand={handleSendCommand}
          />
        )}
        {activeTab === 'actions' && (
          <DroneActions
            actionTypes={DRONE_ACTION_TYPES}
            onSendCommand={handleSendCommand}
          />
        )}
      </div>

      {/* Confirmation Modal - Rendered via Portal for proper viewport centering */}
      {modalOpen && ReactDOM.createPortal(
        <div className="modal-overlay" onClick={handleCancelSendCommand}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm Command</h3>
            <p>{confirmationMessage}</p>
            {currentCommandData && (
              <div className="command-confirmation-details">
                <p><strong>Trigger:</strong> {formatTriggerTime(currentCommandData.triggerTime)}</p>
                {currentCommandData.missionType === String(DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV) && (
                  <>
                    <p>
                      <strong>Control Mode:</strong>{' '}
                      {currentCommandData.use_global_setpoints ? 'GLOBAL' : 'LOCAL'}
                    </p>
                    {currentCommandData.use_global_setpoints && (
                      <p>
                        <strong>Launch Correction:</strong>{' '}
                        {currentCommandData.auto_global_origin ? 'Auto Global Launch Corrector' : 'Manual launch placement'}
                      </p>
                    )}
                  </>
                )}
                {currentCommandData.missionType === String(DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW) && (
                  <p>
                    <strong>Execution Mode:</strong> LOCAL launch-frame only
                  </p>
                )}
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
        document.body
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
};

export default CommandSender;
