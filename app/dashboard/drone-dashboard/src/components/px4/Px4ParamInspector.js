import React, { useState } from 'react';
import { ConfirmDialog } from '../ui';
import { formatParameterRange, formatParameterValue, parseParameterValue } from '../../utilities/px4ParameterValues';

const normalize = value => String(value || '').replace(/\s+/g, ' ').trim();
const comparable = value => normalize(value).replace(/[\s.。:;,!?()[\]{}"'`´\-\u2013\u2014]+$/g, '').toLocaleLowerCase();

export function buildParameterDescriptions(row) {
  const shortDescription = normalize(row?.short_description);
  let longDescription = normalize(row?.long_description);
  const summary = comparable(shortDescription);
  if (summary) {
    while (longDescription) {
      const first = longDescription.match(/^(.+?[.!?。])(?:\s+|$)/);
      if (!first || comparable(first[1]) !== summary) break;
      longDescription = longDescription.slice(first[0].length).trim();
    }
    if (comparable(longDescription) === summary) longDescription = '';
    else if (comparable(longDescription).startsWith(summary)) {
      longDescription = longDescription.slice(shortDescription.length).replace(/^[\s.。:;,\-–—!?]+/, '').trim();
    }
  }
  return { shortDescription, longDescription };
}

/** Inspection is read-only until Edit. Exact numeric text is never display-rounded. */
export default function Px4ParamInspector({ row, aircraftLabel, onClose, onStage, blockedReason = '', snapshotLabel = 'Aircraft snapshot', snapshotAgeLabel = '' }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(() => String(row.value ?? ''));
  const [error, setError] = useState('');
  const { shortDescription, longDescription } = buildParameterDescriptions(row);
  const choices = Array.isArray(row.enum_values) ? row.enum_values : [];
  // A list from a catalog/docs page is reference, not a native enum contract.
  const authoritativeEnum = choices.length > 0 && row.authoritative_fields?.includes('enum_values');
  const declaredDraftValue = choices.some(entry => String(entry.value) === value);
  const changeValue = next => { setValue(next); setError(''); };
  const submit = () => {
    if (!editing) { setEditing(true); return; }
    try {
      const parsed = parseParameterValue(value, row.value_type);
      if (onStage({ component_id: row.component_id || 1, name: row.name, value_type: row.value_type, value: parsed })) onClose();
    } catch (failure) { setError(failure.message); }
  };
  return <ConfirmDialog appearance="console" open title={row.name} cancelLabel="Close"
    confirmLabel={editing ? 'Review change' : 'Edit value'} onCancel={onClose} onConfirm={submit}
    confirmDisabled={Boolean(blockedReason) || row.writable === false}
    message={<div className="px4-inspector">
      <p className="px4-context-label">{aircraftLabel} · Component {row.component_id || 1}</p>
      <p className={snapshotLabel === 'Snapshot stale' ? 'px4-stale' : 'px4-context-label'}>{snapshotLabel}{snapshotAgeLabel ? ` · ${snapshotAgeLabel}` : ''}</p>
      <div className="px4-reading"><strong>{formatParameterValue(row.value, row)}</strong><span>{row.unit || ''}</span></div>
      {String(row.value) !== formatParameterValue(row.value, row) && <p className="px4-exact">Exact value <code>{String(row.value)}</code></p>}
      {shortDescription && <p>{shortDescription}</p>}
      <p className="px4-context-label">{row.metadata_authority === 'vehicle' ? 'Vehicle metadata' : row.metadata_authority === 'unavailable' ? 'Metadata unavailable' : 'Reference metadata'} · snapshot values from aircraft</p>
      <dl className="px4-facts">
        <dt>Default{row.authoritative_fields?.includes('default_value') ? '' : ' · reference'}</dt><dd>{formatParameterValue(row.default_value, row, { exact: true })}</dd>
        <dt>Range{row.authoritative_fields?.includes('min_value') || row.authoritative_fields?.includes('max_value') ? '' : ' · reference'}</dt><dd>{formatParameterRange(row)}</dd>
        <dt>Type</dt><dd>{row.value_type.toUpperCase()}{row.unit ? ` · ${row.unit}` : ''}</dd>
        <dt>Reboot</dt><dd>{row.reboot_required == null ? 'Not declared' : row.reboot_required ? 'Required after change' : 'Not required'}</dd>
      </dl>
      {editing && <section className="px4-editor" aria-label="Edit parameter">
        {authoritativeEnum ? <label>New value · vehicle choices<select aria-label={`New value for ${row.name}`} value={value} onChange={event => changeValue(event.target.value)}>
          {!declaredDraftValue && <option value={value}>Not declared by vehicle · {value}</option>}
          {choices.map((entry, index) => <option key={`${entry.value}:${index}`} value={String(entry.value)}>{entry.description || 'No description'} · {String(entry.value)}</option>)}
        </select></label> : <>
          <label>New value{row.unit ? ` · ${row.unit}` : ''}<input type="text" inputMode={row.value_type === 'int' ? 'numeric' : row.value_type === 'float' ? 'decimal' : 'text'}
            aria-label={`New value for ${row.name}`} value={value} onChange={event => changeValue(event.target.value)} /></label>
          {choices.length > 0 && <details className="px4-details"><summary>Reference choices</summary>
            <label>Populate draft from reference<select aria-label={`Reference choice for ${row.name}`} value="" onChange={event => changeValue(event.target.value)}>
              <option value="" disabled>Choose a suggestion…</option>
              {choices.map((entry, index) => <option key={`${entry.value}:${index}`} value={String(entry.value)}>{entry.description || 'No description'} · {String(entry.value)}</option>)}
            </select></label><small>Suggestions only. Other exact values remain allowed.</small>
          </details>}
        </>}
        <div className="px4-text-actions">
          <button type="button" className="operator-button operator-button--ghost" onClick={() => { setValue(String(row.value)); setError(''); }}>Use current</button>
          <button type="button" className="operator-button operator-button--ghost" disabled={row.default_value == null}
            onClick={() => { setValue(String(row.default_value)); setError(''); }}>Use default</button>
          <button type="button" className="operator-button operator-button--ghost" onClick={() => { setEditing(false); setValue(String(row.value)); setError(''); }}>Discard edit</button>
        </div>
        {error && <p role="alert">{error}</p>}
      </section>}
      {blockedReason && <p className="px4-inline-warning">{blockedReason}</p>}
      {row.writable === false && <p>Read only</p>}
      <details className="px4-details"><summary>Details & reference</summary>
        {longDescription && <p>{longDescription}</p>}
        <dl className="px4-facts"><dt>Group</dt><dd>{row.group || 'Not declared'}</dd>
          <dt>Category</dt><dd>{row.category || 'Not declared'}</dd>
          <dt>Step</dt><dd>{row.increment == null ? 'Not declared' : String(row.increment)}</dd>
          <dt>Metadata source</dt><dd>{(row.metadata_sources || []).join(', ').replace(/_/g, ' ') || 'Unknown'}</dd></dl>
        {choices.length > 0 && <><h3>Declared values · {authoritativeEnum ? 'vehicle' : 'reference'}</h3><dl className="px4-enum-list">
          {choices.map((entry, index) => <React.Fragment key={`${entry.value}:${index}`}><dt><code>{String(entry.value)}</code></dt><dd>{entry.description || 'No description'}</dd></React.Fragment>)}
        </dl></>}
        {row.docs_url && <a href={row.docs_url} target="_blank" rel="noopener noreferrer">PX4 reference ↗</a>}
      </details>
    </div>} />;
}
