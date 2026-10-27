import React, { useMemo, useState } from 'react';
import { Link as RouterLink } from 'react-router-dom';
import {
  MdFlightTakeoff,
  MdPauseCircleOutline,
  MdReplay,
  MdStop,
  MdWarningAmber,
} from 'react-icons/md';
import { toast } from 'react-toastify';

import ImportSection from '../components/ImportSection';
import VisualizationSection from '../components/VisualizationSection';
import ExportSection from '../components/ExportSection';
import {
  MetricStrip,
  OperatorCard,
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import useFetch from '../hooks/useFetch';
import {
  GCS_ROUTE_KEYS,
  getFleetConfigResponse,
} from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../constants/droneConstants';
import '../styles/DroneShowWorkspace.css';

const PHASE_LABELS = {
  idle: 'Idle',
  preparing: 'Preparing',
  awaiting_ack: 'Dispatching',
  scheduled: 'Scheduled',
  pending_execution: 'Waiting to start',
  executing: 'Show in progress',
  finishing: 'Finishing',
  completed: 'Complete',
  failed: 'Failed',
  cancelled: 'Cancelled',
  timeout: 'Timed out',
  terminal: 'Complete',
};

const MODE_OPTIONS = [
  { value: 'global-auto', label: 'Global · auto correction', detail: 'Recommended outdoors' },
  { value: 'global-manual', label: 'Global · manual placement', detail: 'Precise launch placement required' },
  { value: 'local', label: 'Local launch frame', detail: 'Specialist / controlled use' },
];

function formatDuration(milliseconds) {
  const totalSeconds = Math.max(0, Math.round(Number(milliseconds || 0) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, '0')}s`;
}

function ReadinessRow({ label, state, detail }) {
  const tone = state === 'pass' ? 'success' : state === 'fail' ? 'danger' : 'warning';
  return (
    <div className="drone-show-workspace__readiness-row">
      <span className={`drone-show-workspace__signal drone-show-workspace__signal--${tone}`} aria-hidden="true" />
      <span className="drone-show-workspace__readiness-label">{label}</span>
      <span className={`drone-show-workspace__readiness-state drone-show-workspace__readiness-state--${tone}`}>
        {state === 'pass' ? 'Ready' : state === 'fail' ? 'Review' : 'Waiting'}
      </span>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function OperateTab({ workspace, operation, targetIds, onCommand, commandBusy }) {
  const packageInfo = workspace?.package || {};
  const validation = workspace?.validation || {};
  const safety = workspace?.safety || {};
  const progress = operation?.command?.progress || {};
  const phase = operation?.phase || 'idle';
  const hasPackage = Boolean(packageInfo.available);
  const validationReady = !['FAIL', 'BLOCKED'].includes(String(validation.validation_status || '').toUpperCase());
  const safetyStatus = safety.safety_analysis?.safety_status || safety.safety_status;
  const safetyReady = !safetyStatus || safetyStatus === 'SAFE';
  const fleetReady = (operation?.fleet || []).length > 0
    && (operation?.fleet || []).every((drone) => drone.telemetry_fresh !== false);
  const fleetAirborne = (operation?.fleet || []).some((drone) => (
    drone.armed
    || /(?:OFFBOARD|HOLD|POSITION|MISSION|AUTO)/i.test(String(drone.state || ''))
  ));
  const ready = hasPackage && validationReady && safetyReady && fleetReady;
  const [pendingAction, setPendingAction] = useState(null);

  const confirmAction = async (action) => {
    if (pendingAction !== action) {
      setPendingAction(action);
      return;
    }
    setPendingAction(null);
    await onCommand(action);
  };

  const actionDisabled = (action) => {
    if (commandBusy || !targetIds.length) return true;
    const activePhases = ['preparing', 'awaiting_ack', 'scheduled', 'pending_execution', 'executing', 'finishing', 'in_progress'];
    const terminalPhases = ['idle', 'completed', 'failed', 'cancelled', 'timeout', 'terminal'];
    if (action === 'launch') return !ready || fleetAirborne || activePhases.includes(phase);
    if (action === 'hold') return !activePhases.includes(phase);
    return terminalPhases.includes(phase) && !fleetAirborne;
  };

  return (
    <div className="drone-show-workspace__operate">
      <div className="drone-show-workspace__operation-rail">
        <div className="drone-show-workspace__operation-title">
          <span className="drone-show-workspace__eyebrow">Current operation</span>
          <strong>{PHASE_LABELS[phase] || phase}</strong>
          {operation?.mission_name ? <small>{operation.mission_name}</small> : null}
        </div>
        <div className="drone-show-workspace__operation-progress" aria-label="Show progress">
          <span style={{ width: `${Number(operation?.progress_percent || 0)}%` }} />
        </div>
        <div className="drone-show-workspace__operation-stats">
          <span><b>{operation?.fleet?.filter((drone) => drone.telemetry_fresh).length || 0}</b> live</span>
          <span><b>{targetIds.length}</b> targeted</span>
          <span><b>{progress.label || 'No active show'}</b></span>
        </div>
      </div>

      <div className="drone-show-workspace__operate-grid">
        <OperatorCard className="drone-show-workspace__readiness">
          <div className="drone-show-workspace__section-heading">
            <div><span className="drone-show-workspace__eyebrow">Launch gate</span><h2>Ready to fly</h2></div>
            <StatusBadge tone={ready ? 'success' : 'warning'}>{ready ? 'READY' : 'REVIEW'}</StatusBadge>
          </div>
          <ReadinessRow label="Show package" state={hasPackage ? 'pass' : 'fail'} detail={hasPackage ? `${packageInfo.drone_count} aircraft · ${formatDuration(packageInfo.duration_ms)}` : 'Import a SkyBrush ZIP'} />
          <ReadinessRow label="Trajectory validation" state={validationReady ? 'pass' : 'fail'} detail={validationReady ? 'No blocking geometry errors' : 'Open Design / Setup'} />
          <ReadinessRow label="Safety report" state={safetyReady ? 'pass' : 'warn'} detail={safetyStatus || 'Not available'} />
          <ReadinessRow label="Fleet telemetry" state={fleetReady ? 'pass' : 'warn'} detail={`${operation?.fleet?.filter((drone) => drone.telemetry_fresh).length || 0}/${targetIds.length} fresh`} />
        </OperatorCard>

        <OperatorCard className="drone-show-workspace__controls">
          <div className="drone-show-workspace__section-heading">
            <div><span className="drone-show-workspace__eyebrow">Flight control</span><h2>Show actions</h2></div>
            <small>{targetIds.length ? `${targetIds.length} aircraft` : 'No fleet target'}</small>
          </div>
          <div className="drone-show-workspace__action-grid">
            {[
              ['launch', MdFlightTakeoff, 'Launch show'],
              ['hold', MdPauseCircleOutline, 'Hold show'],
              ['return', MdReplay, 'Managed return'],
              ['land', MdStop, 'Land here'],
              ['abort', MdWarningAmber, 'Abort'],
            ].map(([key, Icon, label]) => (
              <button
                key={key}
                type="button"
                className={`drone-show-workspace__action drone-show-workspace__action--${key}`}
                disabled={actionDisabled(key)}
                onClick={() => confirmAction(key)}
                aria-label={pendingAction === key ? `Confirm ${label}` : label}
              >
                <Icon aria-hidden="true" />
                <span>{pendingAction === key ? `Confirm ${label}` : label}</span>
              </button>
            ))}
          </div>
          {pendingAction ? <p className="drone-show-workspace__confirm-hint">Select the same action again to confirm.</p> : null}
        </OperatorCard>
      </div>

      <OperatorCard className="drone-show-workspace__fleet-status">
        <div className="drone-show-workspace__section-heading"><div><span className="drone-show-workspace__eyebrow">Fleet status</span><h2>Aircraft</h2></div></div>
        <div className="drone-show-workspace__fleet-table" role="table" aria-label="Drone show fleet status">
          {(operation?.fleet || []).map((drone) => (
            <div className="drone-show-workspace__fleet-row" role="row" key={drone.hw_id}>
              <span className={`drone-show-workspace__signal drone-show-workspace__signal--${drone.telemetry_fresh ? 'success' : 'warning'}`} aria-hidden="true" />
              <b>HW {drone.hw_id}</b>
              <span>{drone.state}</span>
              <span>{drone.armed ? 'Armed' : 'Disarmed'}</span>
              <span>{drone.battery_percent == null ? '—' : `${Math.round(drone.battery_percent)}%`}</span>
              <span>{drone.telemetry_fresh ? 'Live' : 'Stale'}</span>
            </div>
          ))}
          {!operation?.fleet?.length ? <div className="drone-show-workspace__empty">No configured aircraft found.</div> : null}
        </div>
      </OperatorCard>
    </div>
  );
}

function SetupTab({ uploadCount, setUploadCount, selectedMode, onModeChange }) {
  return (
    <div className="drone-show-workspace__setup">
      <div className="drone-show-workspace__setup-flow" aria-label="Drone show setup flow">
        <span className="is-active"><b>1</b> Import</span><span><b>2</b> Review</span><span><b>3</b> Launch geometry</span><span><b>4</b> Activate</span>
      </div>
      <OperatorCard className="drone-show-workspace__setup-card"><ImportSection setUploadCount={setUploadCount} /></OperatorCard>
      <OperatorCard className="drone-show-workspace__setup-card"><VisualizationSection uploadCount={uploadCount} /></OperatorCard>
      <OperatorCard className="drone-show-workspace__setup-card drone-show-workspace__mode-card">
        <div className="drone-show-workspace__section-heading">
          <div><span className="drone-show-workspace__eyebrow">Launch mode</span><h2>Position reference</h2></div>
          <StatusBadge tone="info">Next launch</StatusBadge>
        </div>
        <div className="drone-show-workspace__mode-list" role="radiogroup" aria-label="Drone show launch mode">
          {MODE_OPTIONS.map((mode) => (
            <label key={mode.value} className={`drone-show-workspace__mode-option ${selectedMode === mode.value ? 'is-selected' : ''}`}>
              <input
                type="radio"
                name="drone-show-mode"
                value={mode.value}
                checked={selectedMode === mode.value}
                onChange={() => onModeChange(mode.value)}
              />
              <span><b>{mode.label}</b><small>{mode.detail}</small></span>
            </label>
          ))}
        </div>
      </OperatorCard>
      <OperatorCard className="drone-show-workspace__setup-card">
        <div className="drone-show-workspace__section-heading"><div><span className="drone-show-workspace__eyebrow">Launch geometry</span><h2>Position and origin</h2></div><RouterLink to="/mission-config" className="drone-show-workspace__text-link">Open Mission Config</RouterLink></div>
        <p className="drone-show-workspace__compact-copy">Review launch slots, hardware assignments, origin, and live deviations before activating the show.</p>
      </OperatorCard>
      <OperatorCard className="drone-show-workspace__setup-card"><ExportSection /></OperatorCard>
      <details className="drone-show-workspace__advanced">
        <summary>Advanced: Custom CSV show</summary>
        <p>Use only for a protocol-ready local-frame CSV. It does not run SkyBrush conversion.</p>
        <RouterLink to="/custom-show" className="drone-show-workspace__text-link">Open Custom CSV</RouterLink>
      </details>
    </div>
  );
}

export default function DroneShowWorkspace() {
  const [tab, setTab] = useState('operate');
  const [uploadCount, setUploadCount] = useState(0);
  const [commandBusy, setCommandBusy] = useState(false);
  const [selectedMode, setSelectedMode] = useState('global-auto');
  const { data: workspace, loading: workspaceLoading, error: workspaceError } = useFetch(GCS_ROUTE_KEYS.showWorkspace, 10000);
  const { data: operation, loading: operationLoading } = useFetch(GCS_ROUTE_KEYS.showOperationStatus, 1000);
  const [config, setConfig] = useState([]);

  React.useEffect(() => {
    let active = true;
    getFleetConfigResponse().then((response) => {
      if (active && Array.isArray(response.data)) setConfig(response.data);
    }).catch(() => {});
    return () => { active = false; };
  }, []);

  const targetIds = useMemo(
    () => (operation?.target_drone_ids?.length ? operation.target_drone_ids : config.map((drone) => String(drone.hw_id))),
    [config, operation?.target_drone_ids],
  );

  const onCommand = async (action) => {
    const missionByAction = {
      launch: DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV,
      hold: DRONE_ACTION_TYPES.HOLD,
      return: DRONE_ACTION_TYPES.RETURN_RTL,
      land: DRONE_ACTION_TYPES.LAND,
      abort: DRONE_MISSION_TYPES.NONE,
    };
    setCommandBusy(true);
    try {
      const isLaunch = action === 'launch';
      await submitCommandWithLifecycleFeedback({
        mission_type: missionByAction[action],
        target_drone_ids: targetIds,
        trigger_time: 0,
        ...(isLaunch
          ? {
            auto_global_origin: selectedMode === 'global-auto',
            use_global_setpoints: selectedMode !== 'local',
          }
          : {}),
        operator_label: `Drone Show · ${action}`,
        uiMeta: { operatorLabel: `Drone Show · ${action}`, targetLabel: `${targetIds.length} aircraft` },
      });
      const label = action === 'return' ? 'Managed return' : action === 'hold' ? 'Hold' : action === 'land' ? 'Land' : action === 'abort' ? 'Abort' : 'Launch';
      toast.success(`${label} sent.`);
    } catch (error) {
      toast.error(error?.message || 'Command was not accepted.');
    } finally {
      setCommandBusy(false);
    }
  };

  const packageInfo = workspace?.package || {};
  const statusTone = workspaceLoading || operationLoading ? 'info' : packageInfo.available ? 'success' : 'warning';
  const statusLabel = workspaceLoading ? 'Loading' : packageInfo.available ? 'Package loaded' : 'No show loaded';
  const metrics = workspace?.metrics?.metrics?.basic_metrics || workspace?.metrics?.basic_metrics || {};

  return (
    <PageShell
      className="drone-show-workspace"
      eyebrow="Mission workspace"
      title="Drone Show"
      subtitle="Prepare, verify, and operate one show from one focused surface."
      docsRoute="/drone-show"
      status={<StatusBadge tone={statusTone}>{statusLabel}</StatusBadge>}
    >
      <div className="drone-show-workspace__tabs" role="tablist" aria-label="Drone Show workspace">
        <button type="button" role="tab" aria-selected={tab === 'operate'} className={tab === 'operate' ? 'is-active' : ''} onClick={() => setTab('operate')}>Operate</button>
        <button type="button" role="tab" aria-selected={tab === 'setup'} className={tab === 'setup' ? 'is-active' : ''} onClick={() => setTab('setup')}>Design / Setup</button>
      </div>

      {workspaceError ? <OperatorNotice tone="warning" title="Show data unavailable">The workspace is showing live operation status only. Open Design / Setup after the GCS recovers.</OperatorNotice> : null}

      <MetricStrip
        className="drone-show-workspace__metrics"
        label="Show summary"
        items={[
          { key: 'drones', label: 'Aircraft', value: packageInfo.drone_count || '—' },
          { key: 'duration', label: 'Duration', value: packageInfo.duration_ms ? formatDuration(packageInfo.duration_ms) : '—' },
          { key: 'altitude', label: 'Max altitude', value: metrics.max_altitude_m ? `${metrics.max_altitude_m} m` : '—' },
          { key: 'speed', label: 'Max speed', value: metrics.max_velocity_ms ? `${metrics.max_velocity_ms} m/s` : '—' },
        ]}
      />

      {tab === 'operate'
        ? <OperateTab workspace={workspace} operation={operation} targetIds={targetIds} onCommand={onCommand} commandBusy={commandBusy} />
        : <SetupTab uploadCount={uploadCount} setUploadCount={setUploadCount} selectedMode={selectedMode} onModeChange={setSelectedMode} />}
    </PageShell>
  );
}
