import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { FaCheck, FaChevronRight, FaClipboardList, FaRegClock, FaTimes } from 'react-icons/fa';
import { useOptionalFleetAlerts } from './FleetAlertsContext';
import { ALERT_LEVELS, distinctAlertConditions } from './fleetAlertPresentation';
import { useCommandActivity } from '../../contexts/CommandActivityContext';
import MemoCommands, { commandStage, commandTime } from './MemoCommands';
import './FleetMemo.css';

const RECENT_OBSERVATION_MS = 5000;
const EMPTY = [];
function alertTitle(entry) {
  return entry.source === 'MDS' ? entry.reason.replace(/^MDS observation: /, '') : entry.reason;
}

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
      title={entry.seen ? 'Seen' : 'Acknowledge'}
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
      <div className="fleet-alert-card__copy"><strong>{alertTitle(entry)}</strong><AircraftLine entry={entry} historical={historical} /></div>
      <AlertActions entry={entry} onInspect={onInspect} onSeen={onSeen} />
    </li>
    : <li className="fleet-alert-card fleet-alert-card--group">
      <details onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>
          <Icon className={`fleet-alert-card__severity tone-${entry.tone}`} aria-hidden="true" />
          <span className="fleet-alert-card__copy"><strong>{alertTitle(entry)}</strong>
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

function MemoDialog({ alerts, commands, history, reviewCount, clearResolved, dialogId, trigger, onClose }) {
  const ref = useRef(null);
  const returnFocus = useRef(true);
  const titleId = useId();
  const [page, setPage] = useState('live');
  const [showLastReported, setShowLastReported] = useState(false);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector('[data-close-alerts]')?.focus();
    return () => {
      dialog.close?.();
      if (returnFocus.current) trigger?.focus();
    };
  }, [trigger]);
  const inspect = () => { returnFocus.current = false; onClose(); };
  return <dialog ref={ref} id={dialogId} className="fleet-alerts__dialog" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="fleet-alerts__frame">
      <header className="fleet-alerts__header"><h2 id={titleId}>Memo</h2>
        <button type="button" data-close-alerts className="fleet-alert-icon-button" aria-label="Close Memo"
          onClick={onClose}><FaTimes aria-hidden="true" /></button></header>
      <div className="fleet-alerts__filters" role="group" aria-label="Memo views">
        <button type="button" aria-pressed={page === 'live'} onClick={() => { setShowLastReported(false); setPage('live'); }}>
          Live
        </button>
        <button type="button" aria-pressed={page === 'history'} onClick={() => setPage('history')}>
          History {reviewCount || ''}
        </button>
      </div>
      <div className="fleet-alerts__body">
        {page === 'live' ? <>
          {alerts.current.length > 0 && <FleetAlertList entries={alerts.current} label="Current alerts" onInspect={inspect} onSeen={alerts.markSeen} />}
          <MemoCommands commands={commands} label="Active commands" onInspect={inspect} />
          {!alerts.current.length && !commands.length && <p className="fleet-alerts__empty">
            {alerts.lastReported.length ? <>
              Status unconfirmed{' '}
              <button type="button" className="fleet-memo__clear" onClick={() => { setShowLastReported(true); setPage('history'); }}>View last reported</button>
            </> : 'Nothing needs attention'}
          </p>}
          {alerts.omitted && <p className="fleet-alerts__empty">More conditions in Aircraft Details</p>}
        </> : <>
          <button type="button" className="fleet-memo__clear" aria-disabled={!reviewCount || undefined}
            onClick={() => { if (reviewCount) clearResolved(); }}><FaCheck aria-hidden="true" /> Clear resolved</button>
          <AlertHistory title="Resolved" entries={alerts.cleared} open onInspect={inspect} />
          <AlertHistory title="Last reported" entries={alerts.lastReported} open={showLastReported} onInspect={inspect} />
          <MemoCommands commands={history} label="Command history" onInspect={inspect} />
          {!alerts.cleared.length && !alerts.lastReported.length && !history.length
            && <p className="fleet-alerts__empty">No recent history</p>}
        </>}
      </div>
    </div>
  </dialog>;
}

const MAX_REVIEWED = 200;

