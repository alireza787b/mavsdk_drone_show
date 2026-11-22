import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { FaCheck, FaChevronRight, FaRegBell, FaTimes } from 'react-icons/fa';
import { useOptionalFleetAlerts } from './FleetAlertsContext';
import { ALERT_LEVELS, alertScope, distinctAlertConditions } from './fleetAlertPresentation';
import './FleetAlertsPanel.css';

const RECENT_OBSERVATION_MS = 5000;
const EMPTY = [];
const observedTime = new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' });

export function useScopedFleetAlerts(aircraftIds) {
  const context = useOptionalFleetAlerts();
  const state = context?.state;
  const [expiredAt, setExpiredAt] = useState(null);
  const observedAt = state?.observedAtMs;
  useEffect(() => {
    if (!state?.monitoring || observedAt == null) return undefined;
    const timer = setTimeout(() => setExpiredAt(observedAt), Math.max(0, observedAt + RECENT_OBSERVATION_MS - Date.now()));
    return () => clearTimeout(timer);
  }, [observedAt, state?.monitoring]);
  const recent = state?.monitoring && observedAt != null && expiredAt !== observedAt
    && Date.now() - observedAt < RECENT_OBSERVATION_MS;
  const includes = (entry) => !aircraftIds || aircraftIds.includes(entry.aircraftId);
  const active = distinctAlertConditions((state?.active || EMPTY).filter(includes));
  return {
    current: active.filter((entry) => recent && entry.observed),
    lastReported: active.filter((entry) => !recent || !entry.observed),
    cleared: (state?.recent || EMPTY).filter(includes),
    omitted: (state?.omittedAircraft || 0) + (state?.omittedConditions || 0) > 0,
    markSeen: context?.markSeen,
  };
}

function AlertActions({ entry, onInspect, onSeen }) {
  return <div className="fleet-alert-card__actions">
    {onSeen && <button type="button" className="fleet-alert-icon-button" aria-disabled={entry.seen || undefined}
      title={entry.seen ? 'Seen' : 'Mark seen'}
      aria-label={entry.seen ? `Seen: ${entry.aircraftLabel} ${entry.reason}` : `Mark ${entry.aircraftLabel} ${entry.reason} as seen`}
      onClick={() => { if (!entry.seen) onSeen(entry.id); }}><FaCheck aria-hidden="true" /></button>}
    {entry.aircraftId && <Link className="fleet-alert-icon-button" title="Open aircraft"
      to={`/?aircraft=${encodeURIComponent(entry.aircraftId)}`} onClick={onInspect}
      aria-label={`Open aircraft H${entry.aircraftId}`}><FaChevronRight aria-hidden="true" /></Link>}
  </div>;
}

function AircraftLine({ entry, historical }) {
  const stamp = entry.clearedAtMs ?? entry.lastObservedAtMs;
  return <small>{entry.aircraftLabel}{entry.aircraftId && ` · H${entry.aircraftId}`}
    {entry.source && ` · ${entry.source}`}{historical && Number.isFinite(stamp) && ` · ${observedTime.format(stamp)}`}</small>;
}

function AlertGroup({ entries, historical, onInspect, onSeen }) {
  const [expanded, setExpanded] = useState(false);
  const entry = entries[0];
  const [, , Icon] = ALERT_LEVELS.find(([tone]) => tone === entry.tone);
  const differentAircraft = entry.aircraftId && new Set(entries.map((item) => item.aircraftId)).size === entries.length;
  const countLabel = `${entries.length} ${differentAircraft ? 'aircraft' : 'reports'}`;
  return entries.length === 1
    ? <li className="fleet-alert-card">
      <Icon className={`fleet-alert-card__severity tone-${entry.tone}`} aria-hidden="true" />
      <div className="fleet-alert-card__copy"><strong>{entry.reason}</strong><AircraftLine entry={entry} historical={historical} /></div>
      <AlertActions entry={entry} onInspect={onInspect} onSeen={onSeen} />
    </li>
    : <li className="fleet-alert-card fleet-alert-card--group">
      <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>
          <Icon className={`fleet-alert-card__severity tone-${entry.tone}`} aria-hidden="true" />
          <span className="fleet-alert-card__copy"><strong>{entry.reason}</strong>
            <small>{countLabel}{entry.source && ` · ${entry.source}`}</small></span>
          <FaChevronRight className="fleet-alert-chevron" aria-hidden="true" />
        </summary>
        {expanded && <ul className="fleet-alert-card__aircraft">
          {entries.map((aircraft) => <li key={aircraft.id}><AircraftLine entry={aircraft} historical={historical} />
            <AlertActions entry={aircraft} onInspect={onInspect} onSeen={onSeen} /></li>)}
        </ul>}
      </details>
    </li>;
}

