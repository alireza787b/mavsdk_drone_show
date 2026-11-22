import React, { useId, useRef, useState } from 'react';
import { FaExclamationCircle, FaExclamationTriangle, FaRegBell } from 'react-icons/fa';
import './FleetAlertsPanel.css';

const LEVELS = [
  ['danger', 'Warning', FaExclamationCircle],
  ['warning', 'Caution', FaExclamationTriangle],
];

export function alertCondition(aircraftId, aircraftLabel, reason, { tone = 'warning', source = 'MDS', detail } = {}) {
  return { aircraftId, aircraftLabel, reason, tone, source, detail };
}

export function distinctAlertConditions(entries) {
  const distinct = new Map();
  entries.forEach((entry) => {
    const reason = typeof entry.reason === 'string' ? entry.reason.trim() : '';
    if (!reason) return;
    const key = JSON.stringify([entry.aircraftId, reason.replace(/\s+/g, ' ').toLowerCase()]);
    const previous = distinct.get(key);
    if (!previous || (entry.observed !== false && previous.observed === false)
      || ((entry.observed === false) === (previous.observed === false)
        && entry.tone === 'danger' && previous.tone !== 'danger')) {
      distinct.set(key, { ...entry, reason, displayKey: key });
    }
  });
  return [...distinct.values()].sort((a, b) => Number(b.tone === 'danger') - Number(a.tone === 'danger'));
}

export function AlertButtons({ current, onOpen, selected, hasHistory, popup, controls }) {
  const counts = LEVELS.map(([tone]) => current.filter((entry) => entry.tone === tone).length);
  return <div className="alert-annunciators">
    {LEVELS.map(([tone, label, Icon], index) => counts[index] > 0 && <button key={tone} type="button"
      className={`alert-annunciator tone-${tone}`} aria-label={`${label}: ${counts[index]}`}
      title={`${label}: ${counts[index]}`} aria-expanded={selected === tone} aria-haspopup={popup}
      aria-controls={selected === tone ? controls : undefined} onClick={(event) => onOpen(tone, event.currentTarget)}>
      <Icon aria-hidden="true" /><span aria-hidden="true">{counts[index]}</span>
    </button>)}
    {!counts.some(Boolean) && hasHistory && <button type="button" className="alert-annunciator"
      aria-label="Alerts" title="Alerts" aria-expanded={selected === 'all'} aria-haspopup={popup}
      aria-controls={selected === 'all' ? controls : undefined} onClick={(event) => onOpen('all', event.currentTarget)}>
      <FaRegBell aria-hidden="true" />
    </button>}
  </div>;
}

export function AlertRows({ entries, label, renderActions, renderMeta }) {
  return <ul className="alert-deck__rows" aria-label={label}>
    {distinctAlertConditions(entries).map((entry) => {
      const Icon = entry.tone === 'danger' ? FaExclamationCircle : FaExclamationTriangle;
      return <li className={`alert-deck__row tone-${entry.tone}`} key={entry.displayKey}>
        <Icon aria-hidden="true" />
        <div><span><strong>{entry.aircraftLabel}</strong> · {entry.reason}</span>
          <small>{[entry.source, renderMeta?.(entry)].filter(Boolean).join(' · ')}</small>
          {entry.detail && entry.detail !== entry.reason && <small>{entry.detail}</small>}
        </div>
        {renderActions?.(entry)}
      </li>;
    })}
  </ul>;
}

export function alertScope(entries, selected) {
  return selected === 'all' ? entries : entries.filter((entry) => entry.tone === selected);
}

export function InlineAlerts({ entries, lastReported = [], label = 'Aircraft alerts' }) {
  const [selected, setSelected] = useState(null);
  const trigger = useRef(null);
  const panelId = useId();
  const titleId = useId();
  const current = distinctAlertConditions(entries);
  const open = (tone, button) => { trigger.current = button; setSelected(tone === selected ? null : tone); };
  const close = () => { setSelected(null); trigger.current?.focus(); };
  if (!selected && !current.length && !lastReported.length) return null;
  const visible = alertScope(current, selected);
  const visibleHistory = lastReported;
  return <div className="alert-deck alert-deck--inline" onKeyDown={(event) => {
    if (event.key === 'Escape' && selected) { event.stopPropagation(); close(); }
  }}>
    <AlertButtons current={current} hasHistory={lastReported.length > 0} selected={selected} onOpen={open} controls={panelId} />
    {selected && <section id={panelId} aria-labelledby={titleId} className="alert-deck__sheet">
      <header><h3 id={titleId}>{label}</h3><button type="button" aria-label="Close alert details" onClick={close}>×</button></header>
      {visible.length ? <AlertRows entries={visible} label="Current alerts" /> : <p>No current alerts in this category.</p>}
      {!!visibleHistory.length && <details><summary>Last reported</summary><AlertRows entries={visibleHistory} label="Last reported alerts" /></details>}
    </section>}
  </div>;
}
