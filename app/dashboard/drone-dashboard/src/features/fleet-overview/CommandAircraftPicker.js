import React, { useMemo, useRef, useState } from 'react';
import { FaBroadcastTower, FaRegClock, FaUnlink, FaQuestionCircle, FaTimes, FaEllipsisH, FaSearch } from 'react-icons/fa';
import { ConfirmDialog } from '../../components/ui';
import AircraftChoiceRow from '../../components/ui/AircraftChoiceRow';
import InfoHint from '../../components/InfoHint';
import { matchesDroneSearchQuery } from '../../utilities/dronePresentation';
import { uniqueTargetIds } from './targetSelection';
import './CommandAircraft.css';

/** Draft membership is local until Apply. Live resources never reconcile it. */
export default function CommandAircraftPicker({ selectedIds, configuredIds, aircraft, groups = [], onApply, onClose,
  preset = null, showAllConfigured = true, help = 'This chooses command recipients, not what the board displays. No command is sent here.' }) {
  const [initialIds] = useState(() => uniqueTargetIds(selectedIds));
  const [draft, setDraft] = useState(initialIds);
  const [query, setQuery] = useState('');
  const searchRef = useRef(null);
  const knownIds = useMemo(() => uniqueTargetIds(configuredIds), [configuredIds]);
  const byId = useMemo(() => new Map(aircraft.map(item => [item.id, item])), [aircraft]);
  const roster = uniqueTargetIds([...knownIds, ...initialIds, ...draft]);
  const rows = roster.map(id => ({ id, item: byId.get(id), missing: !knownIds.includes(id) }));
  const visible = rows.filter(({ id, item }) => matchesDroneSearchQuery(item?.raw || { hw_id: id }, query));
  const availableIds = knownIds.filter(id => byId.get(id)?.availability.available);
  const PresetIcon = preset?.Icon || FaBroadcastTower;
  const presetIds = preset?.ids || availableIds;
  const toggle = (id, include) => setDraft(previous => include ? uniqueTargetIds([...previous, id]) : previous.filter(value => value !== id));
  const groupChoices = groups.map(group => ({ ...group,
    ids: uniqueTargetIds(group.drones.map(row => row.hw_id)).filter(id => knownIds.includes(id)),
  })).filter(group => group.ids.length);
  return <ConfirmDialog open title="Command aircraft" appearance="console" initialFocusRef={searchRef}
    confirmLabel={`Use ${draft.length} aircraft`} onConfirm={() => onApply([...draft])} onCancel={onClose}
    message={<div className="command-aircraft-picker">
      <div className="command-aircraft-picker__tools">
        <button type="button" aria-label={preset?.ariaLabel || 'Use available now'} title={preset?.title || 'Replace this draft with the aircraft available now'}
          onClick={() => setDraft([...presetIds])}><PresetIcon aria-hidden="true" /><span>{preset?.label || 'Available'}</span><small>{presetIds.length}</small></button>
        {groupChoices.length > 1 && <select aria-label="Choose command cluster" value="" title="Use a cluster's current aircraft"
          onChange={event => { const group = groupChoices.find(row => String(row.id) === event.target.value); if (group) setDraft([...group.ids]); }}>
          <option value="">Cluster…</option>{groupChoices.map(group => <option key={group.id} value={group.id}>{group.label || `Cluster ${group.leaderId || group.id}`} · {group.ids.length}</option>)}
        </select>}
        <button type="button" aria-label="Clear command aircraft" title="Clear this draft" disabled={!draft.length} onClick={() => setDraft([])}><FaTimes aria-hidden="true" /></button>
        {showAllConfigured && <details className="command-aircraft-picker__more"><summary aria-label="More command aircraft options" title="More selection options"><FaEllipsisH aria-hidden="true" /></summary>
          <button type="button" onClick={() => setDraft([...knownIds])}>All configured</button>
        </details>}
      </div>
      <label className="command-aircraft-picker__search"><FaSearch aria-hidden="true" /><input ref={searchRef} type="search"
        aria-label="Find command aircraft" placeholder="Find aircraft" value={query} onChange={event => setQuery(event.target.value)} /></label>
      <div className="command-aircraft-picker__count"><span aria-live="polite">{draft.length} aircraft</span>
        <InfoHint hoverable label="About command aircraft" placement="bottom" content={help} />
      </div>
      <div className="command-aircraft-picker__roster" role="group" aria-label="Aircraft for commands">
        {visible.map(({ id, item, missing }) => {
          const Icon = missing ? FaQuestionCircle : item?.availability.stale ? FaRegClock : item?.availability.available ? FaBroadcastTower : FaUnlink;
          const status = missing ? 'Missing from configuration' : item?.availability.label || 'Unknown';
          return <AircraftChoiceRow key={id} id={id} name={item?.label || `Aircraft ${id}`} checked={draft.includes(id)}
            detail={`H${id}${item?.identity.posId ? ` · P${item.identity.posId}` : ''}`} onChange={include => toggle(id, include)}
            status={<span title={status} aria-label={status}><Icon aria-hidden="true" />{missing && <span> Missing</span>}</span>} />;
        })}
        {!visible.length && <p className="command-aircraft-picker__empty">No matches</p>}
      </div>
    </div>} />;
}
