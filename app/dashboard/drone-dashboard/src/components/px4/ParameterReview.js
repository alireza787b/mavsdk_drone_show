import React, { useState } from 'react';
import { ConfirmDialog } from '../ui';
import { matchesDroneSearchQuery } from '../../utilities/dronePresentation';
import { formatParameterValue, parameterKey } from '../../utilities/px4ParameterValues';

export const describeAircraft = (aircraft, id) => `${aircraft.find(item => item.id === id)?.label || 'Aircraft'} · H${id}`;

function ChangeTable({ entries, desired = false }) {
  return <div className="px4-table-scroll"><table className="px4-review-table"><thead><tr><th>Parameter</th>{desired && <th>Current</th>}<th>Proposed</th><th>Reference</th></tr></thead>
    <tbody>{entries.map(entry => <tr key={parameterKey(entry)}><th><code>{entry.name}</code><small>Component {entry.component_id || 1} · {entry.value_type}</small></th>
      {desired && <td>{formatParameterValue(entry.current_value, entry, { exact: true })}</td>}
      <td>{formatParameterValue(desired ? entry.desired_value : entry.value, entry, { exact: true })}</td>
      <td>{entry.reboot_required === true ? 'Reboot-sensitive' : entry.reboot_required === false ? 'No reboot declared' : 'Reboot not declared'}</td>
    </tr>)}</tbody></table></div>;
}

