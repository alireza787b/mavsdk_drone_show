import React, { useEffect, useId, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Link } from 'react-router-dom';
import { useOptionalFleetAlerts } from './FleetAlertsContext';
import { AlertButtons, AlertRows, alertScope, distinctAlertConditions } from './AlertAnnunciators';

const RECENT_OBSERVATION_MS = 5000;
const EMPTY = [];

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

function AlertsDialog({ alerts, selected, onClose, dialogId, trigger }) {
  const ref = useRef(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (dialog.showModal) dialog.showModal();
    else dialog.setAttribute('open', '');
    dialog.querySelector('button')?.focus();
    return () => { dialog.close?.(); (trigger?.isConnected ? trigger : document.querySelector('.fleet-alerts button'))?.focus(); };
  }, [trigger]);
  const current = alertScope(alerts.current, selected);
  const actions = (episode) => <div className="fleet-alerts__entry-actions">
    {episode.aircraftId && <Link to={`/?aircraft=${encodeURIComponent(episode.aircraftId)}`} onClick={onClose}
      aria-label={`Open aircraft H${episode.aircraftId}`}>Aircraft</Link>}
    {episode.seen ? <small>Seen</small> : <button type="button"
      aria-label={`Mark ${episode.aircraftLabel} ${episode.reason} as seen`} onClick={() => alerts.markSeen?.(episode.id)}>Mark seen</button>}
  </div>;
  return <dialog ref={ref} id={dialogId} className="fleet-alerts__dialog" aria-labelledby={titleId}
    onCancel={(event) => { event.preventDefault(); onClose(); }}
    onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <header><h2 id={titleId}>{selected === 'danger' ? 'Warnings' : selected === 'warning' ? 'Cautions' : 'Fleet alerts'}</h2>
      <button type="button" onClick={onClose} aria-label="Close fleet alerts">×</button></header>
    {!!current.length && <AlertRows entries={current} label="Current alerts" renderActions={actions} />}
    {!current.length && <p>No current alerts in this view.</p>}
    {!!alerts.lastReported.length && <details open={!current.length || undefined}><summary>Last reported</summary>
      <AlertRows entries={alerts.lastReported} label="Last reported alerts" /></details>}
    {alerts.omitted && <p>More conditions in aircraft details.</p>}
    {!!alerts.cleared.length && <details><summary>Recently cleared</summary>
      <AlertRows entries={alerts.cleared} label="Recently cleared alerts" /></details>}
  </dialog>;
}

export default function FleetAlertsPanel({ className = '' }) {
  const alerts = useScopedFleetAlerts();
  const [open, setOpen] = useState(null);
  const dialogId = useId();
  return <div className={`fleet-alerts ${className}`}>
    <AlertButtons current={alerts.current} hasHistory selected={open?.tone} popup="dialog" controls={dialogId}
      onOpen={(tone, trigger) => setOpen({ tone, trigger })} />
    {open && createPortal(<AlertsDialog alerts={alerts} selected={open.tone} trigger={open.trigger}
      dialogId={dialogId} onClose={() => setOpen(null)} />, document.body)}
  </div>;
}
