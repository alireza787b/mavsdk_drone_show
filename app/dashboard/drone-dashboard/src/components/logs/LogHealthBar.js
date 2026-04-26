// src/components/logs/LogHealthBar.js
import React, { useMemo } from 'react';
import { FaServer, FaPlane, FaExclamationTriangle, FaTimesCircle, FaClock } from 'react-icons/fa';
import { SEVERITY_FOCUS } from '../../constants/logConstants';

const LogHealthBar = ({
  entries,
  displayedCount,
  gcsOnline,
  fleetCount,
  onlineDroneCount,
  severityFocus,
  onSeverityFocusChange,
}) => {
  const { errorCount, warningCount } = useMemo(() => {
    let errors = 0, warnings = 0;
    for (const e of entries) {
      if (e.level === 'ERROR' || e.level === 'CRITICAL') errors++;
      else if (e.level === 'WARNING') warnings++;
    }
    return { errorCount: errors, warningCount: warnings };
  }, [entries]);

  return (
    <div className="log-health-bar" role="status" aria-label="System health">
      <div className="log-health-stat">
        <FaServer size={12} />
        <span>GCS</span>
        <span className={`stat-value log-health-status ${gcsOnline ? 'is-online' : 'is-offline'}`}>
          {gcsOnline ? 'Online' : 'Offline'}
        </span>
      </div>
      <div className="log-health-stat">
        <FaPlane size={12} />
        <span>Drones</span>
        <span className="stat-value">
          {fleetCount > 0 ? `${onlineDroneCount}/${fleetCount}` : '0'}
        </span>
      </div>
      <button
        type="button"
        className={`log-health-stat log-health-button error-count ${severityFocus === SEVERITY_FOCUS.ERRORS ? 'active' : ''}`}
        aria-pressed={severityFocus === SEVERITY_FOCUS.ERRORS}
        onClick={() => onSeverityFocusChange(
          severityFocus === SEVERITY_FOCUS.ERRORS ? null : SEVERITY_FOCUS.ERRORS
        )}
      >
        <FaTimesCircle size={12} />
        <span>Errors</span>
        <span className="stat-value">{errorCount}</span>
      </button>
      <button
        type="button"
        className={`log-health-stat log-health-button warning-count ${severityFocus === SEVERITY_FOCUS.WARNINGS ? 'active' : ''}`}
        aria-pressed={severityFocus === SEVERITY_FOCUS.WARNINGS}
        onClick={() => onSeverityFocusChange(
          severityFocus === SEVERITY_FOCUS.WARNINGS ? null : SEVERITY_FOCUS.WARNINGS
        )}
      >
        <FaExclamationTriangle size={12} />
        <span>Warnings</span>
        <span className="stat-value">{warningCount}</span>
      </button>
      <div className="log-health-stat">
        <FaClock size={12} />
        <span>Showing</span>
        <span className="stat-value">{displayedCount}</span>
      </div>
    </div>
  );
};

export default LogHealthBar;
