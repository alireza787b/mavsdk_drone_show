// src/components/logs/LogViewerToolbar.js
import React from 'react';
import { FaEye, FaCode, FaPause, FaPlay, FaSearch, FaDownload, FaTrash, FaPlane, FaRegClock } from 'react-icons/fa';
import { LIVE_TIME_WINDOWS, LOG_LEVELS, MODES } from '../../constants/logConstants';
import LogLiveIndicator from './LogLiveIndicator';
import LogSessionSelector from './LogSessionSelector';

const LogViewerToolbar = ({
  mode,
  onModeChange,
  level,
  onLevelChange,
  paused,
  onTogglePause,
  connected,
  searchQuery,
  onSearchChange,
  sessions,
  selectedSession,
  onSessionSelect,
  sessionsLoading,
  onExportOpen,
  onOnboardUlogOpen,
  onClear,
  scopeDroneId,
  scopeOptions,
  onScopeChange,
  liveWindow,
  onLiveWindowChange,
  timeStart,
  onTimeStartChange,
  timeEnd,
  onTimeEndChange,
  onClearTimeRange,
}) => {
  const selectedScope = scopeDroneId != null
    ? (scopeOptions || []).find((option) => String(option.hw_id) === String(scopeDroneId)) || null
    : null;
  const liveLabel = scopeDroneId != null ? `Live ${selectedScope?.label || `H${scopeDroneId}`}` : 'Live GCS';

  return (
    <div className="log-toolbar" role="toolbar" aria-label="Log viewer controls">
      {/* Mode toggle */}
      <div className="log-mode-toggle">
        <button
          type="button"
          className={mode === MODES.OPS ? 'active' : ''}
          onClick={() => onModeChange(MODES.OPS)}
          data-help="Operations mode - WARNING+ only"
          aria-pressed={mode === MODES.OPS}
        >
          <FaEye size={12} /> <span className="log-button-text">Ops</span>
        </button>
        <button
          type="button"
          className={mode === MODES.DEV ? 'active' : ''}
          onClick={() => onModeChange(MODES.DEV)}
          data-help="Developer mode - all levels, search, export"
          aria-pressed={mode === MODES.DEV}
        >
          <FaCode size={12} /> <span className="log-button-text">Dev</span>
        </button>
      </div>

      {/* Level filter */}
      <div className="log-toolbar-group">
        <select
          value={level || ''}
          onChange={e => onLevelChange(e.target.value || null)}
          aria-label="Minimum log level"
        >
          <option value="">All Levels</option>
          {LOG_LEVELS.map(l => (
            <option key={l} value={l}>{l}</option>
          ))}
        </select>
      </div>

      <div className="log-toolbar-group">
        <FaPlane size={12} />
        <select
          value={scopeDroneId != null ? String(scopeDroneId) : '__gcs__'}
          onChange={(event) => {
            const nextValue = event.target.value;
            onScopeChange(nextValue === '__gcs__' ? null : Number(nextValue));
          }}
          aria-label="Select log scope"
        >
          <option value="__gcs__">GCS</option>
          {(scopeOptions || []).map((option) => (
            <option key={option.hw_id} value={option.hw_id}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {/* Session selector */}
      <LogSessionSelector
        sessions={sessions}
        selectedSession={selectedSession}
        onSelect={onSessionSelect}
        loading={sessionsLoading}
        liveLabel={liveLabel}
      />

      {/* Live indicator */}
      {!selectedSession && (
        <LogLiveIndicator connected={connected} paused={paused} />
      )}

      {selectedSession ? (
        <div className="log-toolbar-group log-time-range-group">
          <FaRegClock size={12} />
          <input
            type="datetime-local"
            value={timeStart}
            onChange={(event) => onTimeStartChange(event.target.value)}
            aria-label="Filter logs from time"
          />
          <span className="log-time-range-separator">to</span>
          <input
            type="datetime-local"
            value={timeEnd}
            onChange={(event) => onTimeEndChange(event.target.value)}
            aria-label="Filter logs to time"
          />
          {(timeStart || timeEnd) && (
            <button type="button" onClick={onClearTimeRange} data-help="Clear time range">
              <span className="log-button-text">Reset</span>
            </button>
          )}
        </div>
      ) : (
        <div className="log-toolbar-group">
          <FaRegClock size={12} />
          <select
            value={liveWindow}
            onChange={(event) => onLiveWindowChange(event.target.value)}
            aria-label="Live log time window"
          >
            {LIVE_TIME_WINDOWS.map((window) => (
              <option key={window.value} value={window.value}>
                {window.label}
              </option>
            ))}
          </select>
        </div>
      )}

      <div className="log-toolbar-spacer" />

      {/* Search (Developer mode only) */}
      {mode === MODES.DEV && (
        <div className="log-toolbar-group">
          <FaSearch size={12} />
          <input
            type="text"
            className="log-search-input"
            placeholder="Search logs..."
            value={searchQuery}
            onChange={e => onSearchChange(e.target.value)}
            aria-label="Search log messages"
          />
        </div>
      )}

      {/* Pause/Resume */}
      {!selectedSession && (
        <button
          type="button"
          onClick={onTogglePause}
          data-help={paused ? 'Resume' : 'Pause'}
          aria-pressed={paused}
          aria-label={paused ? 'Resume live log stream' : 'Pause live log stream'}
        >
          {paused ? <FaPlay size={12} /> : <FaPause size={12} />}
          <span className="log-button-text">{paused ? 'Resume' : 'Pause'}</span>
        </button>
      )}

      {/* Clear live buffer */}
      {!selectedSession && (
        <button
          type="button"
          onClick={onClear}
          data-help="Clear live buffer"
          aria-label="Clear live log buffer"
        >
          <FaTrash size={12} />
        </button>
      )}

      {scopeDroneId != null && (
        <button
          type="button"
          onClick={onOnboardUlogOpen}
          data-help={`Manage onboard PX4 ULogs for ${liveLabel}`}
          aria-label={`Manage onboard PX4 ULogs for ${liveLabel}`}
        >
          <FaDownload size={12} /> <span className="log-button-text">ULog</span>
        </button>
      )}

      {/* Export (Developer mode only) */}
      {mode === MODES.DEV && (
        <button
          type="button"
          onClick={onExportOpen}
          data-help="Export sessions"
          aria-label="Export log sessions"
        >
          <FaDownload size={12} /> <span className="log-button-text">Export</span>
        </button>
      )}
    </div>
  );
};

export default LogViewerToolbar;
