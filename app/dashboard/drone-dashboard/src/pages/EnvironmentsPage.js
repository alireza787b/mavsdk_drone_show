import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FaCheckCircle,
  FaDownload,
  FaExclamationTriangle,
  FaFilter,
  FaInfoCircle,
  FaRedoAlt,
  FaSave,
  FaSearch,
  FaShieldAlt,
  FaSlidersH,
  FaUpload,
} from 'react-icons/fa';

import {
  ActionIconButton,
  DocsLink,
  EmptyState,
  MetricStrip,
  OperatorCard,
  OperatorNotice,
  PageShell,
  StatusBadge,
} from '../components/ui';
import {
  applyGcsEnvResponse,
  getEnvRegistryResponse,
  getFleetNodeEnvResponse,
  getGcsEnvResponse,
  getUnifiedGitStatusResponse,
  planFleetEnvResponse,
  updateFleetNodeEnvResponse,
  updateGcsEnvResponse,
} from '../services/gcsApiService';
import '../styles/EnvironmentsPage.css';

const DOMAIN_LABELS = {
  auth: 'Auth',
  connectivity: 'Connectivity',
  frontend: 'Frontend',
  git: 'Git',
  logging: 'Logging',
  mavlink: 'MAVLink',
  px4: 'PX4',
  runtime: 'Runtime',
  sitl: 'SITL',
  system: 'System',
};

function compactHash(value) {
  const text = String(value || '');
  return text.length > 12 ? text.slice(0, 12) : text || 'none';
}

function boolLabel(value) {
  const text = String(value).toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(text)) {
    return 'Enabled';
  }
  if (['false', '0', 'no', 'off'].includes(text)) {
    return 'Disabled';
  }
  return value === null || value === undefined || value === '' ? 'Default' : String(value);
}

function displayValue(entry) {
  if (entry.secret) {
    return entry.secret_configured ? 'Configured' : 'Unset';
  }
  if (!entry.value_present || entry.value === null || entry.value === undefined || entry.value === '') {
    return entry.default === null || entry.default === undefined || entry.default === '' ? 'Unset' : `Default: ${boolLabel(entry.default)}`;
  }
  return entry.value_type === 'boolean' ? boolLabel(entry.value) : String(entry.value);
}

function valueTone(entry) {
  if (entry.deprecated) {
    return 'warning';
  }
  if (entry.secret && entry.secret_configured) {
    return 'success';
  }
  if (!entry.value_present) {
    return 'muted';
  }
  return 'neutral';
}

function restartTone(restartRequired) {
  if (restartRequired === 'gcs') {
    return 'warning';
  }
  if (restartRequired === 'none') {
    return 'success';
  }
  return 'info';
}

function normalizeError(error, fallback) {
  return error?.response?.data?.detail || error?.message || fallback;
}

