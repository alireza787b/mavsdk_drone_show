import React, { useState, useEffect } from 'react';
import MissionCard from './MissionCard';
import MissionDetails from './MissionDetails';
import MissionNotification from './MissionNotification';

const MissionCardsContainer = ({ missionTypes, onSendCommand }) => {
  const [selectedMission, setSelectedMission] = useState('');
  const [timeDelay, setTimeDelay] = useState(10);  // Default time delay in seconds
  const [useSlider, setUseSlider] = useState(true);  // Toggle between slider and clock
  const [selectedTime, setSelectedTime] = useState('');  // For time picker input
  const [notification, setNotification] = useState('');  // For user notifications

  useEffect(() => {
    // Set default to user system time + 30 seconds when component mounts
    const now = new Date();
    now.setSeconds(now.getSeconds() + 30);
    setSelectedTime(now.toTimeString().slice(0, 8)); // Format as HH:MM:SS
  }, []);

  const handleMissionSelect = (missionType) => {
    setSelectedMission(missionType);
    setTimeDelay(10);  // Reset time delay to default when a new mission is selected

    // Handle Cancel Mission directly
    if (missionType === 'NONE') {
      if (window.confirm('Are you sure you want to cancel the mission immediately?')) {
        const commandData = {
          missionType: missionType,
          triggerTime: Math.floor(Date.now() / 1000),
        };
        onSendCommand(commandData);
        setNotification('Cancel Mission command sent successfully.');
        setTimeout(() => setNotification(''), 3000);
      }
    }
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

    if (!window.confirm(confirmationMessage)) {
      return;
    }

    const commandData = {
      missionType: selectedMission,
      triggerTime,
    };
    onSendCommand(commandData);
    setNotification(`"${missionName}" command sent successfully.`);
    setTimeout(() => setNotification(''), 3000);
  };

  const handleBack = () => {
    setSelectedMission(''); // Reset mission selection
  };

  const getMissionDescription = (missionType) => {
    switch (missionType) {
      case 'DRONE_SHOW_FROM_CSV':
        return 'This mission mode triggers a drone show based on pre-defined CSV data.';
      case 'CUSTOM_CSV_DRONE_SHOW':
        return 'This mission mode triggers a custom drone show using a custom CSV file.';
      case 'SMART_SWARM':
        return 'This mission mode coordinates a smart swarm of drones.';
      case 'NONE':
        return 'Cancel any currently active mission.';
      default:
        return '';
    }
  };

  return (
    <div className="mission-trigger-content">
      {notification && <MissionNotification message={notification} />}

      {!selectedMission && (
        <div className="mission-cards">
          {Object.entries(missionTypes).map(([key, value]) => (
            <MissionCard
              key={value}
              missionType={value}
              icon={
                key === 'DRONE_SHOW_FROM_CSV' ? '🛸' :
                key === 'CUSTOM_CSV_DRONE_SHOW' ? '🎯' :
                key === 'SMART_SWARM' ? '🐝🐝🐝' :
                '🚫'
              }
              label={key === 'NONE' ? 'Cancel Mission' : key.replace(/_/g, ' ')}
              onClick={handleMissionSelect}
              isCancel={key === 'NONE'}
            />
          ))}
        </div>
      )}

      {selectedMission && selectedMission !== 'NONE' && (
        <MissionDetails
          missionType={selectedMission}
          icon={
            selectedMission === 'DRONE_SHOW_FROM_CSV' ? '🛸' :
            selectedMission === 'CUSTOM_CSV_DRONE_SHOW' ? '🎯' :
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
    </div>
  );
};

export default MissionCardsContainer;
