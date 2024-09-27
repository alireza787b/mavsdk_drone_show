// src/components/MissionTrigger.js
import React, { useState, useEffect } from 'react';
import MissionCard from './MissionCard';
import MissionDetails from './MissionDetails';
import MissionNotification from './MissionNotification';
import { DRONE_MISSION_TYPES, defaultTriggerTimeDelay, getMissionDescription } from '../constants/droneConstants';
import { FaTimesCircle } from 'react-icons/fa';
import '../styles/MissionTrigger.css';

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);
  const [useSlider, setUseSlider] = useState(true);
  const [selectedTime, setSelectedTime] = useState('');
  const [notification, setNotification] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [currentAction, setCurrentAction] = useState(null);

  useEffect(() => {
    const now = new Date();
    now.setSeconds(now.getSeconds() + 30);
    setSelectedTime(now.toTimeString().slice(0, 8));
  }, []);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
    setTimeDelay(defaultTriggerTimeDelay);

    if (missionType === DRONE_MISSION_TYPES.NONE) {
      setCurrentAction({ actionType: missionType, confirmationMessage: 'Are you sure you want to cancel the mission immediately?' });
      setModalOpen(true);
    }
  };

  const handleConfirm = () => {
    if (currentAction) {
      const { actionType } = currentAction;
      const commandData = {
        missionType: actionType,
        triggerTime: Math.floor(Date.now() / 1000),
      };
      onSendCommand(commandData);
      setNotification('Cancel Mission command sent successfully.');
      setTimeout(() => setNotification(null), 3000);
    }
    setModalOpen(false);
    setCurrentAction(null);
  };

  const handleCancel = () => {
    setModalOpen(false);
    setCurrentAction(null);
  };

  const handleSend = () => {
    let triggerTime;

    if (useSlider) {
      triggerTime = Math.floor(Date.now() / 1000) + parseInt(timeDelay);
    } else {
      const now = new Date();
      const [hours, minutes, seconds] = selectedTime.split(':').map(Number);
      const selectedDateTime = new Date(now.getFullYear(), now.getMonth(), now.getDate(), hours, minutes, seconds);
      triggerTime = Math.floor(selectedDateTime.getTime() / 1000);

      if (selectedDateTime < now) {
        alert('The selected time has already passed. Please select a future time.');
        return;
      }
    }

    const missionName = missionTypes[selectedMission];
    const confirmationMessage = `Are you sure you want to send the "${missionName}" command to all drones?\nTrigger time: ${new Date(triggerTime * 1000).toLocaleString()}`;

    setCurrentAction({ actionType: selectedMission, confirmationMessage });
    setModalOpen(true);
  };

  const handleBack = () => {
    setSelectedMission('');
  };

  return (
    <div className="mission-trigger-container">
      {notification && <MissionNotification message={notification} />}

      {!selectedMission && (
        <div className="mission-cards">
          {Object.entries(missionTypes).map(([key, value]) => (
            <MissionCard
              key={value}
              missionType={value}
              icon={
                value === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV ? '🛸' :
                value === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW ? '🎯' :
                value === DRONE_MISSION_TYPES.SMART_SWARM ? '🐝🐝🐝' :
                '🚫'
              }
              label={key === 'NONE' ? 'Cancel Mission' : key.replace(/_/g, ' ')}
              onClick={() => handleMissionSelect(value)}
              isCancel={value === DRONE_MISSION_TYPES.NONE}
            />
          ))}
        </div>
      )}

      {selectedMission && selectedMission !== DRONE_MISSION_TYPES.NONE && (
        <MissionDetails
          missionType={selectedMission}
          icon={
            selectedMission === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV ? '🛸' :
            selectedMission === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW ? '🎯' :
            '🐝🐝🐝'
          }
          label={Object.keys(missionTypes).find((key) => missionTypes[key] === selectedMission).replace(/_/g, ' ')}
          description={getMissionDescription(selectedMission)}
          useSlider={useSlider}
          timeDelay={timeDelay}
          selectedTime={selectedTime}
          onTimeDelayChange={setTimeDelay}
          onTimePickerChange={setSelectedTime}
          onSliderToggle={setUseSlider}
          onSend={handleSend}
          onBack={handleBack}
        />
      )}

      {/* Confirmation Modal */}
      {modalOpen && (
        <div className="modal-overlay">
          <div className="modal-content">
            <h3>Confirm Action</h3>
            <p>{currentAction?.confirmationMessage}</p>
            <div className="modal-actions">
              <button className="confirm-button" onClick={handleConfirm}>Yes</button>
              <button className="cancel-button" onClick={handleCancel}>No</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default MissionTrigger;
