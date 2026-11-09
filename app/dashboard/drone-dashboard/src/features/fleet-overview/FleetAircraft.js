import React, { memo, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { FaBatteryHalf, FaExclamationTriangle, FaTimes } from 'react-icons/fa';
import { AircraftSilhouette } from '../../components/SwarmAircraftSymbol';
import { getFriendlyMissionName } from '../../utilities/missionUtils';
import { DRONE_MISSION_TYPES } from '../../constants/droneConstants';

export function AircraftSymbol() {
  return <svg viewBox="-30 -30 60 60" className="fleet-aircraft-symbol" aria-hidden="true"><AircraftSilhouette nose /></svg>;
}

export const AircraftTile = memo(function AircraftTile({ item, selected, inspected, onToggle, onInspect, list = false }) {
  const issue = item.issues[0];
  return <article className={`fleet-aircraft ${list ? 'fleet-aircraft--row' : ''} ${selected ? 'is-selected' : ''} ${inspected ? 'is-inspected' : ''}`}
    data-aircraft-id={item.id} data-current={item.current}>
    <label className="fleet-aircraft__select"><input type="checkbox" checked={selected} onChange={() => onToggle(item.id)}
      aria-label={`Select ${item.label} · H${item.id}`} /><span className="fleet-visually-hidden">Command target</span></label>
    <button type="button" className="fleet-aircraft__inspect" onClick={() => onInspect(item.id)} aria-label={`Inspect ${item.label} · H${item.id}`}>
      <span className="fleet-aircraft__identity"><strong>{item.label}</strong><small>H{item.id}</small></span>
      <AircraftSymbol />
      <span className="fleet-aircraft__state"><span className={`fleet-link-dot is-${item.current ? 'current' : 'unknown'}`} aria-hidden="true" />
        {item.flightState === 'Unknown' ? 'Flight state unknown' : item.flightState}
        <small>{item.current ? 'Live' : item.runtime.label}</small></span>
      <span className={`fleet-aircraft__battery tone-${item.battery.current ? item.battery.tone : 'muted'}`}>
        <FaBatteryHalf aria-hidden="true" />{item.battery.text}{item.battery.stale && <small>Last known</small>}</span>
      <span className={`fleet-aircraft__issue tone-${issue?.tone || 'neutral'}`}>
        {issue && <><FaExclamationTriangle aria-hidden="true" /><span>{issue.label}</span>{item.issues.length > 1 && <small>+{item.issues.length - 1}</small>}</>}
      </span>
    </button>
  </article>;
});

const MISSION_ROUTES = { [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: '/drone-show',
  [DRONE_MISSION_TYPES.SMART_SWARM]: '/swarm-design', [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: '/custom-show',
  [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: '/swarm-trajectory', [DRONE_MISSION_TYPES.QUICKSCOUT]: '/quickscout' };

export function AircraftInspector({ item, onClose, onMove, onAction }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    if (element.showModal) element.showModal();
    else element.setAttribute('open', '');
    return () => { element.close?.(); if (previous?.isConnected) previous.focus(); };
  }, []);
  const altitude = item.altitude.value;
  const mission = item.raw.mission;
  const missionLabel = getFriendlyMissionName(mission);
  return <dialog ref={dialog} className="fleet-inspector" aria-labelledby="fleet-inspector-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="fleet-inspector__body">
      <header><div><small>AIRCRAFT · H{item.id}{item.raw.pos_id != null ? ` · P${item.raw.pos_id}` : ''}</small><h2 id="fleet-inspector-title">{item.label}</h2></div>
        <button type="button" onClick={onClose} aria-label="Close aircraft details"><FaTimes /></button></header>
      <div className="fleet-inspector__state"><AircraftSymbol /><div><strong>{item.flightState === 'Unknown' ? 'Flight state unknown' : item.flightState}</strong>
        <p>{item.current ? 'Live telemetry' : `${item.runtime.label} · current flight state unavailable`}</p></div></div>
      {item.lastKnown && <p className="fleet-inline-warning">Measurements below are last known, not current.</p>}
      {!!item.issues.length && <ul className="fleet-inspector__issues">{item.issues.map((issue) => <li className={`tone-${issue.tone}`} key={issue.key}><FaExclamationTriangle aria-hidden="true" />{issue.label}</li>)}</ul>}
      <dl className="fleet-inspector__facts">
        <dt>Arming</dt><dd>{item.armed === null ? 'Unknown' : item.armed ? 'Armed' : 'Disarmed'}</dd>
        <dt>Battery</dt><dd>{item.battery.text}{item.battery.stale ? ' · last known' : ''}</dd>
        <dt>Altitude</dt><dd>{altitude == null ? 'Unknown' : `${Number(altitude).toFixed(1)} m ${item.altitude.label}${item.altitude.stale ? ' · last known' : ''}`}</dd>
        <dt>GPS</dt><dd>{item.gps.label}{item.gps.stale ? ' · last known' : ''}</dd>
        <dt>Satellites</dt><dd>{item.gps.satellites ?? 'Unknown'}{item.gps.stale ? ' · last known' : ''}</dd>
        <dt>Position</dt><dd>{item.position.latitude == null ? 'Unavailable' : `${item.position.latitude.toFixed(6)}, ${item.position.longitude.toFixed(6)}${item.position.stale ? ' · last known' : ''}`}</dd>
        <dt>Flight mode</dt><dd>{item.current ? item.raw.flight_mode || 'Unknown' : 'Unknown'}</dd>
        <dt>Observed</dt><dd>{item.runtime.telemetryAgeSec == null ? 'Never seen' : `${item.runtime.telemetryAgeSec}s ago`}</dd>
      </dl>
      {MISSION_ROUTES[mission] && <Link className="fleet-workspace-link" to={MISSION_ROUTES[mission]} onClick={onClose}>{missionLabel || 'Open mission workspace'} →</Link>}
      <section className="fleet-inspector__actions" aria-label={`Actions for ${item.label}`}>
        <button type="button" onClick={() => onAction('HOLD', item)}>Hold</button>
        <button type="button" onClick={() => onAction('LAND', item)}>Land</button>
        <button type="button" onClick={() => onAction('RETURN_RTL', item)}>Return</button>
        <button type="button" disabled={!item.current || item.flightState !== 'Airborne'} onClick={() => onMove(item)}>Move</button>
      </section>
      <details><summary>Diagnostics</summary><dl className="fleet-inspector__facts">
        <dt>HDOP / VDOP</dt><dd>{item.gps.hdop ?? '—'} / {item.gps.vdop ?? '—'}</dd>
        <dt>Link evidence</dt><dd>{item.runtime.tooltip}</dd>
        <dt>Battery source</dt><dd>{item.battery.help}</dd>
        <dt>Companion</dt><dd><Link to="/fleet-ops" onClick={onClose}>Fleet operations →</Link></dd>
      </dl></details>
    </div>
  </dialog>;
}
