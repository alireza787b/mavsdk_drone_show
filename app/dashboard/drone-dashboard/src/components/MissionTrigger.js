//app/dashboard/drone-dashboard/src/components/MissionTrigger.js
import React, { useState, useEffect } from 'react';
import MissionCard from './MissionCard';
import MissionDetails from './MissionDetails';
import MissionNotification from './MissionNotification';
import { DRONE_MISSION_TYPES, defaultTriggerTimeDelay, getMissionDescription } from '../constants/droneConstants';
import '../styles/MissionTrigger.css';

const MissionTrigger = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(defaultTriggerTimeDelay);
  const [useSlider, setUseSlider] = useState(true);
  const [selectedTime, setSelectedTime] = useState('');
  const [notification, setNotification] = useState(null);

  useEffect(() => {
    const now = new Date();
    now.setSeconds(now.getSeconds() + 30);
    setSelectedTime(now.toTimeString().slice(0, 8));
  }, []);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
    setTimeDelay(defaultTriggerTimeDelay);

    if (missionType === DRONE_MISSION_TYPES.NONE) {
      // Directly send the command for 'Cancel Mission'
      const commandData = {
        missionType: missionType,
        triggerTime: 0, // Immediate action
      };
      onSendCommand(commandData);
    }
  };

  const handleSend = () => {
    let triggerTime;

    if (useSlider) {
      triggerTime = Math.floor(Date.now() / 1000) + parseInt(timeDelay);
    } else {
      const now = new Date();
      const [hours, minutes, seconds] = selectedTime.split(':').map(Number);
      const selectedDateTime = new Date(
        now.getFullYear(),
        now.getMonth(),
        now.getDate(),
        hours,
        minutes,
        seconds
      );
      triggerTime = Math.floor(selectedDateTime.getTime() / 1000);

      if (selectedDateTime < now) {
        alert('The selected time has already passed. Please select a future time.');
        return;
      }
    }

    const commandData = {
      missionType: selectedMission,
      triggerTime: triggerTime,
    };
    onSendCommand(commandData);
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
                value === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV
                  ? '🛸'
                  : value === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW
                  ? '🎯'
                  : value === DRONE_MISSION_TYPES.SMART_SWARM
                  ? '🐝🐝🐝'
                  : '🚫'
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
            selectedMission === DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV
              ? '🛸'
              : selectedMission === DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW
              ? '🎯'
              : '🐝🐝🐝'
          }
          label={Object.keys(missionTypes)
            .find((key) => missionTypes[key] === selectedMission)
            .replace(/_/g, ' ')}
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
    </div>
  );
};

export default MissionTrigger;
