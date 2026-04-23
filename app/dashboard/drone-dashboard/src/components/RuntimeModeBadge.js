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
  restartRequired = false,
  compact = false,
  className = '',
}) {
  const normalizedMode = normalizeMode(mode);
  const label = normalizedMode === 'real'
    ? 'REAL'
    : normalizedMode === 'sitl'
      ? 'SITL'
      : 'UNKNOWN';
  const title = restartRequired
    ? `${label} runtime. Persisted host config differs from the running process; apply restart in Runtime Admin.`
    : `${label} runtime.`;

  return (
    <span
      className={`runtime-mode-badge runtime-mode-badge--${normalizedMode}${compact ? ' runtime-mode-badge--compact' : ''}${restartRequired ? ' runtime-mode-badge--restart-required' : ''}${className ? ` ${className}` : ''}`}
      title={title}
      aria-label={restartRequired ? `${label} runtime, restart required` : `${label} runtime`}
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
  restartRequired: PropTypes.bool,
  compact: PropTypes.bool,
  className: PropTypes.string,
};
