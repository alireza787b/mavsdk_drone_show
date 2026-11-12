import React, { useMemo, useState } from 'react';
import { PageShell, ConfirmDialog } from '../components/ui';
import { getBackendURL } from '../config/apiConfig';
import { getFleetConfigResponse, getFleetTelemetryResponse } from '../services/gcsApiService';
import { getSources } from '../services/logService';
import { useFleetResource, mergeFleetResources } from '../features/fleet-overview/useFleetResources';
import { buildFleetViewModel } from '../features/fleet-overview/fleetViewModel';
import { normalizeTelemetryResponse } from '../constants/fieldMappings';
import { matchesDroneSearchQuery } from '../utilities/dronePresentation';
import useUlogTransfers from '../features/log-workspace/useUlogTransfers';
import RuntimeLogsWorkspace from '../components/logs/RuntimeLogsWorkspace';
import FlightLogsWorkspace from '../components/logs/FlightLogsWorkspace';
import UlogTransferActivity from '../components/logs/UlogTransferActivity';
import '../styles/LogViewer.css';

const loadSources = async options => ({ data: await getSources(options) });

function SourceChooser({ aircraft, source, flightOnly, loading, rosterError, onChoose, onClose }) {
  const [candidate, setCandidate] = useState(source), [search, setSearch] = useState('');
  const visible = aircraft.filter(item => matchesDroneSearchQuery(item.raw, search));
  return <ConfirmDialog appearance="console" open title="Choose log source" cancelLabel="Cancel" confirmLabel="Use source" onCancel={onClose} onConfirm={() => { onChoose(candidate); onClose(); }} confirmDisabled={flightOnly && candidate === 'gcs'}
    message={<div><label>Find aircraft<input type="search" aria-label="Find log source" value={search} onChange={event => setSearch(event.target.value)} /></label>
      {!flightOnly && <label className="logs-check"><input type="radio" name="log-source" checked={candidate === 'gcs'} onChange={() => setCandidate('gcs')} />GCS</label>}
      {loading && <p role="status">Loading aircraft…</p>}
      {!loading && !visible.length && <p role="status">{rosterError ? 'Aircraft roster unavailable. Current source is unchanged.' : search ? 'No matching aircraft.' : 'No configured aircraft.'}</p>}
      <div className="logs-source-options">{visible.map(item => <label className="logs-check" key={item.id}>
        <input type="radio" name="log-source" checked={candidate === item.id} onChange={() => setCandidate(item.id)} /><span>{item.label} · H{item.id}</span><small>{item.identity.posId ? `Position ${item.identity.posId} · ` : ''}{item.availability.label}</small>
      </label>)}</div></div>} />;
}

export default function LogViewer({ runtimeMode = 'unknown', operatorId = '', userRole = 'viewer' }) {
  const context = `${getBackendURL()}:${runtimeMode}:${operatorId || 'browser-session'}`;
  return <LogsWorkspace key={context} context={context} runtimeMode={runtimeMode} userRole={userRole} />;
}

function LogsWorkspace({ context, runtimeMode, userRole }) {
  const config = useFleetResource(getFleetConfigResponse, 30000, context);
  const telemetry = useFleetResource(getFleetTelemetryResponse, 15000, context);
  const sources = useFleetResource(loadSources, 60000, context);
  const [source, setSource] = useState('gcs'), [tab, setTab] = useState('live'), [chooser, setChooser] = useState(false);
  const [now, setNow] = useState(Date.now);
  React.useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const drones = useMemo(() => {
    const clock = { receivedAtMs: telemetry.receivedAtMs, serverNowMs: telemetry.response?.headers?.['x-mds-server-time'] ?? telemetry.response?.headers?.date };
    const payload = telemetry.response?.data?.telemetry || telemetry.response?.data || {};
    return mergeFleetResources(config.response?.data, normalizeTelemetryResponse(payload, clock), {}, clock);
  }, [config.response, telemetry.response, telemetry.receivedAtMs]);
  const model = useMemo(() => buildFleetViewModel(drones, { nowMs: now, displayPolicy: telemetry.response?.data?.display_policy }), [drones, now, telemetry.response]);
  const aircraft = model.byId.get(source), droneId = source === 'gcs' ? null : source;
  const label = source === 'gcs' ? 'GCS' : `${aircraft?.label || 'Unknown aircraft'} · H${source}`;
  const transfers = useUlogTransfers(`mds:ulog-transfers:v1:${context}`);
  return <PageShell className="logs-workspace operator-console" title="Logs" docsRoute="/logs" status={<span className="logs-runtime-label">{runtimeMode.toUpperCase()}</span>}>
    <div className="logs-tabs" role="tablist" aria-label="Logs workspace">{[['live', 'Live'], ['sessions', 'Sessions'], ['flight', 'Flight logs']].map(([key, title]) => <button type="button" key={key} id={`logs-tab-${key}`} role="tab" aria-selected={tab === key} aria-controls={`logs-panel-${key}`} onClick={() => setTab(key)}>{title}</button>)}</div>
    <section className="logs-source-strip" aria-label="Selected log source"><span>Source</span><button type="button" className="operator-button operator-button--ghost" aria-label="Choose log source" onClick={() => setChooser(true)}>{label} ▾</button>
      {config.error && <small>Aircraft metadata unavailable · current source unchanged</small>}</section>
    <div id={`logs-panel-${tab}`} role="tabpanel" aria-labelledby={`logs-tab-${tab}`}>
      {tab === 'flight' ? <FlightLogsWorkspace key={`${context}:${source}`} droneId={droneId} sourceLabel={label} userRole={userRole} transfers={transfers} />
        : <RuntimeLogsWorkspace key={`${context}:${source}`} tab={tab} droneId={droneId} sourceLabel={label} context={context} registry={sources.response?.data?.components || {}} now={now} />}
    </div>
    <UlogTransferActivity transfers={transfers} userRole={userRole} now={now} />
    {chooser && <SourceChooser aircraft={model.aircraft} source={source} flightOnly={tab === 'flight'} loading={config.loading && telemetry.loading} rosterError={Boolean(config.error)} onChoose={setSource} onClose={() => setChooser(false)} />}
  </PageShell>;
}
