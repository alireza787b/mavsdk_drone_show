import React from 'react';

const MissionCard = ({ missionType, icon, category, label, summary, note, onClick, href, isCancel, disabled = false }) => {
  const Control = href ? 'a' : 'button';
  return <Control
    href={disabled ? undefined : href}
    type={href ? undefined : 'button'}
    disabled={href ? undefined : disabled}
    aria-disabled={href && disabled ? true : undefined}
    className={`mission-card ${isCancel ? 'cancel-mission-card' : ''}`}
    onClick={href ? undefined : () => onClick(missionType)}
    title={[label, summary, note].filter(Boolean).join(' ')}
    aria-label={[label, summary, note].filter(Boolean).join('. ')}
  >
    <div className="mission-card__header">
      <div className="mission-icon">{icon}</div>
      <span className="mission-card__eyebrow">{category}</span>
    </div>
    <div className="mission-name">{label}</div>
    <div className="mission-summary">{summary}</div>
  </Control>;
};

export default MissionCard;
