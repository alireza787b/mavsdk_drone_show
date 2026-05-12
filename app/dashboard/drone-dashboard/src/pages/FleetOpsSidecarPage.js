import React, { useEffect, useMemo, useState } from 'react';
import {
  FaBroadcastTower,
  FaCheckCircle,
  FaClipboardCheck,
  FaEye,
  FaFileExport,
  FaInfoCircle,
  FaProjectDiagram,
  FaRedo,
  FaTimes,
  FaWifi,
} from 'react-icons/fa';
import {
  applyFleetSidecarPolicyResponse,
  applyFleetSidecarReconcileResponse,
  dryRunFleetSidecarPolicyResponse,
  dryRunFleetSidecarReconcileResponse,
  getFleetSidecarResponse,
  promoteFleetSidecarDraftResponse,
} from '../services/gcsApiService';
import { DocsLink } from '../components/ui';
import '../styles/FleetOpsSidecarPage.css';

export const SMART_WIFI_SIDECAR_CONFIG = {
  sidecar: 'smart-wifi-manager',
  title: 'Wi-Fi Sidecar Profiles',
  baselineTitle: 'Repo Wi-Fi Baseline',
  nodeTitle: 'Node Wi-Fi Profile',
  baselineDescription: 'Secrets are summarized only; passwords and secret-file paths are not returned.',
  icon: FaWifi,
  defaultMode: 'fleet-merge',
  docsRoute: '/fleet-ops/wifi',
  modes: ['fleet-merge', 'observe', 'local', 'fleet-strict'],
  itemKind: 'wifi',
  emptyLabel: 'No Wi-Fi profiles reported.',
};

export const MAVLINK_SIDECAR_CONFIG = {
  sidecar: 'mavlink-anywhere',
  title: 'MAVLink Sidecar Profiles',
  baselineTitle: 'Repo MAVLink Baseline',
  nodeTitle: 'Node MAVLink Overlay',
  baselineDescription: 'Fleet policy excludes hardware input overlays; source devices stay node-local by default.',
  icon: FaBroadcastTower,
  defaultMode: 'local',
  docsRoute: '/fleet-ops/mavlink',
  modes: ['local', 'observe', 'fleet-merge', 'fleet-strict'],
  itemKind: 'mavlink',
  emptyLabel: 'No MAVLink endpoints reported.',
};

const EMPTY_ROWS = [];
const RECONCILE_MODES = new Set(['fleet-merge', 'fleet-strict']);

function shortHash(value) {
  return value ? String(value).slice(0, 12) : 'n/a';
}

function statusClass(value) {
  if (value === 'in_sync' || value === 'online' || value === 'active') return 'ok';
  if (value === 'configured' || value === 'local_extra' || value === 'missing_fleet_baseline' || value === 'offline' || value === 'unknown') return 'warn';
  if (value === 'outdated' || value === 'unreachable' || value === 'failed') return 'bad';
  return '';
}

function formatAge(presence) {
  if (!presence || (presence.age_seconds !== 0 && !presence.age_seconds)) {
    return 'last seen unknown';
  }
  if (presence.age_seconds < 60) {
    return `${presence.age_seconds}s ago`;
  }
  return `${Math.round(presence.age_seconds / 60)}m ago`;
}

function getJobResults(job) {
  return Object.entries(job?.results || {});
}

function jobBlockedResults(job) {
  return getJobResults(job).filter(([, result]) => !result?.ok);
}

function isRowReadyForMutation(row) {
  return row?.presence?.state === 'online'
    && row?.service_state !== 'unreachable'
    && row?.drift_state !== 'unreachable';
}

function modeSummary(mode) {
  if (mode === 'observe') return 'Report only; no sidecar profile mutation.';
  if (mode === 'local') return 'Node-local dashboard and CLI remain authoritative.';
  if (mode === 'fleet-strict') return 'Repo baseline authoritative; advanced confirmation required.';
  return 'Repo baseline is applied while local additions are preserved.';
}

