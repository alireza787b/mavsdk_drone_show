import React from 'react';

const MissionCard = ({ missionType, icon, category, label, summary, note, onClick, isCancel }) => (
  <button
    type="button"
    className={`mission-card ${isCancel ? 'cancel-mission-card' : ''}`}
    onClick={() => onClick(missionType)}
    title={[label, summary, note].filter(Boolean).join(' ')}
    aria-label={[label, summary, note].filter(Boolean).join('. ')}
  >
    <div className="mission-card__header">
      <div className="mission-icon">{icon}</div>
      <span className="mission-card__eyebrow">{category}</span>
    </div>
    <div className="mission-name">{label}</div>
    <div className="mission-summary">{summary}</div>
  </button>
);

export default MissionCard;