function downloadJson(filename, payload) {
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

function buildGcsEnvProfile(values) {
  return buildEnvProfile(values, { scope: 'gcs' });
}

function buildNodeEnvProfile(values, hwId) {
  return buildEnvProfile(values, { scope: 'node', hw_id: String(hwId || '') });
}

function buildEnvProfile(values, extra) {
  const entries = {};
  values.forEach((entry) => {
    if (!entry.editable || entry.secret || !entry.value_present) {
      return;
    }
    entries[entry.name] = entry.value === null || entry.value === undefined ? '' : String(entry.value);
  });

  return {
    version: 1,
    kind: 'mds-env-profile',
    ...extra,
    exported_at: new Date().toISOString(),
    entries,
  };
}

function parseEnvProfile(rawText, expectedScope) {
  const payload = JSON.parse(rawText);
  if (!payload || payload.kind !== 'mds-env-profile') {
    throw new Error('Profile kind must be mds-env-profile.');
  }
  if (payload.scope !== expectedScope) {
    throw new Error(`Only ${expectedScope.toUpperCase()} env profiles can be imported here.`);
  }
  if (!payload.entries || typeof payload.entries !== 'object' || Array.isArray(payload.entries)) {
    throw new Error('Profile entries must be an object.');
  }
  return Object.fromEntries(
    Object.entries(payload.entries)
      .filter(([key]) => typeof key === 'string' && key.trim())
      .map(([key, value]) => [key.trim(), value])
  );
}

function parseGcsEnvProfile(rawText) {
  return parseEnvProfile(rawText, 'gcs');
}

function parseNodeEnvProfile(rawText) {
  return parseEnvProfile(rawText, 'node');
}

function buildInitialDraft(entry) {
  if (entry.value_present && entry.value !== null && entry.value !== undefined) {
    return String(entry.value);
  }
  if (entry.default !== null && entry.default !== undefined) {
    return String(entry.default);
  }
  return '';
}

function EnvEntryDialog({ entry, busy, onSave, onClose }) {
  const [draft, setDraft] = useState(() => buildInitialDraft(entry));

  useEffect(() => {
    setDraft(buildInitialDraft(entry));
  }, [entry]);

  const allowedValues = Array.isArray(entry.allowed_values) ? entry.allowed_values : [];
  const inputId = `env-edit-${entry.name}`;
  const canEdit = Boolean(entry.editable && !entry.secret && !entry.deprecated);
  const reason = entry.deprecated
    ? `Retired${entry.replacement ? `; use ${entry.replacement}` : ''}.`
    : entry.secret
      ? 'Secret values are file-backed and are not edited in the browser.'
      : !entry.editable
        ? 'This value is controlled by bootstrap, deployment defaults, or a dedicated workflow.'
        : '';

  return (
    <div
      className="environments-page__dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onClose();
        }
      }}
    >
      <form
        className="environments-page__dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`${canEdit ? 'Edit' : 'View'} ${entry.name}`}
        onSubmit={(event) => {
          event.preventDefault();
          if (canEdit) {
            onSave(entry, draft);
          }
        }}
      >
        <header>
          <span>{canEdit ? <FaSlidersH aria-hidden="true" /> : <FaInfoCircle aria-hidden="true" />}</span>
          <div>
            <strong>{entry.title}</strong>
            <code>{entry.name}</code>
          </div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close environment editor">×</button>
        </header>
        {canEdit ? (
          <label htmlFor={inputId}>
            <span>Value</span>
            {entry.value_type === 'boolean' ? (
              <select id={inputId} value={draft} onChange={(event) => setDraft(event.target.value)} autoFocus>
                <option value="true">Enabled</option>
                <option value="false">Disabled</option>
              </select>
            ) : allowedValues.length ? (
              <select id={inputId} value={draft} onChange={(event) => setDraft(event.target.value)} autoFocus>
                {allowedValues.map((value) => (
                  <option key={String(value)} value={String(value)}>{String(value)}</option>
                ))}
              </select>
            ) : (
              <input
                id={inputId}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder={entry.default !== null && entry.default !== undefined ? `Default: ${entry.default}` : 'Set value'}
                autoFocus
              />
            )}
          </label>
        ) : (
          <div className="environments-page__readonly-value">
            <span>Current</span>
            <strong>{displayValue(entry)}</strong>
            {reason ? <small>{reason}</small> : null}
          </div>
        )}
        <dl>
          <div>
            <dt>Type</dt>
            <dd>{entry.value_type}</dd>
          </div>
          <div>
            <dt>Source</dt>
            <dd>{entry.source_of_truth}</dd>
          </div>
          <div>
            <dt>Apply</dt>
            <dd>{entry.apply_action}</dd>
          </div>
          <div>
            <dt>Docs</dt>
            <dd><DocsLink doc={{ label: 'Guide', docPath: entry.docs }} compact /></dd>
          </div>
        </dl>
        {entry.notes ? <p>{entry.notes}</p> : null}
        <footer>
          <button type="button" className="operator-button operator-button--ghost" onClick={onClose} disabled={busy}>
            {canEdit ? 'Cancel' : 'Close'}
          </button>
          {canEdit ? (
            <button type="submit" className="operator-button operator-button--primary" disabled={busy}>
              {busy ? 'Saving...' : 'Save'}
            </button>
          ) : null}
        </footer>
      </form>
    </div>
  );
}

function buildNodePlanDraft(entry) {
  if (!entry) {
    return '';
  }
  if (entry.default !== null && entry.default !== undefined && entry.default !== '') {
    return String(entry.default);
  }
  if (entry.value_type === 'boolean') {
    return 'true';
  }
  return '';
}

