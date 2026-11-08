import React from 'react';
import { FaCheck, FaUndoAlt } from 'react-icons/fa';
import { AircraftSilhouette } from './SwarmAircraftSymbol';
import { ActionIconButton } from './ui/OperatorPrimitives';
import '../styles/SwarmFormationSource.css';

function CaptureSymbol() {
  return <svg viewBox="0 0 64 48" aria-hidden="true" focusable="false">
    <path className="formation-source__crosshair" d="M 4 15 V 4 H 16 M 48 4 H 60 V 15 M 4 33 V 44 H 16 M 48 44 H 60 V 33" />
    {[[32, 15], [18, 32], [46, 32]].map(([x, y]) => <g key={x} transform={`translate(${x} ${y}) scale(.45)`}><AircraftSilhouette /></g>)}
  </svg>;
}

function SourceAction({ href, onClick, icon, label, help, disabled, current }) {
  const className = `formation-source__action${current ? ' is-current' : ''}`;
  const content = <>{label}{current && <FaCheck aria-hidden="true" className="formation-source__check" />}</>;
  if (href) return <a href={disabled ? undefined : href} aria-disabled={disabled || undefined}
    aria-label={label} title={help}
    className={`operator-action-icon-button operator-action-icon-button--neutral operator-action-icon-button--md ${className}`}>
    <span className="operator-action-icon-button__icon" aria-hidden="true">{icon}</span>
    <span className="operator-action-icon-button__text">{content}</span>
  </a>;
  return <ActionIconButton label={label} icon={icon} onClick={onClick} disabled={disabled}
    className={className} title={help}>{content}</ActionIconButton>;
}

/** Two ways to prepare the same plan, not persistent live-following modes. */
export default function SwarmFormationSource({ onSaved, onCapture, savedHref, captureHref,
  savedCurrent = false, disabled = false, captureDisabled = false }) {
  return <div className="formation-source" role="group" aria-label="Formation starting point">
    <span className="formation-source__label">Formation</span>
    <SourceAction label="Saved plan" icon={<FaUndoAlt />} onClick={onSaved} href={savedHref}
      disabled={disabled} current={savedCurrent}
      help="Restore the saved plan loaded by this editor. Undo remains available in Design. This does not pull from the repository or send a flight command." />
    <SourceAction label="Capture positions" icon={<CaptureSymbol />} onClick={onCapture} href={captureHref}
      disabled={disabled || captureDisabled}
      help="Preview current aircraft spacing, then choose whether to use it. No flight command is sent." />
  </div>;
}
