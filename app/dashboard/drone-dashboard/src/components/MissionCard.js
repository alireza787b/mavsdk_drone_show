import React from 'react';

const MissionCard = ({ missionType, icon, category, label, summary, note, onClick, isCancel }) => (
  <button
    type="button"
    className={`mission-card ${isCancel ? 'cancel-mission-card' : ''}`}
    onClick={() => onClick(missionType)}
  >
    <div className="mission-card__header">
      <div className="mission-icon">{icon}</div>
      <span className="mission-card__eyebrow">{category}</span>
    </div>
    <div className="mission-name">{label}</div>
    <div className="mission-summary">{summary}</div>
    {note && <div className="mission-note">{note}</div>}
  </button>
);

export default MissionCard;