function readReview(key) {
  try {
    const value = key && JSON.parse(localStorage.getItem(key));
    if (Array.isArray(value)) return new Set(value.filter(id => typeof id === 'string').slice(-MAX_REVIEWED));
  } catch (_) { /* The review count can remain local to this session. */ }
  return new Set();
}

export default function FleetMemo({ scope }) {
  const alerts = useScopedFleetAlerts();
  const { commandMonitors = [], commandHistory = [], activeObservation } = useCommandActivity();
  const archivedIds = new Set(commandHistory.map(command => command.commandId));
  const observed = new Map((activeObservation?.snapshots || []).map(command => [command.commandId, command]));
  const historical = [];
  for (const command of commandMonitors) {
    if (archivedIds.has(command.commandId)) continue;
    const existing = observed.get(command.commandId);
    if (command.isTerminal) {
      observed.delete(command.commandId);
      historical.push(command);
    } else if (command.trackingIssue) {
      if (!existing) historical.push(command);
    } else if (existing || !activeObservation || commandTime(command) > activeObservation.receivedAtMs) {
      if (!existing || commandTime(command) >= commandTime(existing)) observed.set(command.commandId, command);
    } else historical.push({ ...command, trackingIssue: 'last_reported' });
  }
  const commands = [...observed.values()].filter(command => !command.isTerminal && !archivedIds.has(command.commandId))
    .sort((a, b) => commandTime(b) - commandTime(a));
  const history = [...commandHistory, ...historical].sort((a, b) => commandTime(b) - commandTime(a));
  const key = scope && `${scope}:memo-review`;
  const [review, setReview] = useState(() => readReview(key));
  const resolvedIds = [
    ...alerts.cleared.map(entry => `alert:${entry.id}`),
    ...history.filter(command => command.isTerminal).map(command => `command:${command.commandId}`),
  ];
  const reviewCount = resolvedIds.filter(id => !review.has(id)).length;
  const clearResolved = () => {
    const next = new Set([...review, ...resolvedIds].slice(-MAX_REVIEWED));
    setReview(next);
    try { if (key) localStorage.setItem(key, JSON.stringify([...next])); } catch (_) { /* Keep this session's review state. */ }
  };
  const [open, setOpen] = useState(false);
  const dialogId = useId();
  const summaryId = useId();
  const trigger = useRef(null);
  const counts = { danger: 0, warning: 0 };
  alerts.current.forEach(entry => { counts[entry.tone]++; });
  const leading = alerts.current.length ? alertTitle(alerts.current[0]) : commands.length
    ? `${commands[0].commandLabel} · ${commandStage(commands[0])}`
    : alerts.lastReported.length ? 'Status unconfirmed' : 'Nothing needs attention';
  return <div className="fleet-memo">
    <button ref={trigger} type="button" className="fleet-memo__trigger" aria-label="Memo" aria-describedby={summaryId}
      aria-expanded={open} aria-haspopup="dialog" aria-controls={open ? dialogId : undefined} onClick={() => setOpen(true)}>
      <FaClipboardList aria-hidden="true" /><strong>Memo</strong>
      {ALERT_LEVELS.map(([tone, label, Icon]) => counts[tone] > 0 && <span key={tone}
        title={`${label}: ${counts[tone]}`} className={`fleet-memo__count tone-${tone}`}>
        <Icon aria-hidden="true" /><span>{counts[tone]}</span></span>)}
      {!!commands.length && <span className="fleet-memo__count" title={`Active commands: ${commands.length}`}>
        <FaRegClock aria-hidden="true" />{commands.length}</span>}
      <span className="fleet-memo__leading">{leading}</span>
      <FaChevronRight className="fleet-memo__chevron" aria-hidden="true" />
    </button>
    <span id={summaryId} className="fleet-visually-hidden">
      {counts.danger} warnings, {counts.warning} cautions, {commands.length} active commands.
    </span>
    {open && createPortal(<MemoDialog alerts={alerts} commands={commands} history={history} reviewCount={reviewCount}
      clearResolved={clearResolved} trigger={trigger.current} dialogId={dialogId}
      onClose={() => setOpen(false)} />, document.body)}
  </div>;
}
