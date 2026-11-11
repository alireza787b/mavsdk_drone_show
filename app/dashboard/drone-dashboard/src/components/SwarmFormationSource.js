import React from 'react';
import { FaProjectDiagram } from 'react-icons/fa';
import { AircraftSilhouette } from './SwarmAircraftSymbol';
import { ActionIconButton } from './ui/OperatorPrimitives';
import '../styles/SwarmFormationSource.css';

function CaptureSymbol() {
  return <svg viewBox="0 0 64 48" aria-hidden="true" focusable="false">
    <path className="formation-source__crosshair" d="M 4 15 V 4 H 16 M 48 4 H 60 V 15 M 4 33 V 44 H 16 M 48 44 H 60 V 33" />
    {[[32, 15], [18, 32], [46, 32]].map(([x, y]) => <g key={x} transform={`translate(${x} ${y}) scale(.45)`}><AircraftSilhouette /></g>)}
  </svg>;
}

function SourceAction({ href, onClick, icon, label, help, disabled }) {
  const className = 'formation-source__action';
  if (href && !disabled) return <a href={href}
    aria-label={label} title={help}
    className={`operator-action-icon-button operator-action-icon-button--neutral operator-action-icon-button--md ${className}`}>
    <span className="operator-action-icon-button__icon" aria-hidden="true">{icon}</span>
    <span className="operator-action-icon-button__text">{label}</span>
  </a>;
  return <ActionIconButton label={label} icon={icon} onClick={onClick} disabled={disabled}
    className={className} title={help}>{label}</ActionIconButton>;
}

/** Planning and capture share one draft. Revert is a separate editor action. */
export default function SwarmFormationSource({ onPlan, onCapture, planHref, captureHref,
  disabled = false, captureDisabled = false }) {
  return <div className="formation-source" role="group" aria-label="Formation starting point">
    <span className="formation-source__label">Formation</span>
    <SourceAction label="Plan formation" icon={<FaProjectDiagram />} onClick={onPlan} href={planHref}
      disabled={disabled}
      help="Design and edit the formation, starting from the saved layout or your existing draft. Opening planning never resets edits or sends a flight command." />
    <SourceAction label="Capture positions" icon={<CaptureSymbol />} onClick={onCapture} href={captureHref}
      disabled={disabled || captureDisabled}
      help="Preview current aircraft spacing, then choose whether to use it. No flight command is sent." />
  </div>;
}