function NodeEnvPlanner({
  entries,
  rows,
  query,
  busy,
  setBusy,
  setNotice,
}) {
  const [keyName, setKeyName] = useState('');
  const [draft, setDraft] = useState('');
  const [targetMode, setTargetMode] = useState('all');
  const [plan, setPlan] = useState(null);

  const selectedEntry = useMemo(
    () => entries.find((entry) => entry.name === keyName) || entries[0] || null,
    [entries, keyName],
  );

  useEffect(() => {
    if (!selectedEntry) {
      setKeyName('');
      setDraft('');
      return;
    }
    if (keyName !== selectedEntry.name) {
      setKeyName(selectedEntry.name);
    }
    setDraft(buildNodePlanDraft(selectedEntry));
  }, [keyName, selectedEntry]);

  if (!entries.length) {
    return null;
  }

  const allowedValues = Array.isArray(selectedEntry?.allowed_values) ? selectedEntry.allowed_values : [];
  const targetRows = targetMode === 'visible' ? rows : [];
  const targetHwIds = targetRows
    .map((row) => row.hw_id || row.key)
    .filter((value) => value !== undefined && value !== null && String(value).trim());
  const targetLabel = targetMode === 'visible'
    ? `${targetHwIds.length} visible/reporting node(s)`
    : 'all configured/reporting nodes';

  const runPlan = async () => {
    if (!selectedEntry) {
      return;
    }
    setBusy(true);
    setPlan(null);
    try {
      const payload = {
        updates: { [selectedEntry.name]: draft },
        target_hw_ids: targetMode === 'visible' ? targetHwIds : [],
      };
      const response = await planFleetEnvResponse(payload);
      const data = response?.data || {};
      setPlan(data);
      setNotice({
        tone: data.blocked_count ? 'warning' : 'info',
        title: 'Fleet env dry-run complete',
        detail: `${data.target_count || 0} target(s), ${data.blocked_count || 0} blocked. Mutation is intentionally disabled in this release.`,
      });
    } catch (error) {
      setNotice({ tone: 'danger', title: 'Fleet env plan failed', detail: normalizeError(error, 'Could not validate fleet-node env plan.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <OperatorCard compact className="environments-page__node-planner" tone="info">
      <div className="environments-page__node-planner-main">
        <span><FaShieldAlt aria-hidden="true" /> Fleet env planner</span>
        <strong>Dry-run only</strong>
        <p>Validate node-side env changes before rollout. Apply stays blocked until identity-safe node mutation APIs are enabled.</p>
      </div>
      <div className="environments-page__node-planner-controls">
        <label>
          <span>Variable</span>
          <select value={selectedEntry?.name || ''} onChange={(event) => setKeyName(event.target.value)}>
            {entries.map((entry) => (
              <option key={entry.name} value={entry.name}>{entry.title} ({entry.name})</option>
            ))}
          </select>
        </label>
        <label>
          <span>Value</span>
          {selectedEntry?.value_type === 'boolean' ? (
            <select value={draft} onChange={(event) => setDraft(event.target.value)}>
              <option value="true">Enabled</option>
              <option value="false">Disabled</option>
            </select>
          ) : allowedValues.length ? (
            <select value={draft} onChange={(event) => setDraft(event.target.value)}>
              {allowedValues.map((value) => (
                <option key={String(value)} value={String(value)}>{String(value)}</option>
              ))}
            </select>
          ) : (
            <input value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Planned value" />
          )}
        </label>
        <label>
          <span>Targets</span>
          <select value={targetMode} onChange={(event) => setTargetMode(event.target.value)}>
            <option value="all">All reported</option>
            <option value="visible">Visible filter</option>
          </select>
        </label>
        <button type="button" className="operator-button operator-button--primary" onClick={runPlan} disabled={busy || (targetMode === 'visible' && !targetHwIds.length)}>
          Plan
        </button>
      </div>
      <small>
        Target: {targetLabel}{query ? ` · filter "${query}"` : ''}
      </small>
      {plan ? (
        <div className="environments-page__node-plan-result">
          <StatusBadge tone={plan.blocked_count ? 'warning' : 'success'}>
            {plan.target_count} target(s)
          </StatusBadge>
          <StatusBadge tone="muted">{plan.mutation_policy}</StatusBadge>
        </div>
      ) : null}
    </OperatorCard>
  );
}

function EnvImportDialog({ plan, busy, onConfirm, onClose }) {
  const scopeLabel = plan.scopeLabel || 'Env';
  return (
    <div
      className="environments-page__dialog"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onClose();
        }
      }}
    >
      <section
        className="environments-page__dialog-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`Import ${scopeLabel} environment profile`}
      >
        <header>
          <span><FaUpload aria-hidden="true" /></span>
          <div>
            <strong>Import {scopeLabel} Profile</strong>
            <code>{plan.updatedKeys.length} registry-approved key(s)</code>
          </div>
          <button type="button" onClick={onClose} disabled={busy} aria-label="Close import profile dialog">×</button>
        </header>
        <p>
          Dry-run validation passed. Confirming writes these values through the
          registry-controlled env API; secrets and wrong-scope keys remain blocked.
        </p>
        <div className="environments-page__profile-key-list" aria-label="Imported environment keys">
          {plan.updatedKeys.map((key) => (
            <StatusBadge key={key} tone="info">{key}</StatusBadge>
          ))}
        </div>
        {plan.restartRequired ? (
          <OperatorNotice tone="warning" title="Restart required" icon={<FaRedoAlt />}>
            {plan.scope === 'node'
              ? 'Restart or reconcile the node service after import so restart-sensitive values take effect.'
              : 'Apply the GCS env restart after import so restart-sensitive values take effect.'}
          </OperatorNotice>
        ) : null}
        {plan.warnings?.length ? (
          <OperatorNotice tone="warning" title="Import warnings" icon={<FaExclamationTriangle />}>
            {plan.warnings.join(' ')}
          </OperatorNotice>
        ) : null}
        <footer>
          <button type="button" className="operator-button operator-button--ghost" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="button" className="operator-button operator-button--primary" onClick={onConfirm} disabled={busy}>
            {busy ? 'Importing...' : 'Import'}
          </button>
        </footer>
      </section>
    </div>
  );
}

export default function EnvironmentsPage() {
  const importInputRef = useRef(null);
  const nodeImportInputRef = useRef(null);
  const [registry, setRegistry] = useState(null);
  const [gcsEnv, setGcsEnv] = useState(null);
  const [fleetStatus, setFleetStatus] = useState(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState('');
  const [selectedNodeEnv, setSelectedNodeEnv] = useState(null);
  const [nodeEnvLoading, setNodeEnvLoading] = useState(false);
  const [query, setQuery] = useState('');
  const [domain, setDomain] = useState('all');
  const [scope, setScope] = useState('gcs');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [editingEntry, setEditingEntry] = useState(null);
  const [importPlan, setImportPlan] = useState(null);
  const [notice, setNotice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async ({ preserveNotice = false } = {}) => {
    setLoading(true);
    try {
      const [registryResponse, envResponse] = await Promise.all([
        getEnvRegistryResponse(),
        getGcsEnvResponse(),
      ]);
      getUnifiedGitStatusResponse()
        .then((response) => setFleetStatus(response?.data || null))
        .catch(() => setFleetStatus(null));
      setRegistry(registryResponse?.data || null);
      setGcsEnv(envResponse?.data || null);
      if (!preserveNotice) {
        setNotice(null);
      }
    } catch (error) {
      setNotice({ tone: 'danger', title: 'Environment registry unavailable', detail: normalizeError(error, 'Could not load MDS environment metadata.') });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const loadNodeEnv = useCallback(async (hwId, { preserveNotice = false } = {}) => {
    if (!hwId) {
      setSelectedNodeEnv(null);
      return;
    }
    setNodeEnvLoading(true);
    try {
      const response = await getFleetNodeEnvResponse(hwId, {
        params: { include_hidden: showAdvanced },
      });
      setSelectedNodeEnv(response?.data || null);
      if (!preserveNotice) {
        setNotice(null);
      }
    } catch (error) {
      setSelectedNodeEnv(null);
      setNotice({
        tone: 'danger',
        title: `Drone ${hwId} env unavailable`,
        detail: normalizeError(error, 'Could not reach the selected drone env API.'),
      });
    } finally {
      setNodeEnvLoading(false);
    }
  }, [showAdvanced]);

  const values = useMemo(() => Array.isArray(gcsEnv?.values) ? gcsEnv.values : [], [gcsEnv]);
  const nodeRows = useMemo(() => {
    const statusById = fleetStatus?.git_status || {};
    return Object.entries(statusById).map(([key, value]) => ({
      key,
      ...value,
      env_runtime: value?.env_runtime || null,
    })).sort((a, b) => Number(a.pos_id || a.key) - Number(b.pos_id || b.key));
  }, [fleetStatus]);
  const domains = useMemo(() => {
    const domainSet = new Set(values.map((entry) => entry.domain).filter(Boolean));
    return ['all', ...Array.from(domainSet).sort()];
  }, [values]);
  const nodeEditableEntries = useMemo(() => {
    const registryEntries = Array.isArray(registry?.entries) ? registry.entries : [];
    return registryEntries
      .filter((entry) => entry.scope === 'node' && entry.editable && !entry.secret && !entry.deprecated)
      .sort((left, right) => {
        const domainCompare = String(left.domain || '').localeCompare(String(right.domain || ''));
        return domainCompare || String(left.title || left.name).localeCompare(String(right.title || right.name));
      });
  }, [registry]);

  const filteredValues = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return values.filter((entry) => {
      if (!showAdvanced && ['advanced', 'diagnostic', 'hidden'].includes(entry.ui_visibility)) {
        return false;
      }
      if (domain !== 'all' && entry.domain !== domain) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [
        entry.name,
        entry.title,
        entry.domain,
        entry.value_type,
        entry.notes,
        entry.docs,
        displayValue(entry),
      ].join(' ').toLowerCase().includes(normalizedQuery);
    });
  }, [domain, query, showAdvanced, values]);

  const filteredNodeRows = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return nodeRows;
    }
    const matches = nodeRows.filter((row) => [
      row.pos_id,
      row.hw_id,
      row.ip,
      row.env_runtime?.runtime_mode,
      row.env_runtime?.runtime_mode_source,
      row.env_runtime?.registry_hash,
      row.env_runtime?.local_env_path,
      row.env_runtime?.node_identity_path,
      ...(row.env_runtime?.unknown_keys || []),
      ...(row.env_runtime?.deprecated_keys || []),
    ].join(' ').toLowerCase().includes(normalizedQuery));
    return matches.length ? matches : nodeRows;
  }, [nodeRows, query]);

  useEffect(() => {
    if (scope !== 'nodes') {
      return;
    }
    const available = filteredNodeRows
      .map((row) => String(row.hw_id || row.key || '').trim())
      .filter(Boolean);
    if (!available.length) {
      setSelectedNodeKey('');
      setSelectedNodeEnv(null);
      return;
    }
    if (!selectedNodeKey || !available.includes(selectedNodeKey)) {
      setSelectedNodeKey(available[0]);
    }
  }, [filteredNodeRows, scope, selectedNodeKey]);

  const selectedNode = useMemo(
    () => filteredNodeRows.find((row) => String(row.hw_id || row.key || '').trim() === selectedNodeKey) || null,
    [filteredNodeRows, selectedNodeKey],
  );

  useEffect(() => {
    if (scope !== 'nodes' || !selectedNodeKey) {
      return;
    }
    loadNodeEnv(selectedNodeKey);
  }, [loadNodeEnv, scope, selectedNodeKey]);

  const groupedValues = useMemo(() => filteredValues.reduce((groups, entry) => {
    const key = entry.domain || 'system';
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(entry);
    return groups;
  }, {}), [filteredValues]);

  const selectedNodeValues = useMemo(() => (
    Array.isArray(selectedNodeEnv?.values) ? selectedNodeEnv.values : []
  ), [selectedNodeEnv]);

  const filteredSelectedNodeValues = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return selectedNodeValues.filter((entry) => {
      if (!showAdvanced && ['advanced', 'diagnostic', 'hidden'].includes(entry.ui_visibility)) {
        return false;
      }
      if (!normalizedQuery) {
        return true;
      }
      return [
        entry.name,
        entry.title,
        entry.domain,
        entry.value_type,
        entry.notes,
        entry.docs,
        displayValue(entry),
      ].join(' ').toLowerCase().includes(normalizedQuery);
    });
  }, [query, selectedNodeValues, showAdvanced]);

  const groupedSelectedNodeValues = useMemo(() => filteredSelectedNodeValues.reduce((groups, entry) => {
    const key = entry.domain || 'system';
    if (!groups[key]) {
      groups[key] = [];
    }
    groups[key].push(entry);
    return groups;
  }, {}), [filteredSelectedNodeValues]);

  const restartSensitiveCount = values.filter((entry) => entry.restart_required === 'gcs' && entry.editable).length;
  const editableCount = values.filter((entry) => entry.editable && !entry.secret).length;
  const unknownCount = Array.isArray(gcsEnv?.unknown_keys) ? gcsEnv.unknown_keys.length : 0;
  const deprecatedCount = Array.isArray(gcsEnv?.deprecated_keys) ? gcsEnv.deprecated_keys.length : 0;
  const registryHash = registry?.registry_hash || gcsEnv?.registry_hash || '';
  const nodeDriftCount = nodeRows.filter((row) => {
    const envRuntime = row.env_runtime || {};
    return (envRuntime.unknown_keys || []).length
      || (envRuntime.deprecated_keys || []).length
      || (envRuntime.registry_hash && registryHash && envRuntime.registry_hash !== registryHash);
  }).length;
  const configPath = gcsEnv?.config_path || 'GCS env file';

  const summaryItems = [
    {
      key: 'registry',
      label: 'Registry',
      value: compactHash(registryHash),
      detail: `v${registry?.version || gcsEnv?.registry_version || '?'}`,
      icon: <FaShieldAlt />,
      tone: 'info',
    },
    {
      key: 'editable',
      label: 'Editable',
      value: editableCount,
      detail: 'GCS host keys',
      icon: <FaSlidersH />,
      tone: editableCount ? 'success' : 'muted',
    },
    {
      key: 'restart',
      label: 'Restart',
      value: restartSensitiveCount,
      detail: 'restart-sensitive',
      icon: <FaRedoAlt />,
      tone: restartSensitiveCount ? 'warning' : 'success',
    },
    {
      key: 'drift',
      label: 'Drift',
      value: scope === 'nodes' ? nodeDriftCount : unknownCount + deprecatedCount,
      detail: scope === 'nodes' ? `${nodeRows.length} reported nodes` : `${unknownCount} unknown · ${deprecatedCount} retired`,
      icon: <FaExclamationTriangle />,
      tone: (scope === 'nodes' ? nodeDriftCount : unknownCount || deprecatedCount) ? 'warning' : 'success',
    },
  ];

  const saveEntry = async (entry, value) => {
    setBusy(true);
    try {
      const targetScope = editingEntry?.scope || 'gcs';
      const response = targetScope === 'node'
        ? await updateFleetNodeEnvResponse(selectedNodeKey, { updates: { [entry.name]: value } })
        : await updateGcsEnvResponse({ updates: { [entry.name]: value } });
      const data = response?.data || {};
      setEditingEntry(null);
      setNotice({
        tone: data.restart_required ? 'warning' : 'success',
        title: data.restart_required ? 'Saved. Apply pending.' : 'Environment saved',
        detail: data.changed_keys?.length
          ? `${data.changed_keys.join(', ')} updated in ${data.config_path}.`
          : 'No file change was required.',
      });
      if (targetScope === 'node') {
        await loadNodeEnv(selectedNodeKey, { preserveNotice: true });
      } else {
        await refresh({ preserveNotice: true });
      }
    } catch (error) {
      setNotice({ tone: 'danger', title: 'Save failed', detail: normalizeError(error, `Could not update ${entry.name}.`) });
    } finally {
      setBusy(false);
    }
  };

  const applyEnv = async () => {
    setBusy(true);
    try {
      const response = await applyGcsEnvResponse();
      const data = response?.data || {};
      setNotice({
        tone: data.status === 'scheduled' ? 'success' : 'info',
        title: data.message || 'Environment apply completed',
        detail: data.scheduled ? `Restart scheduled in ${data.restart_delay_ms || 0} ms.` : 'No restart was scheduled.',
      });
    } catch (error) {
      setNotice({ tone: 'danger', title: 'Apply failed', detail: normalizeError(error, 'Could not schedule the GCS restart.') });
    } finally {
      setBusy(false);
    }
  };

  const exportGcsProfile = () => {
    const profile = buildGcsEnvProfile(values);
    downloadJson('mds-gcs-env-profile.json', profile);
    setNotice({
      tone: 'success',
      title: 'GCS env profile exported',
      detail: `${Object.keys(profile.entries).length} editable non-secret value(s) exported.`,
    });
  };

  const exportNodeProfile = () => {
    if (!selectedNodeKey || !selectedNodeValues.length) {
      return;
    }
    const profile = buildNodeEnvProfile(selectedNodeValues, selectedNodeKey);
    downloadJson(`mds-node-${selectedNodeKey}-env-profile.json`, profile);
    setNotice({
      tone: 'success',
      title: `Drone ${selectedNodeKey} env profile exported`,
      detail: `${Object.keys(profile.entries).length} editable non-secret value(s) exported.`,
    });
  };

  const handleImportFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = async () => {
      setBusy(true);
      try {
        const updates = parseGcsEnvProfile(String(reader.result || ''));
        const response = await updateGcsEnvResponse({ updates, dry_run: true });
        const data = response?.data || {};
        setImportPlan({
          scope: 'gcs',
          scopeLabel: 'GCS',
          updates,
          updatedKeys: data.updated_keys || Object.keys(updates),
          restartRequired: Boolean(data.restart_required),
          warnings: data.warnings || [],
        });
        setNotice(null);
      } catch (error) {
        setNotice({ tone: 'danger', title: 'Profile import rejected', detail: normalizeError(error, error.message || 'Could not read the selected profile.') });
      } finally {
        setBusy(false);
      }
    };
    reader.onerror = () => {
      setNotice({ tone: 'danger', title: 'Profile import failed', detail: 'Could not read the selected file.' });
    };
    reader.readAsText(file);
  };

  const handleNodeImportFile = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !selectedNodeKey) {
      return;
    }

    const reader = new FileReader();
    reader.onload = async () => {
      setBusy(true);
      try {
        const updates = parseNodeEnvProfile(String(reader.result || ''));
        const response = await updateFleetNodeEnvResponse(selectedNodeKey, { updates, dry_run: true });
        const data = response?.data || {};
        setImportPlan({
          scope: 'node',
          scopeLabel: `Drone ${selectedNodeKey}`,
          updates,
          updatedKeys: data.updated_keys || Object.keys(updates),
          restartRequired: Boolean(data.restart_required),
          warnings: data.warnings || [],
        });
        setNotice(null);
      } catch (error) {
        setNotice({ tone: 'danger', title: 'Node profile rejected', detail: normalizeError(error, error.message || 'Could not read the selected profile.') });
      } finally {
        setBusy(false);
      }
    };
    reader.onerror = () => {
      setNotice({ tone: 'danger', title: 'Node profile import failed', detail: 'Could not read the selected file.' });
    };
    reader.readAsText(file);
  };

  const confirmImportProfile = async () => {
    if (!importPlan) {
      return;
    }
    setBusy(true);
    try {
      const response = importPlan.scope === 'node'
        ? await updateFleetNodeEnvResponse(selectedNodeKey, { updates: importPlan.updates })
        : await updateGcsEnvResponse({ updates: importPlan.updates });
      const data = response?.data || {};
      setImportPlan(null);
      setNotice({
        tone: data.restart_required ? 'warning' : 'success',
        title: data.restart_required ? 'Profile imported. Apply pending.' : 'Profile imported',
        detail: data.changed_keys?.length
          ? `${data.changed_keys.join(', ')} updated in ${data.config_path}.`
          : 'Profile already matched the persisted env file.',
      });
      if (importPlan.scope === 'node') {
        await loadNodeEnv(selectedNodeKey, { preserveNotice: true });
      } else {
        await refresh({ preserveNotice: true });
      }
    } catch (error) {
      setNotice({ tone: 'danger', title: 'Profile import failed', detail: normalizeError(error, 'Could not import the selected profile.') });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageShell
      className="environments-page"
      eyebrow="Configuration Control"
      title="Environments"
      subtitle="Registry-backed GCS variables and single-node field repair. Bulk fleet rollout stays dry-run."
      icon={<FaSlidersH />}
      docsRoute="/environments"
      status={(
        <div className="environments-page__status">
          <StatusBadge tone={gcsEnv?.config_present ? 'success' : 'warning'}>{gcsEnv?.config_present ? 'env file' : 'missing file'}</StatusBadge>
          <StatusBadge tone="muted">{configPath}</StatusBadge>
        </div>
      )}
      actions={(
        <div className="environments-page__actions">
          <DocsLink
            doc={{ label: 'Registry', docPath: 'docs/reference/mds-environment-registry.md' }}
            compact
          />
          <DocsLink
            doc={{ label: 'Table', docPath: 'docs/reference/mds-environment-registry.generated.md' }}
            compact
          />
          <ActionIconButton icon={<FaRedoAlt />} label="Refresh environments" onClick={refresh} disabled={busy || loading} />
          {scope === 'gcs' ? (
            <>
              <ActionIconButton icon={<FaUpload />} label="Import GCS env profile" onClick={() => importInputRef.current?.click()} disabled={busy || loading}>
                Import
              </ActionIconButton>
              <ActionIconButton icon={<FaDownload />} label="Export GCS env profile" onClick={exportGcsProfile} disabled={busy || loading || !values.length}>
                Export
              </ActionIconButton>
              <ActionIconButton icon={<FaSave />} label="Apply GCS environment restart" tone="warning" onClick={applyEnv} disabled={busy || loading}>
                Apply
              </ActionIconButton>
            </>
          ) : (
            <>
              <ActionIconButton icon={<FaUpload />} label="Import selected drone env profile" onClick={() => nodeImportInputRef.current?.click()} disabled={busy || nodeEnvLoading || !selectedNodeKey}>
                Import
              </ActionIconButton>
              <ActionIconButton icon={<FaDownload />} label="Export selected drone env profile" onClick={exportNodeProfile} disabled={busy || nodeEnvLoading || !selectedNodeValues.length}>
                Export
              </ActionIconButton>
            </>
          )}
          <input
            ref={importInputRef}
            type="file"
            accept="application/json,.json"
            className="environments-page__file-input"
            onChange={handleImportFile}
            aria-label="Import GCS env profile file"
          />
          <input
            ref={nodeImportInputRef}
            type="file"
            accept="application/json,.json"
            className="environments-page__file-input"
            onChange={handleNodeImportFile}
            aria-label="Import selected drone env profile file"
          />
        </div>
      )}
    >
      {notice ? (
        <OperatorNotice tone={notice.tone} title={notice.title} icon={notice.tone === 'danger' ? <FaExclamationTriangle /> : <FaCheckCircle />}>
          {notice.detail}
        </OperatorNotice>
      ) : null}

      {gcsEnv?.warnings?.length ? (
        <OperatorNotice tone="warning" title="Registry warnings" icon={<FaExclamationTriangle />}>
          <span>{gcsEnv.warnings.join(' ')}</span>
          {gcsEnv.unknown_keys?.length || gcsEnv.deprecated_keys?.length ? (
            <span className="environments-page__warning-keys">
              {(gcsEnv.unknown_keys || []).map((key) => <StatusBadge key={`unknown-${key}`} tone="warning">{key}</StatusBadge>)}
              {(gcsEnv.deprecated_keys || []).map((key) => <StatusBadge key={`retired-${key}`} tone="muted">{key} retired</StatusBadge>)}
            </span>
          ) : null}
        </OperatorNotice>
      ) : null}

      <MetricStrip items={summaryItems} label="Environment registry summary" />

      <section className="environments-page__toolbar" aria-label="Environment filters">
        <div className="environments-page__scope-tabs" aria-label="Environment scopes">
          <button type="button" className={scope === 'gcs' ? 'is-active' : ''} onClick={() => setScope('gcs')}>
            GCS Host
          </button>
          <button type="button" className={scope === 'nodes' ? 'is-active' : ''} onClick={() => setScope('nodes')}>
            Fleet Nodes
          </button>
        </div>
        <label>
          <span><FaSearch aria-hidden="true" /> Search</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="MDS_MODE, auth, port..." />
        </label>
        <label className={scope === 'gcs' ? '' : 'is-hidden'}>
          <span><FaFilter aria-hidden="true" /> Domain</span>
          <select value={domain} onChange={(event) => setDomain(event.target.value)}>
            {domains.map((item) => (
              <option key={item} value={item}>{item === 'all' ? 'All domains' : DOMAIN_LABELS[item] || item}</option>
            ))}
          </select>
        </label>
        <button type="button" className="operator-button operator-button--ghost" onClick={() => setShowAdvanced((current) => !current)}>
          {showAdvanced ? 'Operator view' : 'Advanced'}
        </button>
      </section>

      {loading && scope === 'gcs' ? (
        <EmptyState icon={<FaSlidersH />} title="Loading environments" detail="Reading the registry and GCS host env file." />
      ) : null}

      {!loading && scope === 'gcs' && filteredValues.length === 0 ? (
        <EmptyState icon={<FaSearch />} title="No matching variables" detail="Change the search, domain, or advanced filter." />
      ) : null}

      {!loading && scope === 'gcs' && filteredValues.length ? (
        <div className="environments-page__groups">
          {Object.entries(groupedValues).map(([groupDomain, entries]) => (
            <section key={groupDomain} className="environments-page__group" aria-label={`${DOMAIN_LABELS[groupDomain] || groupDomain} environment variables`}>
              <header>
                <h2>{DOMAIN_LABELS[groupDomain] || groupDomain}</h2>
                <StatusBadge tone="muted">{entries.length}</StatusBadge>
              </header>
              <div className="environments-page__grid">
                {entries.map((entry) => (
                  <OperatorCard key={entry.name} compact className="environments-page__entry">
                    <div className="environments-page__entry-main">
                      <span className="environments-page__entry-title">{entry.title}</span>
                      <code>{entry.name}</code>
                    </div>
                    <div className="environments-page__entry-value">
                      <StatusBadge tone={valueTone(entry)}>{displayValue(entry)}</StatusBadge>
                      <StatusBadge tone={restartTone(entry.restart_required)}>{entry.restart_required}</StatusBadge>
                    </div>
                    <div className="environments-page__entry-actions">
                      <span aria-label={entry.notes || `${entry.name} value type`}>{entry.value_type}</span>
                      <ActionIconButton
                        icon={entry.editable && !entry.secret && !entry.deprecated ? <FaSlidersH /> : <FaInfoCircle />}
                        label={`${entry.editable && !entry.secret && !entry.deprecated ? 'Edit' : 'View'} ${entry.name}`}
                        size="sm"
                        onClick={() => setEditingEntry({ scope: 'gcs', entry })}
                        disabled={busy}
                      />
                    </div>
                  </OperatorCard>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : null}

      {!loading && scope === 'nodes' ? (
        <NodeEnvPlanner
          entries={nodeEditableEntries}
          rows={filteredNodeRows}
          query={query}
          busy={busy}
          setBusy={setBusy}
          setNotice={setNotice}
        />
      ) : null}

      {!loading && scope === 'nodes' && filteredNodeRows.length === 0 ? (
        <EmptyState icon={<FaSearch />} title="No node env reports" detail="Fleet-node env posture appears after drone git-status polling returns." />
      ) : null}

      {!loading && scope === 'nodes' && filteredNodeRows.length ? (
        <section className="environments-page__node-workbench" aria-label="Fleet node environment editor">
          <div className="environments-page__node-grid" aria-label="Fleet node environment posture">
            {filteredNodeRows.map((row) => {
              const envRuntime = row.env_runtime || {};
              const nodeKey = String(row.hw_id || row.key || '').trim();
              const hashMismatch = Boolean(envRuntime.registry_hash && registryHash && envRuntime.registry_hash !== registryHash);
              const drift = hashMismatch || (envRuntime.unknown_keys || []).length || (envRuntime.deprecated_keys || []).length;
              return (
                <OperatorCard
                  key={row.key}
                  as="button"
                  type="button"
                  compact
                  selected={nodeKey === selectedNodeKey}
                  className="environments-page__node-card"
                  tone={drift ? 'warning' : 'neutral'}
                  onClick={() => setSelectedNodeKey(nodeKey)}
                >
                  <header>
                    <div>
                      <span>Drone {row.pos_id || row.key}</span>
                      <strong>HW {row.hw_id || row.key}</strong>
                    </div>
                    <StatusBadge tone={drift ? 'warning' : 'success'}>{drift ? 'Drift' : 'Clean'}</StatusBadge>
                  </header>
                  <dl>
                    <div>
                      <dt>Mode</dt>
                      <dd>{envRuntime.runtime_mode || 'unknown'}</dd>
                    </div>
                    <div>
                      <dt>Registry</dt>
                      <dd>{compactHash(envRuntime.registry_hash)}</dd>
                    </div>
                    <div>
                      <dt>Keys</dt>
                      <dd>{envRuntime.configured_node_key_count ?? 0}/{envRuntime.registered_node_key_count ?? 0}</dd>
                    </div>
                    <div>
                      <dt>Drift</dt>
                      <dd>{(envRuntime.unknown_keys || []).length + (envRuntime.deprecated_keys || []).length + (hashMismatch ? 1 : 0)}</dd>
                    </div>
                  </dl>
                  <p aria-label="Node environment details">
                    {envRuntime.local_env_present ? envRuntime.local_env_path : 'local.env missing'} · {envRuntime.node_identity_present ? 'identity ok' : 'identity missing'}
                  </p>
                </OperatorCard>
              );
            })}
          </div>

          <OperatorCard compact className="environments-page__node-editor" tone={selectedNodeEnv?.warnings?.length ? 'warning' : 'neutral'}>
            <header className="environments-page__node-editor-header">
              <div>
                <span>Single Node Env</span>
                <strong>{selectedNode ? `Drone ${selectedNode.pos_id || selectedNode.key} · HW ${selectedNode.hw_id || selectedNode.key}` : 'Select a node'}</strong>
              </div>
              <div>
                <StatusBadge tone={selectedNodeEnv?.config_present ? 'success' : 'warning'}>
                  {selectedNodeEnv?.config_present ? 'local.env' : 'missing'}
                </StatusBadge>
                <StatusBadge tone="muted">{compactHash(selectedNodeEnv?.registry_hash)}</StatusBadge>
                <ActionIconButton icon={<FaRedoAlt />} label="Reload selected drone env" size="sm" onClick={() => loadNodeEnv(selectedNodeKey)} disabled={!selectedNodeKey || nodeEnvLoading} />
              </div>
            </header>

            {nodeEnvLoading ? (
              <EmptyState icon={<FaSlidersH />} title="Loading node env" detail="Reading the selected drone through the GCS proxy." />
            ) : null}

            {!nodeEnvLoading && selectedNodeEnv?.warnings?.length ? (
              <OperatorNotice tone="warning" title="Node env warnings" icon={<FaExclamationTriangle />}>
                {selectedNodeEnv.warnings.join(' ')}
              </OperatorNotice>
            ) : null}

            {!nodeEnvLoading && selectedNodeEnv && filteredSelectedNodeValues.length === 0 ? (
              <EmptyState icon={<FaSearch />} title="No node variables" detail="Change the search or advanced filter." />
            ) : null}

            {!nodeEnvLoading && filteredSelectedNodeValues.length ? (
              <div className="environments-page__groups environments-page__groups--embedded">
                {Object.entries(groupedSelectedNodeValues).map(([groupDomain, entries]) => (
                  <section key={groupDomain} className="environments-page__group" aria-label={`${DOMAIN_LABELS[groupDomain] || groupDomain} node environment variables`}>
                    <header>
                      <h2>{DOMAIN_LABELS[groupDomain] || groupDomain}</h2>
                      <StatusBadge tone="muted">{entries.length}</StatusBadge>
                    </header>
                    <div className="environments-page__grid environments-page__grid--node">
                      {entries.map((entry) => (
                        <OperatorCard key={entry.name} compact className="environments-page__entry">
                          <div className="environments-page__entry-main">
                            <span className="environments-page__entry-title">{entry.title}</span>
                            <code>{entry.name}</code>
                          </div>
                          <div className="environments-page__entry-value">
                            <StatusBadge tone={valueTone(entry)}>{displayValue(entry)}</StatusBadge>
                            <StatusBadge tone={restartTone(entry.restart_required)}>{entry.restart_required}</StatusBadge>
                          </div>
                          <div className="environments-page__entry-actions">
                            <span aria-label={entry.notes || `${entry.name} value type`}>{entry.value_type}</span>
                            <ActionIconButton
                              icon={entry.editable && !entry.secret && !entry.deprecated ? <FaSlidersH /> : <FaInfoCircle />}
                              label={`${entry.editable && !entry.secret && !entry.deprecated ? 'Edit' : 'View'} ${entry.name}`}
                              size="sm"
                              onClick={() => setEditingEntry({ scope: 'node', entry })}
                              disabled={busy || !selectedNodeKey}
                            />
                          </div>
                        </OperatorCard>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            ) : null}
          </OperatorCard>
        </section>
      ) : null}

      {editingEntry ? (
        <EnvEntryDialog entry={editingEntry.entry} busy={busy} onSave={saveEntry} onClose={() => setEditingEntry(null)} />
      ) : null}

      {importPlan ? (
        <EnvImportDialog
          plan={importPlan}
          busy={busy}
          onConfirm={confirmImportProfile}
          onClose={() => setImportPlan(null)}
        />
      ) : null}
    </PageShell>
  );
}
