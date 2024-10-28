// src/components/CommandSender.js
import React, { useState } from 'react';
import MissionTrigger from './MissionTrigger';
import DroneActions from './DroneActions';
import { sendDroneCommand } from '../services/droneApiService';
import { DRONE_MISSION_TYPES, DRONE_ACTION_TYPES } from '../constants/droneConstants';
import '../styles/CommandSender.css';

const CommandSender = () => {
  const [activeTab, setActiveTab] = useState('missionTrigger');

  const handleSendCommand = async (commandData) => {
    try {
      const response = await sendDroneCommand(commandData);
      if (response.status === 'success') {
        alert('Command sent successfully!');
      } else {
        alert(`Error sending command: ${response.message}`);
      }
    } catch (error) {
      console.error('Error sending command:', error);
      alert('Error sending command. Please check the console for more details.');
    }
  };

  return (
    <div className="command-sender-container">
      <h2 className="command-sender-header">Command Control</h2>
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
    </div>
  );
};

export default CommandSender;
