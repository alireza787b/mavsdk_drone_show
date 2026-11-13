import React, { memo, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { FaExclamationTriangle, FaExclamationCircle, FaCheck, FaHourglassHalf, FaRegClock, FaUnlink, FaInfoCircle, FaTimes, FaBatteryHalf, FaArrowsAltV, FaSatellite, FaBroadcastTower, FaRoute, FaQuestionCircle, FaWifi, FaEthernet, FaUsb, FaPaperPlane } from 'react-icons/fa';
import { DRONE_MISSION_TYPES } from '../../constants/droneConstants';
import { normalizeRuntimeIp } from '../../utilities/missionIdentityUtils';

export function AircraftSymbol({ item }) {
  const state = ({ Grounded: 'grounded', Airborne: 'airborne', 'Taking off': 'taking-off', Landing: 'landing' })[item?.flightState] || 'unknown';
  return <svg viewBox="0 0 24 24" className={`fleet-aircraft-symbol fleet-state-symbol is-${state}`} data-state={state} aria-hidden="true">
    {state === 'unknown' ? <><path d="M5 5h14v14H5z" strokeDasharray="3 2" /><path d="M10 9a2 2 0 0 1 4 0c0 2-2 2-2 4M12 16v1" /></>
      : state === 'grounded' ? <><circle cx="12" cy="10" r="4" /><path d="M5 19h14M8 15v4M16 15v4" /></>
        : state === 'airborne' ? <path d="m12 3 8 15-8-4-8 4z" />
          : state === 'taking-off' ? <><path d="M12 18V4m-5 5 5-5 5 5M5 21h14" /></>
            : <path d="M12 3v14m-5-5 5 5 5-5M5 21h14" />}
  </svg>;
}

/** Front-profile schematic: intentionally does not depict a rotor count or heading. */
function AircraftPortrait({ item }) {
  const conditions = item.issues.filter((issue) => ['danger', 'warning'].includes(issue.tone));
  const warning = conditions.some((issue) => issue.tone === 'danger');
  const AlertIcon = warning ? FaExclamationCircle : FaExclamationTriangle;
  // Flight phase, runtime/link evidence and aircraft conditions occupy distinct
  // fixed slots. None changes command selection or acknowledges an alert.
  const status = !item.current && item.runtime.indicatorClass === 'lost'
    ? { key: 'lost', Icon: FaUnlink, label: 'Link lost', tone: 'warning' }
    : item.availability.label === 'Offline'
      ? { key: 'offline', Icon: FaUnlink, label: 'Heartbeat offline', tone: 'muted' }
    : !item.current && item.boot.active
      ? { key: 'initializing', Icon: FaHourglassHalf, label: 'Initializing', tone: 'warning' }
    : item.availability.stale
      ? { key: 'stale', Icon: FaRegClock, label: 'Heartbeat stale', tone: 'warning' }
      : !item.current && item.availability.available
          ? { key: 'delayed', Icon: FaRegClock, label: 'Flight telemetry unavailable', tone: 'warning' }
          : item.current && item.flightState === 'Grounded' && item.readiness.status === 'ready'
            ? { key: 'ready', Icon: FaCheck, label: 'Preflight ready', tone: 'good' } : null;
  const StatusIcon = status?.Icon;
  return <span className="fleet-aircraft__portrait" data-state={item.flightState.toLowerCase()}>
    <svg className="fleet-aircraft__schematic" viewBox="0 0 96 80" aria-hidden="true">
      <g className="fleet-aircraft__airframe">
        <path d="m17 34 18 8m26 0 18-8M17 27v8m62-8v8" />
        <ellipse cx="17" cy="23" rx="14" ry="3" /><ellipse cx="79" cy="23" rx="14" ry="3" />
        <path className="fleet-aircraft__body" d="m37 33 22 0 7 12-8 9H38l-8-9z" />
        <path d="m39 54-5 11H23m34-11 5 11h11M42 40h12" />
      </g>
    </svg>
    {status && <span className={`fleet-aircraft__status-badge tone-${status.tone}`} data-status={status.key} title={status.label} aria-label={status.label}>
      <StatusIcon aria-hidden="true" />
    </span>}
    {conditions.length > 0 && <span className={`fleet-aircraft__alert-badge tone-${warning ? 'danger' : 'warning'}`}
      title={`${conditions.length} aircraft conditions · ${warning ? 'warning' : 'caution'} · open aircraft details`}
      aria-label={`${warning ? 'Warning' : 'Caution'}: ${conditions.length} aircraft conditions`}>
      <AlertIcon aria-hidden="true" /><small>{conditions.length}</small>
    </span>}
    <span className="fleet-aircraft__phase-marker"><AircraftSymbol item={item} /></span>
  </span>;
}

const METRIC_ICONS = { battery: FaBatteryHalf, altitude: FaArrowsAltV, gnss: FaSatellite, link: FaBroadcastTower, mission: FaRoute };
const NETWORK_ICONS = { wifi: FaWifi, ethernet: FaEthernet, usb_modem: FaUsb };
function Metric({ kind, label, value, displayValue = value, stale = false, tone = '', icon }) {
  const Icon = icon || METRIC_ICONS[kind];
  const presentation = displayValue === 'Unknown' ? '—' : displayValue;
  return <span className={`fleet-aircraft__metric fleet-aircraft__metric--${kind}${tone ? ` tone-${tone}` : ''}`}
    title={`${kind === 'link' ? 'Heartbeat age / reported signal' : label}: ${value}${stale ? ' · Last known' : ''}`} aria-label={`${label}: ${value}${stale ? ', Last known' : ''}`}>
    <span>{Icon && <Icon aria-hidden="true" />}<span>{presentation}</span></span>{stale && <em>Last known</em>}
  </span>;
}

function altitudeText(altitude) {
  return altitude.value == null ? 'Unknown' : `${Number(altitude.value).toFixed(1)} m ${altitude.label}`;
}

function compactAltitude(altitude) {
  if (altitude.value == null) return '—';
  const value = Number(altitude.value);
  return `${Math.abs(value) >= 100 ? Math.round(value) : Number(value.toFixed(1))} m ${altitude.label}`;
}

function heartbeatText(availability) {
  return availability.ageSec == null ? 'Unknown' : `${availability.label} · ${Math.round(availability.ageSec)}s`;
}

export const AircraftTile = memo(function AircraftTile({ item, selected, inspected, onInspect, list = false }) {
  const issue = item.issues[0];
  return <article className={`fleet-aircraft ${list ? 'fleet-aircraft--row' : ''} ${selected ? 'is-selected' : ''} ${inspected ? 'is-inspected' : ''} ${item.availability.stale || item.availability.label === 'Offline' ? 'is-stale' : ''}`}
    data-aircraft-id={item.id} data-current={item.current} data-flight-state={item.flightState.toLowerCase()} data-readiness={item.readiness.status} data-availability={item.availability.label.toLowerCase()}>
    {selected && <span className="fleet-aircraft__recipient" aria-label={`Command recipient: ${item.label} · H${item.id}`}
      title="Included in command recipients"><FaPaperPlane aria-hidden="true" /></span>}
    <button type="button" className="fleet-aircraft__inspect" onClick={() => onInspect(item.id)} aria-label={`Inspect ${item.label} · H${item.id}`}>
      <span className="fleet-aircraft__identity"><span><strong>{item.label}</strong><small>H{item.id}{item.identity.posId ? ` · P${item.identity.posId}` : ''}</small></span>
        <FaInfoCircle className="fleet-aircraft__info" aria-hidden="true" /></span>
      <span className="fleet-aircraft__instruments">
        <Metric kind="battery" label="Battery" value={item.battery.text}
          displayValue={item.battery.remaining !== null ? `${Math.round(item.battery.remaining)}%` : item.battery.text} stale={item.battery.stale} tone={item.battery.current ? item.battery.tone : 'muted'} />
        <AircraftPortrait item={item} />
        <Metric kind="gnss" label="GNSS" value={`${item.gps.label} · ${item.gps.satellites ?? '—'} sats`}
          displayValue={item.gps.label} stale={item.gps.stale} />
        <Metric kind="altitude" label="Altitude" value={altitudeText(item.altitude)} displayValue={compactAltitude(item.altitude)} stale={item.altitude.stale} />
        <Metric kind="link" label="Link" value={`${heartbeatText(item.availability)}${item.network.current ? ` · ${item.network.label}${item.network.percent !== null ? ` ${Math.round(item.network.percent)}%` : ''}` : ''}`}
          displayValue={item.network.percent !== null ? `${Math.round(item.network.percent)}%` : null}
          icon={item.availability.label === 'Fresh' ? NETWORK_ICONS[item.network.type] || FaBroadcastTower : item.availability.stale ? FaRegClock : item.availability.label === 'Offline' ? FaUnlink : FaQuestionCircle}
          tone={item.availability.tone} />
      </span>
      <span className="fleet-aircraft__state">
        {item.flightState === 'Unknown' ? 'Flight state unknown' : item.flightState}
        <small className="fleet-aircraft__mode" aria-label={`Flight mode: ${item.flightMode.label}${item.flightMode.stale ? ', Last known' : ''}`}>
          {item.flightMode.label}{item.flightMode.stale ? ' · Last known' : ''}</small>
        {item.flightState === 'Grounded' && <small className={`fleet-aircraft__readiness is-${item.readiness.status}`}>
          {item.readiness.status === 'warning' ? 'Check' : item.readiness.label}</small>}</span>
      {item.mission.known && item.mission.value !== DRONE_MISSION_TYPES.NONE && <Metric kind="mission" label="Mission" value={item.mission.label} stale={item.mission.stale} />}
      <span className={`fleet-aircraft__issue tone-${issue?.tone || 'neutral'}`}>
        {issue && <><FaExclamationTriangle aria-hidden="true" /><span>{issue.label}</span>{item.issues.length > 1 && <small>+{item.issues.length - 1}</small>}</>}
      </span>
    </button>
  </article>;
});

const MISSION_ROUTES = { [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: '/drone-show',
  [DRONE_MISSION_TYPES.SMART_SWARM]: '/swarm-design', [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: '/custom-show',
  [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: '/swarm-trajectory', [DRONE_MISSION_TYPES.QUICKSCOUT]: '/quickscout' };

export function AircraftInspector({ item, onClose, onMove, onAction, onMore }) {
  const dialog = useRef(null);
  const NetworkIcon = NETWORK_ICONS[item.network.type] || FaBroadcastTower;
  useEffect(() => {
    const element = dialog.current;
    const previous = document.activeElement;
    if (element.showModal) element.showModal();
    else element.setAttribute('open', '');
    return () => { element.close?.(); if (previous?.isConnected) previous.focus(); };
  }, []);
  const mission = item.mission.value;
  return <dialog ref={dialog} className="fleet-inspector" aria-labelledby="fleet-inspector-title"
    onCancel={(event) => { event.preventDefault(); onClose(); }} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="fleet-inspector__body">
      <header><div><small>AIRCRAFT · H{item.id}{item.raw.pos_id != null ? ` · P${item.raw.pos_id}` : ''}</small><h2 id="fleet-inspector-title">{item.label}</h2></div>
        <button type="button" onClick={onClose} aria-label="Close aircraft details"><FaTimes /></button></header>
      <div className="fleet-inspector__state"><AircraftSymbol item={item} /><div><strong>{item.flightState === 'Unknown' ? 'Flight state unknown' : item.flightState}</strong>
        <p>{item.current ? 'Live telemetry' : `${item.runtime.label} · current flight state unavailable`}</p></div></div>
      {item.lastKnown && <p className="fleet-inline-warning">Measurements below are last known, not current.</p>}
      {!!item.issues.length && <section aria-label="Aircraft alerts"><h3 className="fleet-inspector__alert-title">Aircraft alerts <small>{item.issues.length}</small></h3>
        <ul className="fleet-inspector__issues">{item.issues.map((issue) => <li className={`tone-${issue.tone}`} key={issue.key}><FaExclamationTriangle aria-hidden="true" />{issue.label}</li>)}</ul></section>}
      <dl className="fleet-inspector__facts">
        <dt>Configured IP</dt><dd><code>{normalizeRuntimeIp(item.raw.ip) || 'Unknown'}</code></dd>
        <dt>Arming</dt><dd>{item.armed === null ? 'Unknown' : item.armed ? 'Armed' : 'Disarmed'}</dd>
        <dt>Battery</dt><dd>{item.battery.text}{item.battery.stale ? ' · last known' : ''}</dd>
        <dt>Altitude</dt><dd>{altitudeText(item.altitude)}{item.altitude.stale ? ' · last known' : ''}</dd>
        <dt>GPS</dt><dd>{item.gps.label}{item.gps.stale ? ' · last known' : ''}</dd>
        <dt>Satellites</dt><dd>{item.gps.satellites ?? 'Unknown'}{item.gps.stale ? ' · last known' : ''}</dd>
        <dt>Position</dt><dd>{item.position.latitude == null ? 'Unavailable' : `${item.position.latitude.toFixed(6)}, ${item.position.longitude.toFixed(6)}${item.position.stale ? ' · last known' : ''}`}</dd>
        <dt>Flight mode</dt><dd>{item.flightMode.label}{item.flightMode.stale ? ' · last known' : ''}</dd>
        <dt>Mission</dt><dd>{item.mission.label}{item.mission.stale ? ' · last known' : ''}</dd>
        <dt>Readiness</dt><dd>{item.readiness.label}</dd>
        <dt>Network</dt><dd title={item.network.interface || undefined}><NetworkIcon aria-hidden="true" />{' '}{item.network.label}{item.network.percent !== null ? ` · ${Math.round(item.network.percent)}%` : ''}{item.network.stale ? ' · last known' : ''}</dd>
      </dl>
      {MISSION_ROUTES[mission] && <Link className="fleet-workspace-link" to={MISSION_ROUTES[mission]} onClick={onClose}>{item.mission.label} workspace →</Link>}
      <section className="fleet-inspector__actions" aria-label={`Actions for ${item.label} · H${item.id}`}>
        <button type="button" onClick={() => onAction('TAKE_OFF', item)}>Takeoff</button>
        <button type="button" onClick={() => onAction('HOLD', item)}>Hold</button>
        <button type="button" onClick={() => onAction('LAND', item)}>Land</button>
        <button type="button" onClick={() => onAction('RETURN_RTL', item)}>Return</button>
        <button type="button" disabled={!item.current || item.flightState !== 'Airborne'} onClick={() => onMove(item)}>Move</button>
        {onMore && <button type="button" onClick={() => onMore(item)}>More</button>}
      </section>
      <details><summary>Diagnostics</summary><dl className="fleet-inspector__facts">
        <dt>Heartbeat age</dt><dd>{heartbeatText(item.availability)}</dd>
        <dt>Network interface</dt><dd>{item.network.interface || 'Unknown'}{item.network.stale ? ' · last known' : ''}</dd>
        <dt>Telemetry age</dt><dd>{item.runtime.telemetryAgeSec == null ? 'Never seen' : `${item.runtime.telemetryAgeSec}s ago`}</dd>
        <dt>HDOP / VDOP</dt><dd>{item.gps.hdop ?? '—'} / {item.gps.vdop ?? '—'}</dd>
        <dt>Link evidence</dt><dd>{item.runtime.tooltip}</dd>
        <dt>Battery source</dt><dd>{item.battery.help}</dd>
        <dt>Flight mode code</dt><dd>{item.raw.flight_mode == null ? 'Unknown' : String(item.raw.flight_mode)}</dd>
        <dt>Readiness detail</dt><dd>{item.readiness.summary || 'Unknown'}</dd>
        <dt>Companion</dt><dd><Link to="/fleet-ops" onClick={onClose}>Fleet operations →</Link></dd>
      </dl></details>
    </div>
  </dialog>;
}
