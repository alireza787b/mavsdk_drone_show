import React, { useState } from 'react';
import { fetchGcsResource, putGcsResource } from '../../services/gcsApiService';
import { OperatorNotice } from '../ui';

export default function TrajectoryFormationPanel({ formation, fleet = [], onSaved, readOnly = false }) {
  const [draft, setDraft] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const rows = draft?.assignments || formation?.assignments || [];
  const change = (id, field, value) => setDraft({ revision: draft?.revision || formation.revision,
    assignments: rows.map((row) => String(row.hw_id) === String(id) ? { ...row, [field]: value } : row) });
  const loadLive = async () => {
    setError(''); setBusy(true);
    try {
      const { data } = await fetchGcsResource('/api/v1/config/swarm');
      setDraft({ revision: draft?.revision || formation.revision,
        assignments: (Array.isArray(data) ? data : data.assignments).map((row) => ({ ...row })) });
    } catch { setError('Smart Swarm layout could not be read. Your mission layout is unchanged.'); }
    finally { setBusy(false); }
  };
  const save = async () => {
    setBusy(true); setError('');
    try {
      const result = await putGcsResource('/api/v1/swarm-trajectories/formation', draft || {
        revision: formation.revision, assignments: rows });
      if (result.data.success !== true) throw new Error('Formation save was not confirmed');
      setDraft(null); onSaved?.();
    } catch (e) { setError(typeof e.response?.data?.detail === 'string' ? e.response.data.detail
      : e.message || 'Formation not saved. Check the leader links and offsets.'); }
    finally { setBusy(false); }
  };
  return <details className="trajectory-formation">
    <summary>Formation <span>{rows.length} aircraft · {draft ? 'Draft' : formation?.saved ? 'Mission layout' : 'Smart Swarm draft'}</span></summary>
    {error && <OperatorNotice tone="warning" title="Formation not saved">{error}</OperatorNotice>}
    {draft && draft.revision !== formation?.revision && <OperatorNotice tone="warning" title="Layout changed elsewhere">Your draft is preserved. Reset it to load the latest layout.</OperatorNotice>}
    <div className="trajectory-formation__scroll"><table><thead><tr><th>Aircraft</th><th>Follows</th><th>Frame</th><th>North / Forward (m)</th><th>East / Right (m)</th><th>Up (m)</th></tr></thead>
      <tbody>{rows.map((row) => { const id = String(row.hw_id); const name = fleet.find((d) => String(d.hw_id) === id)?.name || `H${id}`;
        return <tr key={id}><th>{name}</th><td><select aria-label={`${name} follows`} value={row.follow}
          disabled={readOnly || busy} onChange={(e) => change(id, 'follow', Number(e.target.value))}>
          <option value="0">Leader</option>{rows.filter((d) => String(d.hw_id) !== id).map((d) => <option key={d.hw_id} value={d.hw_id}>
            {fleet.find((f) => String(f.hw_id) === String(d.hw_id))?.name || `H${d.hw_id}`}</option>)}</select></td>
          <td><select aria-label={`${name} frame`} value={row.frame || 'ned'} disabled={readOnly || busy} onChange={(e) => change(id, 'frame', e.target.value)}>
            <option value="ned">NED</option><option value="body">Body</option></select></td>
          {['offset_x', 'offset_y', 'offset_z'].map((axis) => <td key={axis}><input aria-label={`${name} ${axis}`} type="number" step="any"
            value={row[axis] ?? 0} disabled={readOnly || busy} onChange={(e) => change(id, axis, e.target.value === '' ? null : Number(e.target.value))} /></td>)}
        </tr>; })}</tbody></table></div>
    <div className="trajectory-formation__actions">
      <button type="button" className="operator-button operator-button--primary" disabled={readOnly || busy || !formation || (!draft && formation.saved)
        || Boolean(draft && draft.revision !== formation.revision)} onClick={save}>{busy ? 'Saving…' : 'Save mission layout'}</button>
      <button type="button" className="operator-button operator-button--ghost" disabled={readOnly || busy || !formation}
        data-help="Copy the current Smart Swarm leaders, followers, frames and offsets into this mission draft. The live formation is unchanged."
        onClick={loadLive}>Copy Smart Swarm</button>
      <button type="button" className="operator-button operator-button--ghost" disabled={!draft || busy} onClick={() => { setDraft(null); setError(''); }}>Reset draft</button>
    </div>
  </details>;
}
