import React from 'react';
import PropTypes from 'prop-types';
import { FaExclamationTriangle } from 'react-icons/fa';

import '../styles/RuntimeModeBadge.css';

function normalizeMode(mode) {
  const normalized = String(mode || '').trim().toLowerCase();
  if (normalized === 'real') {
    return 'real';
  }
  if (normalized === 'sitl') {
    return 'sitl';
  }
  return 'unknown';
}

export default function RuntimeModeBadge({
  mode,
  configuredMode = '',
  restartRequired = false,
  compact = false,
  className = '',
}) {
  const normalizedMode = normalizeMode(mode);
  const normalizedConfiguredMode = normalizeMode(configuredMode);
  const label = normalizedMode === 'real'
    ? 'REAL'
    : normalizedMode === 'sitl'
      ? 'SITL'
      : 'UNKNOWN';
  const configuredLabel = normalizedConfiguredMode === 'real'
    ? 'REAL'
    : normalizedConfiguredMode === 'sitl'
      ? 'SITL'
      : 'UNKNOWN';
  const configMatches = normalizedConfiguredMode === normalizedMode && normalizedConfiguredMode !== 'unknown';
  const title = restartRequired
    ? `${label} runtime. Persisted host config is ${configuredLabel}; apply restart in GCS Runtime.`
    : configMatches
      ? `${label} runtime. Persisted host config matches the running process.`
      : `${label} runtime.`;
  const ariaLabel = restartRequired
    ? `${label} runtime, configured ${configuredLabel}, restart required`
    : configMatches
      ? `${label} runtime, host config aligned`
      : `${label} runtime`;

  return (
    <span
      className={`runtime-mode-badge runtime-mode-badge--${normalizedMode}${compact ? ' runtime-mode-badge--compact' : ''}${restartRequired ? ' runtime-mode-badge--restart-required' : ''}${className ? ` ${className}` : ''}`}
      title={title}
      aria-label={ariaLabel}
    >
      <span className="runtime-mode-badge__label">{label}</span>
      {restartRequired ? (
        <FaExclamationTriangle className="runtime-mode-badge__warning" aria-hidden="true" />
      ) : null}
    </span>
  );
}

RuntimeModeBadge.propTypes = {
  mode: PropTypes.string,
  configuredMode: PropTypes.string,
  restartRequired: PropTypes.bool,
  compact: PropTypes.bool,
  className: PropTypes.string,
};
