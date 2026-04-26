// src/components/logs/LogSessionSelector.js
import React from 'react';
import { FaClock } from 'react-icons/fa';
import { formatSessionLabel } from '../../utilities/logViewerUtils';

const LogSessionSelector = ({ sessions, selectedSession, onSelect, loading, liveLabel = 'Live Session' }) => {
  return (
    <div className="log-session-selector">
      <FaClock size={12} />
      <select
        value={selectedSession || '__live__'}
        onChange={e => onSelect(e.target.value === '__live__' ? null : e.target.value)}
        disabled={loading}
        aria-label="Select log session"
      >
        <option value="__live__">{liveLabel}</option>
        {(sessions || []).map(s => (
          <option key={s.session_id} value={s.session_id} data-session-id={s.session_id}>
            {formatSessionLabel(s)}
          </option>
        ))}
      </select>
    </div>
  );
};

export default LogSessionSelector;