export default function ParameterReview({ workspace, aircraft, clusters, now, onClose, knownRuntime }) {
  const { draft, review, reviewBusy, applying } = workspace;
  const [query, setQuery] = useState(''), [detailTarget, setDetailTarget] = useState('');
  const expired = Boolean(review && now >= review.expires_at);
  const target = review?.targets?.find(item => item.hw_id === detailTarget) || review?.targets?.[0];
  const totalChanges = review?.targets?.reduce((sum, item) => sum + item.changes.length, 0) || 0;
  const updateIds = ids => workspace.updateDraft(previous => ({ ...previous, hwIds: [...new Set(ids)], excludedHwIds: [] }));
  const toggle = id => workspace.updateDraft(previous => {
    const selected = previous.hwIds.includes(id);
    return { ...previous, hwIds: selected ? previous.hwIds.filter(value => value !== id) : [...previous.hwIds, id],
      excludedHwIds: selected ? [...new Set([...(previous.excludedHwIds || []), id])] : (previous.excludedHwIds || []).filter(value => value !== id) };
  });
  const hiddenCount = draft.hwIds.filter(id => !aircraft.some(item => item.id === id && matchesDroneSearchQuery(item.raw, query))).length;
  return <ConfirmDialog appearance="console" size="wide" open title={review ? 'Review parameter changes' : 'Prepare parameter changes'}
    cancelLabel="Close" confirmLabel={review ? `Apply ${totalChanges} changes to ${review.hw_ids.length} aircraft` : 'Prepare review'}
    busy={reviewBusy || applying} allowDismissWhileBusy={!applying} onCancel={onClose}
    onConfirm={review ? workspace.apply : workspace.prepare}
    confirmDisabled={!knownRuntime || Boolean(workspace.storageError) || (review ? expired || review.blocked || totalChanges === 0 : !draft.hwIds.length || !draft.entries.length)}
    message={<div className="px4-review">
      <div className="px4-review-heading"><strong>{draft.title}</strong><span>{draft.entries.length} parameter{draft.entries.length === 1 ? '' : 's'}</span></div>
      {draft.importNotes && (draft.importNotes.skippedCount > 0 || draft.importNotes.warnings.length > 0) && <details className="px4-details">
        <summary>Import notes · {draft.importNotes.skippedCount} skipped</summary><ul>{draft.importNotes.warnings.map((warning, index) => <li key={index}>{warning.line != null ? `Line ${warning.line}: ` : ''}{typeof warning === 'string' ? warning : warning.message}</li>)}</ul>
      </details>}
      {reviewBusy && <p role="status">Preparing native review… this may take up to one minute.</p>}
      {workspace.error && <p role="alert" className="px4-inline-warning">{workspace.error}</p>}
      {!knownRuntime && <p role="alert">Runtime mode is unknown. Applying is unavailable.</p>}
      {workspace.storageError && <p role="alert">{workspace.storageError}</p>}
      {!review ? <>
        <fieldset className="px4-targets"><legend>Apply targets · {draft.hwIds.length} selected{hiddenCount ? ` · ${hiddenCount} hidden` : ''}</legend>
          <div className="px4-target-actions"><button type="button" className="operator-button operator-button--ghost" onClick={() => updateIds(aircraft.map(item => item.id))}>All</button>
            <button type="button" className="operator-button operator-button--ghost" onClick={() => updateIds([])}>None</button>
            {!!clusters.length && <label><span className="px4-visually-hidden">Select cluster targets</span><select aria-label="Select cluster targets" value="" onChange={event => {
              const cluster = clusters.find(item => String(item.id) === event.target.value);
              if (cluster) updateIds(cluster.drones.map(item => String(item.hw_id ?? item.hw_ID)));
            }}><option value="">Select cluster…</option>{clusters.map(item => <option key={item.id} value={String(item.id)}>{item.label || `Cluster ${item.leaderId || item.id}`}</option>)}</select></label>}
          </div>
          <label className="px4-search"><span className="px4-visually-hidden">Find apply targets</span><input type="search" aria-label="Find apply targets" placeholder="Find aircraft" value={query} onChange={event => setQuery(event.target.value)} /></label>
          <div className="px4-target-list">{aircraft.filter(item => matchesDroneSearchQuery(item.raw, query)).map(item => <label key={item.id} className="px4-target-row">
            <input type="checkbox" checked={draft.hwIds.includes(item.id)} onChange={() => toggle(item.id)} aria-label={`Apply to ${describeAircraft(aircraft, item.id)}`} />
            <span>{describeAircraft(aircraft, item.id)}</span><small>{item.runtime.label} · {item.armed === null ? 'Arming unknown' : item.armed ? 'Armed' : 'Disarmed'}</small>
          </label>)}</div>
          {draft.hwIds.filter(id => !aircraft.some(item => item.id === id)).map(id => <label key={id} className="px4-target-row"><input type="checkbox" checked onChange={() => toggle(id)} />H{id} · unavailable identity</label>)}
        </fieldset>
        {!!draft.excludedHwIds?.length && <p className="px4-excluded">Excluded explicitly: {draft.excludedHwIds.map(id => describeAircraft(aircraft, id)).join(', ')}</p>}
        <details className="px4-details"><summary>Proposed values · {draft.entries.length}</summary><ChangeTable entries={draft.entries} /></details>
      </> : <>
        <section className="px4-frozen-targets" aria-label="Frozen apply targets"><h3>Apply to {review.hw_ids.length} aircraft</h3><p>{review.hw_ids.map(id => describeAircraft(aircraft, id)).join(' · ')}</p>
          {!!review.excluded_hw_ids?.length && <p>Excluded: {review.excluded_hw_ids.map(id => describeAircraft(aircraft, id)).join(' · ')}</p>}
          <small>Exact aircraft and baseline values are frozen for this review.</small>
        </section>
        {(review.warnings || []).map((warning, index) => <p key={index} className="px4-inline-warning">{warning}</p>)}
        <div className="px4-table-scroll"><table className="px4-review-table"><thead><tr><th>Aircraft</th><th>Changes</th><th>Unchanged</th><th>State</th></tr></thead><tbody>
          {review.targets.map(item => <tr key={item.hw_id}><th>{describeAircraft(aircraft, item.hw_id)}</th><td>{item.changes.length}</td><td>{item.unchanged_count}</td><td>{item.blockers.length ? item.blockers.join(' · ') : 'Reviewed'}{item.warnings.length ? ` · ${item.warnings.join(' · ')}` : ''}</td></tr>)}
        </tbody></table></div>
        {target && <section className="px4-target-diff"><label>Review aircraft<select value={target.hw_id} onChange={event => setDetailTarget(event.target.value)} aria-label="Review aircraft">
          {review.targets.map(item => <option key={item.hw_id} value={item.hw_id}>{describeAircraft(aircraft, item.hw_id)} · {item.changes.length} changes</option>)}
        </select></label><ChangeTable entries={target.changes} desired />
          <small>Baseline snapshot: {target.snapshot_id || 'Unavailable'}</small></section>}
        <div className="px4-text-actions"><button type="button" className="operator-button operator-button--ghost" disabled={applying} onClick={() => workspace.updateDraft(previous => ({ ...previous }))}>Edit review</button>
          {expired && <span role="alert">Review expired. Prepare a new review.</span>}
          {review.blocked && <span role="alert">Blocked. Resolve the listed aircraft conditions before applying.</span>}
        </div>
      </>}
    </div>} />;
}

export { ChangeTable };