function isReconcileMode(mode) {
  return RECONCILE_MODES.has(mode);
}

function errorMessage(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback;
}

function installedRefLabel(value) {
  if (!value) return 'n/a';
  if (typeof value === 'string') return value;
  return value.commit || value.ref || value.branch || value.path || 'reported';
}

function Modal({ title, icon: Icon = FaInfoCircle, children, onClose }) {
  return (
    <div className="fleet-sidecar__modal-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="fleet-sidecar__modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="fleet-sidecar__modal-head">
          <div>
            <Icon aria-hidden="true" />
            <h2>{title}</h2>
          </div>
          <button type="button" className="fleet-sidecar__icon-button" onClick={onClose} aria-label="Close dialog">
            <FaTimes />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}

function DetailGrid({ items }) {
  return (
    <dl className="fleet-sidecar__details">
      {items.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === '' ? 'n/a' : value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

function ProfileList({ profiles = [], endpoints = [], itemKind = 'wifi', emptyLabel = 'No profiles reported.' }) {
  const items = profiles.length ? profiles : endpoints;
  if (!items.length) {
    return <div className="fleet-sidecar__empty">{emptyLabel}</div>;
  }
  return (
    <div className="fleet-sidecar__profile-list">
      {items.map((item) => {
        if (itemKind === 'mavlink') {
          const address = item.address && item.port ? `${item.address}:${item.port}` : item.device || 'n/a';
          return (
            <div className="fleet-sidecar__profile-row" key={item.name || address}>
              <div>
                <strong>{item.name || 'endpoint'}</strong>
                <span>{item.type || 'endpoint'} · {item.category || 'policy'}</span>
              </div>
              <span className="fleet-sidecar__badge">{item.mode || 'normal'}</span>
              <span>{address}</span>
            </div>
          );
        }
        return (
          <div className="fleet-sidecar__profile-row" key={item.id || item.ssid}>
            <div>
              <strong>{item.ssid || item.id || 'profile'}</strong>
              <span>{item.id || 'no id'}</span>
            </div>
            <span className="fleet-sidecar__badge">secret:{item.secret_status || 'missing'}</span>
            <span>prio {item.priority ?? 0}</span>
          </div>
        );
      })}
    </div>
  );
}

export function SidecarStatusTable({ rows, selected, includeUnreachable, itemKind, onToggleSelected, onOpenNode }) {
  return (
    <div className="fleet-sidecar__table-wrap">
      <table className="fleet-sidecar__table">
        <thead>
          <tr>
            <th>Select</th>
            <th>Drone</th>
            <th>Presence</th>
            <th>Service</th>
            <th>Installed Ref</th>
            <th>Mode</th>
            <th>Source</th>
            <th>Desired</th>
            <th>{itemKind === 'mavlink' ? 'Applied' : 'Local'}</th>
            <th>Drift</th>
            <th>{itemKind === 'mavlink' ? 'Endpoints' : 'Profiles'}</th>
            <th>Dashboard</th>
            <th>Last Apply</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const selectable = includeUnreachable || isRowReadyForMutation(row);
            return (
              <tr key={row.hw_id} className={!isRowReadyForMutation(row) ? 'fleet-sidecar__row-muted' : ''}>
                <td data-label="Select">
                  <input
                    type="checkbox"
                    checked={selected.includes(String(row.hw_id))}
                    onChange={() => onToggleSelected(row)}
                    disabled={!selectable}
                    aria-label={`Select drone ${row.hw_id}`}
                    title={!selectable ? 'Unreachable or offline nodes require explicit include.' : undefined}
                  />
                </td>
                <td data-label="Drone">{row.hw_id}</td>
                <td data-label="Presence">
                  <span className={`fleet-sidecar__badge ${statusClass(row.presence?.state)}`} title={formatAge(row.presence)}>
                    {row.presence?.state || 'unknown'}
                  </span>
                </td>
                <td data-label="Service"><span className={`fleet-sidecar__badge ${statusClass(row.service_state)}`}>{row.service_state || 'unknown'}</span></td>
                <td data-label="Installed Ref">{installedRefLabel(row.installed_ref)}</td>
                <td data-label="Mode">{row.mode}</td>
                <td data-label="Source">{row.profile_source || 'n/a'}</td>
                <td data-label="Desired">{shortHash(row.desired_hash)}</td>
                <td data-label="Local">{shortHash(row.local_hash || row.applied_hash)}</td>
                <td data-label="Drift"><span className={`fleet-sidecar__badge ${statusClass(row.drift_state)}`}>{row.drift_state}</span></td>
                <td data-label="Profiles">{row.profile_count ?? 0}</td>
                <td data-label="Dashboard">{row.dashboard?.url ? <a href={row.dashboard.url} target="_blank" rel="noreferrer">Open</a> : 'n/a'}</td>
                <td data-label="Last Apply">{row.last_apply_result?.status || 'n/a'}</td>
                <td data-label="Details">
                  <button type="button" className="fleet-sidecar__table-button" onClick={() => onOpenNode(row)}>
                    <FaInfoCircle aria-hidden="true" /> View
                  </button>
                </td>
              </tr>
            );
          })}
          {!rows.length && (
            <tr>
              <td colSpan="14" className="fleet-sidecar__empty">No drones reported by Fleet Ops.</td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function SidecarProfileDialog({ config, table, dialog, closeDialog }) {
  const Icon = config.icon;
  if (dialog?.type === 'baseline') {
    return (
      <Modal title={config.baselineTitle} icon={Icon} onClose={closeDialog}>
        <div className="fleet-sidecar__callout">{config.baselineDescription}</div>
        <DetailGrid
          items={[
            ['Configured', table?.baseline?.present ? 'yes' : 'no'],
            ['Path', table?.baseline?.path],
            ['Hash', shortHash(table?.baseline?.hash)],
            [config.itemKind === 'mavlink' ? 'Endpoints' : 'Profiles', table?.baseline?.profile_count],
            ['Hash semantics', table?.baseline?.hash_semantics],
          ]}
        />
        <ProfileList
          profiles={table?.baseline?.profiles || []}
          endpoints={table?.baseline?.endpoints || []}
          itemKind={config.itemKind}
          emptyLabel={config.emptyLabel}
        />
      </Modal>
    );
  }

  if (dialog?.type === 'node') {
    return (
      <Modal title={`${config.nodeTitle}: ${dialog.row.hw_id}`} icon={FaInfoCircle} onClose={closeDialog}>
        <DetailGrid
          items={[
            ['Presence', `${dialog.row.presence?.state || 'unknown'} (${formatAge(dialog.row.presence)})`],
            ['Service', dialog.row.service_state],
            ['Installed ref', installedRefLabel(dialog.row.installed_ref)],
            ['Mode', dialog.row.mode],
            ['Profile source', dialog.row.profile_source],
            ['Desired hash', shortHash(dialog.row.desired_hash)],
            ['Local/applied hash', shortHash(dialog.row.local_hash || dialog.row.applied_hash)],
            ['Drift', dialog.row.drift_state],
            [config.itemKind === 'mavlink' ? 'Endpoints' : 'Profiles', dialog.row.profile_count],
            ['Dashboard', dialog.row.dashboard?.url],
            ['Last apply', dialog.row.last_apply_result?.status],
          ]}
        />
        <div className="fleet-sidecar__callout">
          {dialog.row.operator_state?.summary || 'Use dry-run before applying any profile or policy change.'}
        </div>
      </Modal>
    );
  }

  return null;
}

function PolicyModeDialog({ mode, setMode, modes }) {
  return (
    <div>
      <label htmlFor="fleet-sidecar-mode">Mode</label>
      <select id="fleet-sidecar-mode" value={mode} onChange={(event) => setMode(event.target.value)}>
        {modes.map((item) => <option key={item} value={item}>{item}</option>)}
      </select>
      <span title={modeSummary(mode)}><FaInfoCircle aria-hidden="true" /></span>
    </div>
  );
}

function DryRunApplyDialog({
  job,
  blockedResults,
  modalError,
  ack,
  setAck,
  advancedAck,
  setAdvancedAck,
  allowPartial,
  setAllowPartial,
  confirmText,
  setConfirmText,
  loading,
  onApplyReconcile,
  onApplyPolicy,
  closeDialog,
}) {
  const canConfirmApply = ack
    && confirmText === job?.confirmation_token
    && (!job || job.mode !== 'fleet-strict' || advancedAck)
    && (!blockedResults.length || allowPartial);

  return (
    <Modal title={job.kind || 'Fleet Ops Job'} icon={FaClipboardCheck} onClose={closeDialog}>
      {modalError && <div className="fleet-sidecar__alert in-modal">{modalError}</div>}
      <DetailGrid
        items={[
          ['Job', job.job_id],
          ['Mode', job.mode],
          ['Applied', job.applied ? 'yes' : 'no'],
          ['Confirmation token', job.confirmation_token],
          ['Baseline hash', shortHash(job.baseline_hash)],
          ['Drones', (job.node_ids || Object.keys(job.results || {})).join(', ')],
          ['Blocked', blockedResults.length],
          ['Created', job.created_at],
        ]}
      />
      <div className="fleet-sidecar__job-results">
        {getJobResults(job).map(([nodeId, result]) => {
          const plan = result?.result || {};
          return (
            <div className="fleet-sidecar__job-row" key={nodeId}>
              <span>{nodeId}</span>
              <span className={`fleet-sidecar__badge ${result.ok ? 'ok' : 'bad'}`}>{result.ok ? 'ready' : 'blocked'}</span>
              <span title={result.error || plan.dry_run_id}>{plan.diff?.drift_state || result.error || plan.dry_run_id || 'n/a'}</span>
            </div>
          );
        })}
        {!getJobResults(job).length && <div className="fleet-sidecar__empty">No per-node results.</div>}
      </div>
      {(job.kind === 'reconcile-dry-run' || job.kind === 'policy-dry-run') && (
        <div className="fleet-sidecar__confirm">
          <label><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} /> Acknowledge risks</label>
          {job.mode === 'fleet-strict' && (
            <label><input type="checkbox" checked={advancedAck} onChange={(event) => setAdvancedAck(event.target.checked)} /> Advanced strict ack</label>
          )}
          {blockedResults.length > 0 && (
            <label><input type="checkbox" checked={allowPartial} onChange={(event) => setAllowPartial(event.target.checked)} /> Confirm partial apply</label>
          )}
          <input value={confirmText} onChange={(event) => setConfirmText(event.target.value)} placeholder="Dry-run token" aria-label="Type dry-run confirmation token" />
          <button type="button" onClick={onApplyReconcile} disabled={loading || job.kind !== 'reconcile-dry-run' || !canConfirmApply}>
            <FaCheckCircle aria-hidden="true" /> Apply Reconcile
          </button>
          <button type="button" onClick={onApplyPolicy} disabled={loading || job.kind !== 'policy-dry-run' || !canConfirmApply}>
            <FaCheckCircle aria-hidden="true" /> Apply Policy
          </button>
        </div>
      )}
    </Modal>
  );
}

export default function FleetOpsSidecarPage({ config = SMART_WIFI_SIDECAR_CONFIG }) {
  const {
    sidecar,
    title,
    icon: HeaderIcon,
    defaultMode,
    docsRoute,
    modes,
    itemKind,
  } = config;
  const [table, setTable] = useState(null);
  const [selected, setSelected] = useState([]);
  const [mode, setMode] = useState(defaultMode);
  const [job, setJob] = useState(null);
  const [dialog, setDialog] = useState(null);
  const [ack, setAck] = useState(false);
  const [advancedAck, setAdvancedAck] = useState(false);
  const [allowPartial, setAllowPartial] = useState(false);
  const [includeUnreachable, setIncludeUnreachable] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [opsToken, setOpsToken] = useState(() => {
    if (typeof window === 'undefined') return '';
    return window.sessionStorage?.getItem('fleetOpsMutationToken') || '';
  });
  const [error, setError] = useState('');
  const [modalError, setModalError] = useState('');
  const [loading, setLoading] = useState(false);

  const rows = table?.rows || EMPTY_ROWS;
  const selectedRows = useMemo(
    () => rows.filter((row) => selected.includes(String(row.hw_id))),
    [rows, selected]
  );

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const response = await getFleetSidecarResponse(sidecar);
      setTable(response?.data || response);
    } catch (err) {
      setError(errorMessage(err, 'Failed to load Fleet Ops sidecar table.'));
    } finally {
      setLoading(false);
    }
  };

  const resetConfirmation = () => {
    setAck(false);
    setAdvancedAck(false);
    setAllowPartial(false);
    setConfirmText('');
    setModalError('');
  };

  const updateOpsToken = (value) => {
    setOpsToken(value);
    if (typeof window !== 'undefined') {
      if (value) {
        window.sessionStorage?.setItem('fleetOpsMutationToken', value);
      } else {
        window.sessionStorage?.removeItem('fleetOpsMutationToken');
        window.localStorage?.removeItem('fleetOpsMutationToken');
      }
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sidecar]);

  useEffect(() => {
    if (includeUnreachable) return;
    setSelected((current) => current.filter((item) => {
      const row = rows.find((candidate) => String(candidate.hw_id) === item);
      return row && isRowReadyForMutation(row);
    }));
  }, [includeUnreachable, rows]);

  const toggleSelected = (row) => {
    if (!includeUnreachable && !isRowReadyForMutation(row)) {
      return;
    }
    const value = String(row.hw_id);
    setSelected((current) => (
      current.includes(value)
        ? current.filter((item) => item !== value)
        : [...current, value]
    ));
  };

  const runAction = async (handler) => {
    setLoading(true);
    setError('');
    setModalError('');
    try {
      const response = await handler();
      const result = response?.data || response;
      setJob(result);
      setDialog({ type: 'job', job: result });
      resetConfirmation();
      await load();
    } catch (err) {
      if (dialog) {
        setModalError(errorMessage(err, 'Fleet Ops action failed.'));
      } else {
        setError(errorMessage(err, 'Fleet Ops action failed.'));
      }
    } finally {
      setLoading(false);
    }
  };

  const requireSelection = () => {
    if (!selected.length) {
      throw new Error('Select at least one drone first.');
    }
  };

  const dryRunReconcile = () => runAction(async () => {
    requireSelection();
    if (!isReconcileMode(mode)) {
      throw new Error('Reconcile is only available for fleet-merge or fleet-strict modes. Use policy dry-run to change observe/local posture.');
    }
    return dryRunFleetSidecarReconcileResponse(sidecar, { node_ids: selected, mode });
  });

  const applyReconcile = () => runAction(async () => {
    if (!job?.job_id || job.kind !== 'reconcile-dry-run') {
      throw new Error('Run reconcile dry-run first.');
    }
    if (!ack || confirmText !== job.confirmation_token) {
      throw new Error('Acknowledge risks and type the dry-run confirmation token before applying.');
    }
    if (jobBlockedResults(job).length && !allowPartial) {
      throw new Error('Dry-run has blocked nodes. Confirm partial apply before continuing.');
    }
    return applyFleetSidecarReconcileResponse(sidecar, {
      dry_run_id: job.job_id,
      confirmation: {
        acknowledged_risks: true,
        advanced_strict_ack: advancedAck,
        confirmation_token: confirmText,
        operator: 'dashboard',
      },
    });
  });

  const dryRunPolicy = () => runAction(async () => {
    requireSelection();
    return dryRunFleetSidecarPolicyResponse(sidecar, { node_ids: selected, mode });
  });

  const applyPolicy = () => runAction(async () => {
    if (!job?.job_id || job.kind !== 'policy-dry-run') {
      throw new Error('Run policy dry-run first.');
    }
    if (!ack || confirmText !== job.confirmation_token) {
      throw new Error('Acknowledge risks and type the dry-run confirmation token before applying.');
    }
    return applyFleetSidecarPolicyResponse(sidecar, {
      dry_run_id: job.job_id,
      confirmation: {
        acknowledged_risks: true,
        advanced_strict_ack: advancedAck,
        confirmation_token: confirmText,
        operator: 'dashboard',
      },
    });
  });

  const openPromoteDialog = () => {
    if (selected.length !== 1) {
      setError('Select exactly one reference drone.');
      return;
    }
    const row = rows.find((candidate) => String(candidate.hw_id) === String(selected[0]));
    resetConfirmation();
    setDialog({ type: 'promote-confirm', row });
  };

  const confirmPromoteDraft = async () => {
    if (!dialog?.row?.hw_id) {
      setModalError('Select exactly one reference drone.');
      return;
    }
    if (!ack || confirmText !== 'PROMOTE') {
      setModalError('Acknowledge risks and type PROMOTE before generating the draft.');
      return;
    }
    setLoading(true);
    setModalError('');
    try {
      const response = await promoteFleetSidecarDraftResponse(sidecar, { node_id: dialog.row.hw_id });
      const result = response?.data || response;
      setDialog({ type: 'promote-result', row: dialog.row, draft: result });
      resetConfirmation();
      await load();
    } catch (err) {
      setModalError(errorMessage(err, 'Promote draft failed.'));
    } finally {
      setLoading(false);
    }
  };

  const closeDialog = () => setDialog(null);
  const blockedResults = jobBlockedResults(job);
  const reconcileDisabled = loading || !selected.length || !isReconcileMode(mode);

  return (
    <main className="fleet-sidecar">
      <header className="fleet-sidecar__header">
        <div>
          <span className="fleet-sidecar__eyebrow">Fleet Ops</span>
          <h1><HeaderIcon aria-hidden="true" /> {title}</h1>
        </div>
        <div className="fleet-sidecar__header-actions">
          <DocsLink route={docsRoute} compact />
          <button type="button" onClick={load} disabled={loading}><FaRedo aria-hidden="true" /> Refresh</button>
        </div>
      </header>

      {error && <div className="fleet-sidecar__alert">{error}</div>}

      <section className="fleet-sidecar__toolbar">
        <PolicyModeDialog mode={mode} setMode={setMode} modes={modes} />
        <button type="button" onClick={() => setDialog({ type: 'baseline' })}><FaEye aria-hidden="true" /> Baseline</button>
        <button type="button" onClick={openPromoteDialog} disabled={loading || selected.length !== 1}><FaFileExport aria-hidden="true" /> Promote Draft</button>
        <button
          type="button"
          onClick={dryRunReconcile}
          disabled={reconcileDisabled}
          title={isReconcileMode(mode) ? 'Dry-run selected node reconcile' : 'Observe/local modes are inspect-only; use policy dry-run to change posture.'}
        >
          <FaProjectDiagram aria-hidden="true" /> Dry-run Reconcile
        </button>
        <button type="button" onClick={dryRunPolicy} disabled={loading || !selected.length}><FaClipboardCheck aria-hidden="true" /> Dry-run Policy</button>
        <input
          className="fleet-sidecar__token-input"
          type="password"
          value={opsToken}
          onChange={(event) => updateOpsToken(event.target.value)}
          placeholder="Ops token"
          aria-label="Fleet Ops mutation token"
        />
        <label className="fleet-sidecar__inline-check">
          <input
            type="checkbox"
            checked={includeUnreachable}
            onChange={(event) => setIncludeUnreachable(event.target.checked)}
          />
          Include unreachable
        </label>
      </section>

      <section className="fleet-sidecar__summary">
        <div><strong>Baseline</strong><span>{table?.baseline?.present ? shortHash(table.baseline.hash) : 'not configured'}</span></div>
        <div><strong>Selected</strong><span>{selectedRows.length}</span></div>
        <div><strong>Drones</strong><span>{rows.length}</span></div>
      </section>

      <SidecarStatusTable
        rows={rows}
        selected={selected}
        includeUnreachable={includeUnreachable}
        itemKind={itemKind}
        onToggleSelected={toggleSelected}
        onOpenNode={(row) => setDialog({ type: 'node', row })}
      />

      <SidecarProfileDialog config={config} table={table} dialog={dialog} closeDialog={closeDialog} />

      {dialog?.type === 'promote-confirm' && (
        <Modal title="Promote Reference Draft" icon={FaFileExport} onClose={closeDialog}>
          {modalError && <div className="fleet-sidecar__alert in-modal">{modalError}</div>}
          <DetailGrid
            items={[
              ['Reference drone', dialog.row?.hw_id],
              ['Presence', `${dialog.row?.presence?.state || 'unknown'} (${formatAge(dialog.row?.presence)})`],
              ['Local hash', shortHash(dialog.row?.local_hash)],
              ['Drift', dialog.row?.drift_state],
              [itemKind === 'mavlink' ? 'Endpoints' : 'Profiles', dialog.row?.profile_count],
            ]}
          />
          <div className="fleet-sidecar__callout">
            This generates a sanitized reference draft from the selected node. It does not write the repo baseline.
          </div>
          <div className="fleet-sidecar__confirm">
            <label><input type="checkbox" checked={ack} onChange={(event) => setAck(event.target.checked)} /> Acknowledge reference selection</label>
            <input value={confirmText} onChange={(event) => setConfirmText(event.target.value)} placeholder="PROMOTE" aria-label="Type PROMOTE" />
            <button type="button" onClick={confirmPromoteDraft} disabled={loading || !ack || confirmText !== 'PROMOTE'}>
              <FaFileExport aria-hidden="true" /> Generate Draft
            </button>
          </div>
        </Modal>
      )}

      {dialog?.type === 'promote-result' && (
        <Modal title="Reference Draft Generated" icon={FaFileExport} onClose={closeDialog}>
          <DetailGrid
            items={[
              ['Reference drone', dialog.row?.hw_id],
              ['Repo baseline mutated', dialog.draft?.mutated_repo_baseline ? 'yes' : 'no'],
              ['Draft hash', shortHash(dialog.draft?.draft?.summary?.hash || dialog.draft?.draft?.hash)],
              [itemKind === 'mavlink' ? 'Endpoints' : 'Profiles', dialog.draft?.draft?.summary?.profile_count || dialog.draft?.draft?.profile_count],
            ]}
          />
          <ProfileList
            profiles={dialog.draft?.draft?.summary?.profiles || dialog.draft?.draft?.profiles || []}
            endpoints={dialog.draft?.draft?.summary?.endpoints || dialog.draft?.draft?.endpoints || []}
            itemKind={itemKind}
            emptyLabel={config.emptyLabel}
          />
        </Modal>
      )}

      {dialog?.type === 'job' && job && (
        <DryRunApplyDialog
          job={job}
          blockedResults={blockedResults}
          modalError={modalError}
          ack={ack}
          setAck={setAck}
          advancedAck={advancedAck}
          setAdvancedAck={setAdvancedAck}
          allowPartial={allowPartial}
          setAllowPartial={setAllowPartial}
          confirmText={confirmText}
          setConfirmText={setConfirmText}
          loading={loading}
          onApplyReconcile={applyReconcile}
          onApplyPolicy={applyPolicy}
          closeDialog={closeDialog}
        />
      )}
    </main>
  );
}
