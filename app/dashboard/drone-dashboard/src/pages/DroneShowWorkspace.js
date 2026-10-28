import React, { useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { MdFlightTakeoff, MdHome, MdPauseCircleOutline, MdStop } from 'react-icons/md';
import { toast } from 'react-toastify';
import ImportSection from '../components/ImportSection';
import VisualizationSection from '../components/VisualizationSection';
import ShowPlotImage from '../components/ShowPlotImage';
import ShowAnalysisDetails from '../components/ShowAnalysisDetails';
import ExportSection from '../components/ExportSection';
import SequentialReturnControl from '../components/SequentialReturnControl';
import DeviationView from '../components/DeviationView';
import { ConfirmDialog, MetricStrip, OperatorCard, OperatorNotice, PageShell, StatusBadge } from '../components/ui';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { getCommandName } from '../constants/droneConstants';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { buildShowCommand, showReadiness, SHOW_MODES } from '../utilities/droneShowWorkspace';
import '../styles/DroneShowWorkspace.css';

const PHASES = { idle: 'Idle', preparing: 'Checking aircraft', awaiting_ack: 'Dispatching',
  scheduled: 'Scheduled', pending_execution: 'Starting', executing: 'Running', finishing: 'Finishing',
  completed: 'Complete', partial: 'Partial result', failed: 'Failed', cancelled: 'Cancelled',
  timeout: 'Unconfirmed', superseded: 'Replaced' };
const ACTIONS = { launch: 'Launch show', hold: 'Hold', land: 'Land here', rtl: 'Immediate RTL', cancel: 'Cancel show' };

function duration(ms) {
  const seconds = Math.round(Number(ms || 0) / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}
function ReadinessRow({ label, ready, detail, caution = false, action = null, status = null }) {
  const tone = ready && !caution ? 'success' : 'warning';
  return <div className="drone-show-workspace__readiness-row">
    <span className={`drone-show-workspace__signal drone-show-workspace__signal--${tone}`} aria-hidden="true" />
    <span>{label}</span><StatusBadge tone={tone}>{status || (ready ? (caution ? 'Review' : 'Ready') : 'Check')}</StatusBadge>
    {detail && <small>{detail}</small>}
    {action}
  </div>;
}

export default function DroneShowWorkspace() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') === 'setup' ? 'setup' : 'operate';
  const [revision, setRevision] = useState(0);
  const [mode, setMode] = useState('global-auto');
  const [delay, setDelay] = useState(10);
  const [review, setReview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [aircraftFilter, setAircraftFilter] = useState('');
  const pending = useRef(null);
  const workspaceState = useGcsResourcePolling(GCS_ROUTE_KEYS.showWorkspace, 15000, revision);
  const operationState = useGcsResourcePolling(GCS_ROUTE_KEYS.showOperationStatus, 2000);
  const originState = useGcsResourcePolling(GCS_ROUTE_KEYS.origin, 15000, revision);
  const geometryState = useGcsResourcePolling(mode === 'global-auto' ? GCS_ROUTE_KEYS.positionDeviations : null, 5000, revision);
  const workspace = workspaceState.data;
  const operation = operationState.data;
  const fleet = useMemo(() => operation?.fleet || [], [operation]);
  const visibleFleet = fleet.filter(d => `${d.name} ${d.hw_id} ${d.pos_id}`.toLowerCase().includes(aircraftFilter.toLowerCase()));
  const revealEvidence = (event, id) => {
    event.preventDefault();
    const panel = document.getElementById(id);
    if (panel) { panel.open = true; panel.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); }
  };
  const targetIds = useMemo(() => fleet.map((d) => d.hw_id), [fleet]);
  const recoveryIds = operation?.operation_target_ids?.length ? operation.operation_target_ids : targetIds;
  const recoveryNames = recoveryIds.map((id) => fleet.find((d) => d.hw_id === id)?.name || `HW ${id}`);
  const readiness = showReadiness({ workspace, operation, mode, origin: originState.data, deviations: geometryState.data });
  const active = operation?.state === 'active';
  const recoverable = active || fleet.some((d) => d.armed === true);
  const validDelay = Number.isFinite(Number(delay)) && Number(delay) >= 10 && Number(delay) <= 3600;
  const ready = readiness.ready && !active && !operationState.error && validDelay;
  const packageInfo = workspace?.package || {};
  const metrics = workspace?.metrics?.metrics || {};
  const phase = operation?.phase || 'idle';
  const selectedMode = SHOW_MODES.find((m) => m.value === mode);
  const scopeKey = JSON.stringify([targetIds, recoveryIds, packageInfo.revision, mode, delay]);
  const openReview = (action) => {
    setError('');
    setReview({ action, ids: [...(action === 'launch' ? targetIds : recoveryIds)], scopeKey });
  };
  const execute = async () => {
    if (!review || busy) return;
    if (review.scopeKey !== scopeKey || (review.action === 'launch' && !ready)) {
      setReview(null); setError('Readiness or selection changed. Review again.'); return;
    }
    setBusy(true);
    try {
      // Keep the exact request identity after a lost receipt; a retry must not
      // create a second scheduled launch. Clear only on authoritative acceptance.
      const fingerprint = JSON.stringify([review.action, review.ids, mode, delay]);
      if (pending.current?.fingerprint !== fingerprint) {
        const referenceNowMs = operation.timestamp + performance.now() - operationState.receivedAt;
        pending.current = { fingerprint, command: {
          ...buildShowCommand(review.action, review.ids, { mode, delay, referenceNowMs }),
          idempotency_key: `show-${crypto.randomUUID()}`,
        } };
      }
      await submitCommandWithLifecycleFeedback(pending.current.command);
      pending.current = null;
      setReview(null);
    } catch (exc) {
      setError(exc?.message || 'Dispatch unconfirmed. Retry to recover the same request.');
      toast.error('Command not confirmed. Check status before retrying.');
    } finally { setBusy(false); }
  };

  return <PageShell className="drone-show-workspace" title="Drone Show" docsRoute="/drone-show"
    status={<StatusBadge tone={ready ? 'success' : 'info'}>{active ? PHASES[phase] || 'Active' : ready ? 'Ready' : 'Review'}</StatusBadge>}>
    <div className="drone-show-workspace__workflow" aria-label="Drone Show workflow">
      {['Setup', 'Review', 'Launch', 'Monitor'].map((step, index) => {
        const current = tab === 'setup' ? index === 0 : index === 3;
        return <span key={step} className={current ? 'is-current' : ''}>
          <b>{index + 1}</b><span>{step}</span>
        </span>;
      })}
    </div>
    <div className="drone-show-workspace__tabs" role="tablist" aria-label="Drone Show workspace">
      {['operate', 'setup'].map((key) => <button type="button" role="tab" key={key}
        id={`show-tab-${key}`} aria-controls={`show-panel-${key}`} aria-selected={tab === key}
        className={tab === key ? 'is-active' : ''} onClick={() => setParams({ tab: key })}>
        {key === 'operate' ? 'Operate' : 'Design / Setup'}</button>)}
    </div>
    {(workspaceState.error || operationState.error) && <OperatorNotice tone="warning" title="Connection unavailable">Launch disabled. Last flight outcome may be unconfirmed.</OperatorNotice>}
    {error && <OperatorNotice tone="warning" title="Check command status">{error}</OperatorNotice>}
    <div className="drone-show-workspace__summary">
      <div className="drone-show-workspace__summary-heading">
        <div><span className="drone-show-workspace__eyebrow">Mission package</span><strong>{packageInfo.name || 'No show loaded'}</strong></div>
        <span className="drone-show-workspace__summary-state">{packageInfo.available ? 'Loaded' : 'Awaiting import'}</span>
      </div>
      <MetricStrip label="Show summary" items={[
      { label: 'Aircraft', value: packageInfo.drone_count || '—' },
      { label: 'Duration', value: packageInfo.duration_ms ? duration(packageInfo.duration_ms) : '—' },
      { label: 'Max altitude', value: packageInfo.max_altitude != null ? `${packageInfo.max_altitude} m` : '—' },
      { label: 'Max speed', value: metrics.performance_metrics?.max_velocity_ms != null ? `${metrics.performance_metrics.max_velocity_ms} m/s` : '—' },
      { label: 'Min separation', value: metrics.safety_metrics?.min_inter_drone_distance_m != null ? `${metrics.safety_metrics.min_inter_drone_distance_m} m` : '—', detail: metrics.safety_metrics?.min_distance_details ? `P${metrics.safety_metrics.min_distance_details.drone_1} ↔ P${metrics.safety_metrics.min_distance_details.drone_2} · ${metrics.safety_metrics.min_distance_details.time_s}s` : 'pair/time unavailable' },
      ]} />
    </div>
    <section id={`show-panel-${tab}`} role="tabpanel" aria-labelledby={`show-tab-${tab}`}>
      {tab === 'operate' ? <div className="drone-show-workspace__operate">
        <div className="drone-show-workspace__operation-rail" role="status">
          <div className="drone-show-workspace__operation-title"><span className="drone-show-workspace__eyebrow">Operation</span><strong>{PHASES[phase] || phase}</strong><small>{operation?.mission_type != null ? getCommandName(operation.mission_type) : 'No show dispatched'}</small></div>
          <div className="drone-show-workspace__operation-progress" aria-label="Mission progress"><span style={{ width: `${fleet.length ? Math.round(((operation?.command?.executions?.succeeded || 0) / fleet.length) * 100) : 0}%` }} /></div>
          <div className="drone-show-workspace__operation-stats"><span><b>{fleet.filter((d) => d.telemetry_fresh).length}/{fleet.length}</b> live</span><span><b>{operation?.command?.executions?.succeeded || 0}</b> complete</span></div>
        </div>
        <div className="drone-show-workspace__operate-grid">
          <OperatorCard className="drone-show-workspace__controls">
            <h2>Flight control</h2>
            <label className="drone-show-workspace__field">Position reference<select aria-label="Position reference" value={mode} disabled={active || busy} onChange={(e) => setMode(e.target.value)}>
              {SHOW_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
            </select></label>
            <label className="drone-show-workspace__field">Start in (s)<input aria-label="Launch delay" type="number" min="10" max="3600" value={delay} disabled={active || busy} onChange={(e) => setDelay(e.target.value)} /></label>
            <div className="drone-show-workspace__action-grid">
              <button type="button" className="drone-show-workspace__action drone-show-workspace__action--launch" disabled={!ready || busy} onClick={() => openReview('launch')}><MdFlightTakeoff />Launch show</button>
              <button type="button" className="drone-show-workspace__action drone-show-workspace__action--hold" disabled={!recoverable || busy} onClick={() => openReview('hold')}><MdPauseCircleOutline />Hold</button>
              <button type="button" className="drone-show-workspace__action drone-show-workspace__action--return" disabled={!recoverable || busy} onClick={() => openReview('rtl')}><MdHome />Immediate RTL</button>
            </div>
            <details className="drone-show-workspace__advanced"><summary>Other actions</summary>
              <SequentialReturnControl compact targetIds={recoveryIds} targetNames={recoveryNames} contextKey={operation?.command_id || 'show'} />
              {['land', 'cancel'].map((action) => <button className="operator-button operator-button--ghost" type="button" key={action} disabled={!recoverable || busy} onClick={() => openReview(action)}><MdStop />{ACTIONS[action]}</button>)}
            </details>
          </OperatorCard>
          <OperatorCard className="drone-show-workspace__readiness">
            <h2>Preflight</h2>
            <ReadinessRow label="Package & aircraft slots" ready={readiness.packageReady && readiness.mappingReady} detail={!readiness.mappingReady ? 'Review package and hardware assignments.' : null} action={!readiness.mappingReady ? <Link to="/mission-config">Open Mission Config</Link> : null} />
            <ReadinessRow label="PX4 readiness" ready={readiness.fleetReady} detail={!readiness.fleetReady ? fleet.filter((d) => !d.telemetry_fresh || !d.ready_to_arm).map((d) => `${d.name}: ${!d.telemetry_fresh ? 'No live telemetry' : d.readiness_summary}`).join(' · ') : 'Aircraft connected and disarmed'} />
            <ReadinessRow label="Home / origin" ready={readiness.originReady} detail={readiness.originReady ? 'Shared launch reference set.' : 'Set the shared origin before global auto-correction.'} action={!readiness.originReady ? <Link to="/mission-config">Set origin</Link> : null} />
            <ReadinessRow label="Launch geometry" ready={readiness.geometryReady} caution={readiness.geometryState === 'review' || mode !== 'global-auto'} detail={mode !== 'global-auto' ? 'Manual placement mode.' : readiness.geometrySummary.worst_deviation != null ? `Worst ${Number(readiness.geometrySummary.worst_deviation).toFixed(1)} m · ${readiness.geometrySummary.warnings || 0} warning(s)` : 'Live positions are being checked.'} action={<a href="#launch-geometry" onClick={e => revealEvidence(e, 'launch-geometry')}>Review layout</a>} />
            <ReadinessRow label="Trajectory analysis" ready={readiness.analysisReady} caution={readiness.analysisStatus === 'WARNING'} status={readiness.analysisStatus === 'FAIL' ? 'Blocked' : readiness.analysisStatus === 'WARNING' ? 'Review' : null} detail={readiness.analysisStatus === 'UNKNOWN' ? 'Analysis not available.' : workspace?.validation?.findings?.[0]?.title || workspace?.validation?.issues?.[0]} action={<a href="#trajectory-analysis" onClick={e => revealEvidence(e, 'trajectory-analysis')}>View findings</a>} />
          </OperatorCard>
        </div>
        <details id="launch-geometry" className="drone-show-workspace__evidence-panel">
          <summary>Launch geometry · expected vs live</summary>
          <div className="drone-show-workspace__evidence-content">
            {readiness.originReady ? <DeviationView drones={fleet} deviationData={geometryState.data} trajectoryPositionsByPosId={{}} origin={originState.data} /> : <p>Set the shared origin in Mission Config to review launch positions.</p>}
            <Link to="/mission-config">Open Mission Config</Link>
          </div>
        </details>
        <details id="trajectory-analysis" className="drone-show-workspace__metrics-panel">
          <summary>Mission evidence</summary>
          <div className="drone-show-workspace__metric-details">
            <span>Max distance <b>{metrics.basic_metrics?.max_distance_from_launch_m != null ? `${metrics.basic_metrics.max_distance_from_launch_m} m` : '—'}</b></span>
            <span>Minimum separation <b>{metrics.safety_metrics?.min_inter_drone_distance_m != null ? `${metrics.safety_metrics.min_inter_drone_distance_m} m` : '—'}</b></span>
            <span>Safety <b>{metrics.safety_metrics?.safety_status || '—'}</b></span>
            <span>Trajectory <b>{readiness.analysisStatus}</b></span>
          </div>
          <ShowAnalysisDetails validation={workspace?.validation} metrics={metrics} />
        </details>
        {workspace?.plots?.filenames?.includes('combined_drone_paths.jpg') && <figure className="drone-show-workspace__preview-wrap"><figcaption>Trajectory preview</figcaption><ShowPlotImage className="drone-show-workspace__preview" filename="combined_drone_paths.jpg" plots={workspace.plots} alt="Loaded show trajectory preview" /></figure>}
        <OperatorCard className="drone-show-workspace__fleet-status"><h2>Aircraft · {fleet.filter(d => d.telemetry_fresh).length}/{fleet.length} live</h2>
          <label className="drone-show-workspace__field">Find aircraft<input type="search" value={aircraftFilter} onChange={e => setAircraftFilter(e.target.value)} placeholder="Callsign, hardware or position" /></label>
          <div className="drone-show-workspace__table-wrap"><table className="drone-show-workspace__table"><thead><tr><th>Aircraft</th><th>Mode</th><th>Flight state</th><th>Battery</th><th>Link</th></tr></thead><tbody>
            {visibleFleet.map((d) => <tr key={d.hw_id}><th data-label="Aircraft">{d.name}</th><td data-label="Mode">{d.state}</td><td data-label="Flight state">{d.armed === true ? 'Armed' : d.armed === false ? 'Disarmed' : 'Unknown'}</td><td data-label="Battery">{d.battery_percent == null ? '—' : `${Math.round(d.battery_percent)}%`}</td><td data-label="Link">{d.telemetry_fresh ? 'Live' : 'Unavailable'}</td></tr>)}
          </tbody></table></div>
        </OperatorCard>
      </div> : <div className="drone-show-workspace__setup">
        <div className="drone-show-workspace__setup-intro"><div><span className="drone-show-workspace__eyebrow">Design / Setup</span><h2>Prepare the show package</h2><p>Import, review, then hand off to Operate when the package and launch positions are ready.</p></div><Link className="drone-show-workspace__setup-next" to="/mission-config">Next: launch positions</Link></div>
        <ImportSection setUploadCount={setRevision} />
        <VisualizationSection uploadCount={revision} />
        <Link to="/mission-config">Review launch positions, assignments & origin</Link>
        <ExportSection />
        <details className="drone-show-workspace__advanced"><summary>Advanced · Custom CSV</summary><Link to="/custom-show">Open Custom CSV</Link></details>
      </div>}
    </section>
    <ConfirmDialog appearance="console" open={Boolean(review)} title={ACTIONS[review?.action] || 'Review command'}
      confirmLabel={ACTIONS[review?.action] || 'Confirm'} busy={busy} onCancel={() => setReview(null)} onConfirm={execute}
      confirmDisabled={!review || review.scopeKey !== scopeKey || (review.action === 'launch' && !ready)}
      message={review ? <div className="swarm-confirm-summary"><p>{review.ids.map((id) => fleet.find((d) => d.hw_id === id)?.name || `HW ${id}`).join(' · ')}</p>
        {review.action === 'launch' ? <p>{selectedMode.label} · starts {delay} s after confirmation</p>
          : <p>{review.action === 'hold' ? 'Ends the show and holds current positions. This is not a resumable pause.'
            : review.action === 'rtl' ? 'Returns all selected aircraft immediately using PX4 home and return height. Paths may overlap.'
              : review.action === 'land' ? 'Ends the show and lands at current positions.' : 'Cancels the show. Cancellation alone is not a verified Hold or landing.'}</p>}</div> : ''} />
  </PageShell>;
}
