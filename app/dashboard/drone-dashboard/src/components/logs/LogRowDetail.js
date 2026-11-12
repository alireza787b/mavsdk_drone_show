import React from 'react';
import { ConfirmDialog } from '../ui';
import { recordTime } from '../../features/log-workspace/logWorkspace';

export default function LogRowDetail({ entry, sourceLabel, onClose }) {
  if (!entry) return null;
  const raw = entry._raw || Object.fromEntries(Object.entries(entry).filter(([key]) => !key.startsWith('_')));
  return <ConfirmDialog appearance="console" open title={`${entry.level || 'Unknown level'} · ${entry.component || 'Unknown component'}`}
    cancelLabel="Close" confirmLabel="Done" onCancel={onClose} onConfirm={onClose}
    message={<div className="logs-record-detail"><p className="logs-context">{sourceLabel || entry.source || 'Unknown source'}</p>
      <dl className="logs-facts"><dt>Time UTC</dt><dd>{recordTime(entry.ts)}</dd><dt>Recorded source</dt><dd>{entry.source || 'Unknown'}</dd>
        <dt>Hardware</dt><dd>{entry.drone_id != null ? `#${entry.drone_id}` : 'Not recorded'}</dd><dt>Session</dt><dd>{entry.session_id || 'Not recorded'}</dd></dl>
      <p className="logs-full-message">{entry.msg ?? 'No message recorded'}</p>
      {entry.extra != null && <details open><summary>Structured data</summary><pre>{JSON.stringify(entry.extra, null, 2)}</pre></details>}
      <details><summary>Raw entry</summary><pre>{JSON.stringify(raw, null, 2)}</pre></details>
    </div>} />;
}
