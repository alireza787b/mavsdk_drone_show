// src/components/logs/LogExportDialog.js
import React, { useState } from 'react';
import { toast } from 'react-toastify';
import { exportSessions } from '../../services/logService';
import { formatSessionLabel } from '../../utilities/logViewerUtils';

const LogExportDialog = ({ sessions, onClose, droneId = null, scopeLabel = 'GCS' }) => {
  const [format, setFormat] = useState('jsonl');
  const [selectedIds, setSelectedIds] = useState([]);
  const [exporting, setExporting] = useState(false);

  const toggleSession = (id) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(s => s !== id) : [...prev, id]
    );
  };

  const handleExport = async () => {
    if (selectedIds.length === 0) {
      toast.warning('Select at least one session to export');
      return;
    }
    setExporting(true);
    try {
      const resp = await exportSessions(selectedIds, format, droneId);
      const blob = resp.data;
      // Backend returns ZIP when multiple sessions selected, regardless of format choice
      const ext = selectedIds.length > 1 ? 'zip' : format;
      const scopeSlug = droneId != null ? `drone_${droneId}` : 'gcs';
      const filename = `mds_logs_${scopeSlug}_${new Date().toISOString().slice(0, 19).replace(/:/g, '')}.${ext}`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
      toast.success(`Exported ${selectedIds.length} session(s)`);
      onClose();
    } catch (err) {
      toast.error(`Export failed: ${err.message}`);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="log-export-overlay" onClick={onClose}>
      <div className="log-export-dialog" onClick={e => e.stopPropagation()}>
        <h3>Export {scopeLabel} Log Sessions</h3>
        <div className="export-options">
          <label className="log-export-format-control">
            Format:
            <select value={format} onChange={e => setFormat(e.target.value)}>
              <option value="jsonl">JSONL (.jsonl)</option>
              <option value="zip">ZIP (.zip)</option>
            </select>
          </label>
          <div className="log-export-session-list">
            {(sessions || []).map(s => (
              <label key={s.session_id} className="log-export-session-option">
                <input
                  type="checkbox"
                  checked={selectedIds.includes(s.session_id)}
                  onChange={() => toggleSession(s.session_id)}
                />
                {' '}{formatSessionLabel(s)}
              </label>
            ))}
          </div>
        </div>
        <div className="export-actions">
          <button type="button" onClick={onClose} disabled={exporting}>Cancel</button>
          <button type="button" onClick={handleExport} disabled={exporting} className="active">
            {exporting ? 'Exporting...' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  );
};

export default LogExportDialog;
