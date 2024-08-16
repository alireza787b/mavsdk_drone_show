import React from 'react';

const MissionCard = ({ missionType, icon, label, onClick, isCancel }) => (
  <div
    className={`mission-card ${isCancel ? 'cancel-mission-card' : ''}`}
    onClick={() => onClick(missionType)}
  >
    <div className="mission-icon">{icon}</div>
    <div className="mission-name">{label}</div>
  </div>
);

export default MissionCard;
