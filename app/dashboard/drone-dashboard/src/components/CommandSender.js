//app/dashboard/drone-dashboard/src/components/CommandSender.js
// src/components/CommandSender.js
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import { sendDroneCommand } from '../services/droneApiService';
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

  const handleSendCommand = (commandData) => {
    let targetDronesList = 'All Drones';
    if (targetMode === 'selected') {
      if (selectedDrones.length === 0) {
        alert('No drones selected. Please select at least one drone.');
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


  const handleConfirmSendCommand = async () => {
    if (currentCommandData) {
      try {
        let commandDataToSend = { ...currentCommandData };
        if (targetMode === 'selected') {
          commandDataToSend.target_drones = selectedDrones;
        }
        const response = await sendDroneCommand(commandDataToSend);
        if (response.status === 'success') {
          alert('Command sent successfully!');
        } else {
          alert(`Error sending command: ${response.message}`);
        }
      } catch (error) {
        console.error('Error sending command:', error);
        alert('Error sending command. Please check the console for more details.');
      } finally {
        setModalOpen(false);
        setCurrentCommandData(null);
      }
    }
  };

  const handleCancelSendCommand = () => {
    setModalOpen(false);
    setCurrentCommandData(null);
  };

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
        <label>Command Target:</label>
        <select value={targetMode} onChange={(e) => setTargetMode(e.target.value)}>
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
      <div className="tab-content">
        {activeTab === 'missionTrigger' && (
          <MissionTrigger missionTypes={DRONE_MISSION_TYPES} onSendCommand={handleSendCommand} />
        )}
        {activeTab === 'actions' && (
          <DroneActions actionTypes={DRONE_ACTION_TYPES} onSendCommand={handleSendCommand} />
        )}
      </div>

      {/* Confirmation Modal */}
      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
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
    </div>
  );
};

CommandSender.propTypes = {
  drones: PropTypes.array.isRequired,
};

export default CommandSender;