function FleetAlertList({ entries, label, historical, onInspect, onSeen }) {
  const groups = new Map();
  for (const entry of entries) {
    const key = JSON.stringify([entry.tone, entry.source, entry.reason, entry.aircraftId === null]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(entry);
  }
  return <ul className="fleet-alert-list" aria-label={label}>
    {[...groups].map(([key, group]) => <AlertGroup key={key} entries={group} historical={historical}
      onInspect={onInspect} onSeen={onSeen} />)}
  </ul>;
}

function AlertHistory({ entries, title, open, onInspect }) {
  if (!entries.length) return null;
  return <details className="fleet-alert-history" open={open || undefined}>
    <summary><FaChevronRight className="fleet-alert-chevron" aria-hidden="true" />{title}<small>{entries.length}</small></summary>
    <FleetAlertList entries={entries} label={`${title} alerts`} historical onInspect={onInspect} />
  </details>;
}

function AlertsDialog({ alerts, initialTone, dialogId, trigger, restoreTo, onClose }) {
  const ref = useRef(null);
  const returnFocus = useRef(true);
  const titleId = useId();
  const [selected, setSelected] = useState(initialTone);
  useEffect(() => {
    const dialog = ref.current;
    const controls = restoreTo.current;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector('[data-close-alerts]')?.focus();
    return () => {
      dialog.close?.();
      if (returnFocus.current) (trigger?.isConnected ? trigger : controls?.querySelector('button'))?.focus();
    };
  }, [trigger, restoreTo]);
  const inspect = () => { returnFocus.current = false; onClose(); };
  const current = alertScope(alerts.current, selected);
  const lastReported = alertScope(alerts.lastReported, selected);
  const cleared = alertScope(alerts.cleared, selected);
  return <dialog ref={ref} id={dialogId} className="fleet-alerts__dialog" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="fleet-alerts__frame">
      <header className="fleet-alerts__header"><h2 id={titleId}>Fleet alerts</h2>
        <button type="button" data-close-alerts className="fleet-alert-icon-button" aria-label="Close fleet alerts"
          onClick={onClose}><FaTimes aria-hidden="true" /></button></header>
      <div className="fleet-alerts__filters" role="group" aria-label="Alert severity">
        {ALERT_LEVELS.map(([tone, label, Icon]) => <button key={tone} type="button"
          className={`tone-${tone}`} aria-pressed={selected === tone}
          onClick={() => setSelected(selected === tone ? 'all' : tone)}>
          <Icon aria-hidden="true" />{label === 'Warning' ? 'Warnings' : 'Cautions'}
          <span>{alerts.current.filter((entry) => entry.tone === tone).length}</span>
        </button>)}
      </div>
      <div className="fleet-alerts__body">
        {current.length ? <FleetAlertList entries={current} label="Current alerts" onInspect={inspect} onSeen={alerts.markSeen} />
          : <p className="fleet-alerts__empty">No current {selected === 'danger' ? 'warnings' : selected === 'warning' ? 'cautions' : 'alerts'}</p>}
        <AlertHistory title="Last reported" entries={lastReported} open={!current.length} onInspect={inspect} />
        <AlertHistory title="Recently cleared" entries={cleared} onInspect={inspect} />
        {alerts.omitted && <p className="fleet-alerts__empty">More conditions in Aircraft Details</p>}
      </div>
    </div>
  </dialog>;
}

export default function FleetAlertsPanel({ className = '' }) {
  const alerts = useScopedFleetAlerts();
  const [open, setOpen] = useState(null);
  const dialogId = useId();
  const triggers = useRef(null);
  return <div className={`fleet-alerts alert-annunciators ${className}`} ref={triggers}>
    {ALERT_LEVELS.map(([tone, label, Icon]) => {
      const count = alerts.current.filter((entry) => entry.tone === tone).length;
      if (!count && open?.tone !== tone) return null;
      return <button key={tone} type="button" className={`alert-annunciator tone-${tone}`}
        aria-label={`${label}: ${count}`} title={`${label}: ${count}`} aria-haspopup="dialog"
        aria-expanded={open?.tone === tone} aria-controls={open?.tone === tone ? dialogId : undefined}
        onClick={(event) => setOpen({ tone, trigger: event.currentTarget })}>
        <Icon aria-hidden="true" /><span aria-hidden="true">{count}</span>
      </button>;
    })}
    {(!alerts.current.length || open?.tone === 'all') && <button type="button" className="alert-annunciator"
      aria-label="Alerts" title="Alerts" aria-haspopup="dialog" aria-expanded={open?.tone === 'all'}
      aria-controls={open?.tone === 'all' ? dialogId : undefined}
      onClick={(event) => setOpen({ tone: 'all', trigger: event.currentTarget })}><FaRegBell aria-hidden="true" /></button>}
    {open && createPortal(<AlertsDialog alerts={alerts} initialTone={open.tone} trigger={open.trigger}
      restoreTo={triggers} dialogId={dialogId} onClose={() => setOpen(null)} />, document.body)}
  </div>;
}
