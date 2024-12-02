// src/components/CommandSender.js

import React, { useState } from 'react';
import PropTypes from 'prop-types';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import { sendDroneCommand } from '../services/droneApiService';
import { toast } from 'react-toastify'; // Only import 'toast' here
import {
  DRONE_MISSION_TYPES,
  DRONE_ACTION_TYPES,
  getCommandName,
} from '../constants/droneConstants';
import '../styles/CommandSender.css';

const CommandSender = ({ drones }) => {
  const [activeTab, setActiveTab] = useState('missionTrigger');
  const [targetMode, setTargetMode] = useState('all'); // 'all' or 'selected'
  const [selectedDrones, setSelectedDrones] = useState([]);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentCommandData, setCurrentCommandData] = useState(null);
  const [confirmationMessage, setConfirmationMessage] = useState('');
  const [loading, setLoading] = useState(false);

  // Function to handle sending commands from child components
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

  // Function to confirm and send the command
  const handleConfirmSendCommand = async () => {
    if (currentCommandData) {
      setModalOpen(false); // Close the modal immediately
      setLoading(true); // Show loading indicator
      try {
        let commandDataToSend = { ...currentCommandData };
        if (targetMode === 'selected') {
          commandDataToSend.target_drones = selectedDrones;
        }
        const response = await sendDroneCommand(commandDataToSend);

        if (response.status === 'success') {
          toast.success('Command sent successfully!');
        } else {
          toast.error(`Error sending command: ${response.message}`);
        }
      } catch (error) {
        console.error('Error sending command:', error);
        toast.error('Error sending command. Please check the console for more details.');
      } finally {
        setLoading(false); // Hide loading indicator
        setCurrentCommandData(null);
      }
    }
  };

  // Function to cancel command sending
  const handleCancelSendCommand = () => {
    setModalOpen(false);
    setCurrentCommandData(null);
  };

  // Functions for drone selection
  const toggleDroneSelection = (droneId) => {
    if (selectedDrones.includes(droneId)) {
      setSelectedDrones(selectedDrones.filter((id) => id !== droneId));
    } else {
      setSelectedDrones([...selectedDrones, droneId]);
    }
  };

  const selectAllDrones = () => {
    const allDroneIds = drones.map((drone) => drone.hw_ID);
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
        <label htmlFor="targetMode">Command Target:</label>
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
                  key={drone.hw_ID}
                  className={`drone-item ${
                    selectedDrones.includes(drone.hw_ID) ? 'selected' : ''
                  }`}
                  onClick={() => toggleDroneSelection(drone.hw_ID)}
                >
                  {drone.hw_ID}
                </div>
              ))}
            </div>
            <div className="selected-count">Selected Drones: {selectedDrones.length}</div>
          </div>
        )}
      </div>

      {/* Tab Navigation */}
      <div className="tab-bar">
        <button
          className={`tab-button ${activeTab === 'missionTrigger' ? 'active' : ''}`}
          onClick={() => setActiveTab('missionTrigger')}
        >
          Mission Trigger
        </button>
        <button
          className={`tab-button ${activeTab === 'actions' ? 'active' : ''}`}
          onClick={() => setActiveTab('actions')}
        >
          Actions
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

      {/* Confirmation Modal */}
      {modalOpen && (
        <div className="modal-overlay" onClick={handleCancelSendCommand}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <h3>Confirm Command</h3>
            <p>{confirmationMessage}</p>
            <div className="modal-actions">
              <button className="confirm-button" onClick={handleConfirmSendCommand}>
                Yes
              </button>
              <button className="cancel-button" onClick={handleCancelSendCommand}>
                No
              </button>
            </div>
          </div>
        </div>
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
