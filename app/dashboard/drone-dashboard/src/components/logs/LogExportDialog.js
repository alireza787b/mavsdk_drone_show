import React, { useRef, useState } from 'react';
import { ConfirmDialog } from '../ui';
import { exportSessions } from '../../services/logService';
import { formatSessionLabel } from '../../utilities/logViewerUtils';
import { logError } from '../../features/log-workspace/logWorkspace';

export default function LogExportDialog({ sessions, selectedSession, filters, onClose, droneId = null, scopeLabel = 'GCS' }) {
  const [scope] = useState(() => ({ sessions: [...sessions], droneId, scopeLabel, filters: { ...filters } }));
  const [format, setFormat] = useState('jsonl'), [mode, setMode] = useState('whole');
  const [ids, setIds] = useState(() => selectedSession ? [selectedSession] : []), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [requested, setRequested] = useState(false), [coverage, setCoverage] = useState(null), lock = useRef(false);
  const submit = async () => {
    if (!ids.length || lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const response = await exportSessions(ids, format, scope.droneId, mode === 'filtered' ? scope.filters : null);
      const url = URL.createObjectURL(response.data), anchor = document.createElement('a');
      anchor.href = url; anchor.download = `mds-logs-${scope.droneId == null ? 'gcs' : `H${scope.droneId}`}.${ids.length > 1 ? 'zip' : format}`; anchor.click(); URL.revokeObjectURL(url);
      setRequested(true);
      setCoverage({ records: response.headers?.['x-mds-export-records'], skipped: response.headers?.['x-mds-export-skipped'], scope: response.headers?.['x-mds-export-scope'] });
    } catch (failure) { setError(logError(failure)); }
    finally { lock.current = false; setBusy(false); }
  };
  return <ConfirmDialog appearance="console" open title={`Export ${scope.scopeLabel} sessions`} busy={busy} cancelLabel="Close" confirmLabel={requested ? 'Download again' : 'Prepare export'} onCancel={onClose} onConfirm={submit} confirmDisabled={!ids.length}
    message={<div className="logs-export"><fieldset disabled={busy}><legend>Coverage</legend><label className="logs-check"><input type="radio" checked={mode === 'whole'} onChange={() => setMode('whole')} />Whole selected sessions · all severities, no view filters</label>
      <label className="logs-check"><input type="radio" checked={mode === 'filtered'} onChange={() => setMode('filtered')} />Current filters · all matching records, not only this page</label></fieldset>
      {mode === 'filtered' && <dl className="logs-facts">{Object.entries(scope.filters).filter(([, value]) => value).map(([key, value]) => <React.Fragment key={key}><dt>{key}</dt><dd>{value}</dd></React.Fragment>)}</dl>}
      <label>Format<select disabled={busy} value={format} onChange={event => setFormat(event.target.value)}><option value="jsonl">JSONL</option><option value="zip">ZIP</option></select></label>
      <fieldset disabled={busy}><legend>Frozen source · {ids.length} / 100 sessions</legend>{scope.sessions.map(session => <label key={session.session_id} className="logs-check"><input type="checkbox" checked={ids.includes(session.session_id)} disabled={!ids.includes(session.session_id) && ids.length >= 100} onChange={() => setIds(previous => previous.includes(session.session_id) ? previous.filter(id => id !== session.session_id) : [...previous, session.session_id])} />{formatSessionLabel(session)}</label>)}</fieldset>
      {requested && <p role="status">Browser download requested. Saving to disk is not verified.{coverage?.records != null ? ` ${coverage.records} records exported.` : ''}{Number(coverage?.skipped) > 0 ? ` ${coverage.skipped} records skipped; export coverage is incomplete.` : ''}</p>}{error && <p role="alert">{error}</p>}
    </div>} />;
}
