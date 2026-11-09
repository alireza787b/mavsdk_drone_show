import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { FaExclamationTriangle } from 'react-icons/fa';
import { useFleetAlerts } from './FleetAlertsContext';
import './FleetAlertsPanel.css';

const RECENT_OBSERVATION_MS = 5000;
function ageLabel(timestamp, now) {
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
  return seconds < 60 ? `${seconds}s ago` : `${Math.floor(seconds / 60)}m ago`;
}

function AlertsDialog({ state, markSeen, onClose }) {
  const ref = useRef(null);
  const titleId = useId();
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const previous = document.activeElement;
    const element = ref.current;
    if (element.showModal) element.showModal();
    else element.setAttribute('open', '');
    element.querySelector('button')?.focus();
    // Presentation clock only; does not fetch, refresh evidence or grant authority.
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(timer); element.close?.(); if (previous?.isConnected) previous.focus(); };
  }, []);
  const recentObservation = state.monitoring && state.observedAtMs !== null && now - state.observedAtMs <= RECENT_OBSERVATION_MS;
  const current = recentObservation ? state.active.filter((episode) => episode.observed) : [];
  const currentIds = new Set(current.map((episode) => episode.id));
  const lastObserved = state.active.filter((episode) => !currentIds.has(episode.id));
  const entry = (episode, cleared = false) => <li key={episode.id} className={`fleet-alerts__entry tone-${episode.tone}`}>
    <div><strong>{episode.aircraftLabel}{episode.aircraftId && ` · H${episode.aircraftId}`}</strong>
      <span>{episode.reason}</span>
      <small>{cleared ? 'Clear observed' : 'Last observed'} {ageLabel(cleared ? episode.clearedAtMs : episode.lastObservedAtMs, now)}</small></div>
    <div className="fleet-alerts__entry-actions">
      {episode.aircraftId && <Link to={`/?aircraft=${encodeURIComponent(episode.aircraftId)}`} onClick={onClose} aria-label={`Open aircraft H${episode.aircraftId}`}>Open aircraft</Link>}
      {!cleared && (episode.seen ? <span>Seen</span> : <button type="button" aria-label={`Mark ${episode.aircraftLabel} ${episode.reason} as seen`} onClick={() => markSeen(episode.id)}>Mark seen</button>)}
    </div>
  </li>;
  return <dialog ref={ref} className="fleet-alerts__dialog" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <header><h2 id={titleId}>Fleet alerts</h2><button type="button" onClick={onClose} aria-label="Close fleet alerts">×</button></header>
    <p className="fleet-alerts__scope">Session alerts · Seen does not clear a condition.</p>
    {!recentObservation && state.observedAtMs !== null && <p>Last observed {ageLabel(state.observedAtMs, now)} · not live.</p>}
    {state.sourceError && <p>{recentObservation
      ? 'Telemetry source unavailable · aircraft updates paused.'
      : 'Last observed: telemetry source unavailable.'}</p>}
    {!!(state.omittedAircraft || state.omittedConditions) && <p>{state.omittedAircraft} additional aircraft and {state.omittedConditions} conditions omitted from this bounded view.</p>}
    {current.length > 0 && <section><h3>Observed conditions</h3><ul aria-label="Observed conditions">{current.map((episode) => entry(episode))}</ul></section>}
    {lastObserved.length > 0 && <section><h3>Last observed · not current</h3><ul aria-label="Last-observed conditions">{lastObserved.map((episode) => entry(episode))}</ul></section>}
    {!state.active.length && <p>{recentObservation && !state.sourceError ? 'No conditions reported in the latest Overview observation.' : 'No conditions recorded in this session.'}</p>}
    {state.recent.length > 0 && <details><summary>Recently cleared · {state.recent.length}</summary><ul aria-label="Recently cleared conditions">{state.recent.map((episode) => entry(episode, true))}</ul></details>}
  </dialog>;
}

export default function FleetAlertsPanel({ className = '' }) {
  const { state, markSeen } = useFleetAlerts();
  const [open, setOpen] = useState(false);
  // A GCS outage is one alert, never 100 derived aircraft-loss notifications.
  const count = state.sourceError ? state.active.filter((episode) => episode.aircraftId === null).length : state.active.length;
  return <div className={`fleet-alerts ${className}`}>
    <button type="button" className={`fleet-alerts__trigger ${count ? 'has-alerts' : ''}`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      {count > 0 && <FaExclamationTriangle aria-hidden="true" />}<span>Alerts</span>{count > 0 && <span>{count}</span>}
      {!state.monitoring && state.observedAtMs !== null && <small>Last observed</small>}
    </button>
    {open && createPortal(<AlertsDialog state={state} markSeen={markSeen} onClose={() => setOpen(false)} />, document.body)}
  </div>;
}
