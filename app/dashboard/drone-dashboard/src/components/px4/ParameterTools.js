import React, { useState } from 'react';
import { ConfirmDialog } from '../ui';
import { matchesDroneSearchQuery } from '../../utilities/dronePresentation';
import { parseParameterValue } from '../../utilities/px4ParameterValues';
import { describeAircraft } from './ParameterReview';

export function AircraftChooser({ aircraft, selectedId, onChoose, onClose }) {
  const [query, setQuery] = useState(''), [candidate, setCandidate] = useState(selectedId);
  return <ConfirmDialog appearance="console" open title="Choose aircraft" cancelLabel="Cancel" confirmLabel="Inspect aircraft"
    onCancel={onClose} confirmDisabled={!candidate} onConfirm={() => { onChoose(candidate); onClose(); }}
    message={<div className="px4-aircraft-chooser"><label>Find aircraft<input type="search" aria-label="Find aircraft" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name, hardware or position" /></label>
      <div className="px4-target-list">{aircraft.filter(item => matchesDroneSearchQuery(item.raw, query)).map(item => <label key={item.id} className="px4-target-row">
        <input type="radio" name="inspected-aircraft" value={item.id} checked={candidate === item.id} onChange={() => setCandidate(item.id)} />
        <span>{describeAircraft(aircraft, item.id)}</span><small>{item.runtime.label}</small>
      </label>)}</div></div>} />;
}

export function ManualParameterEntry({ componentIds, onStage, onClose }) {
  const [name, setName] = useState(''), [value, setValue] = useState(''), [type, setType] = useState('float');
  const [component, setComponent] = useState(componentIds[0] || 1), [error, setError] = useState('');
  const stage = () => {
    try {
      const normalized = name.trim().toUpperCase();
      if (!/^[A-Z0-9_]{1,16}$/.test(normalized)) throw new Error('Use a PX4 name: 1–16 letters, digits or underscores.');
      if (onStage({ component_id: Number(component), name: normalized, value_type: type, value: parseParameterValue(value, type) })) onClose();
    } catch (failure) { setError(failure.message); }
  };
  return <ConfirmDialog appearance="console" open title="Manual parameter change" cancelLabel="Cancel" confirmLabel="Review change" onCancel={onClose} onConfirm={stage}
    message={<div className="px4-manual-entry"><label>Parameter name<input aria-label="Manual parameter name" value={name} onChange={event => setName(event.target.value.toUpperCase())} /></label>
      <label>Value type<select aria-label="Manual value type" value={type} onChange={event => setType(event.target.value)}><option value="int">Integer</option><option value="float">Float</option><option value="custom">Custom text</option></select></label>
      <label>Proposed value<input type="text" aria-label="Manual proposed value" value={value} onChange={event => setValue(event.target.value)} /></label>
      {componentIds.length > 1 && <label>Component<select value={component} onChange={event => setComponent(event.target.value)}>{componentIds.map(id => <option key={id}>{id}</option>)}</select></label>}
      {error && <p role="alert">{error}</p>}
    </div>} />;
}
