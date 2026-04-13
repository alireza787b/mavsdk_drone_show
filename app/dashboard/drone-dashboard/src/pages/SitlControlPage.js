import React, { useEffect, useMemo, useState } from 'react';
import {
  FaCube,
  FaDocker,
  FaHdd,
  FaInfoCircle,
  FaMemory,
  FaMicrochip,
  FaPlay,
  FaRedoAlt,
  FaServer,
  FaStop,
  FaStream,
  FaSyncAlt,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import {
  getSitlControlHost,
  getSitlControlImages,
  getSitlControlInstanceLogs,
  getSitlControlInstances,
  getSitlControlOperation,
  getSitlControlOperations,
  getSitlControlPolicy,
  reconcileSitlFleet,
  removeSitlInstance,
  restartSitlInstance,
} from '../services/sitlControlService';
import '../styles/SitlControlPage.css';

const INVENTORY_POLL_INTERVAL_MS = 10000;
const OPERATION_POLL_INTERVAL_MS = 2000;
const LOG_TAIL_OPTIONS = [80, 200, 500];
const TERMINAL_OPERATION_STATES = new Set(['failed', 'succeeded']);
const ENABLE_BACKGROUND_POLLING = process.env.NODE_ENV !== 'test';

function formatBytes(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    return '—';
  }
  if (numeric === 0) {
    return '0 B';
  }

  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const exponent = Math.min(Math.floor(Math.log(numeric) / Math.log(1024)), units.length - 1);
  const scaled = numeric / (1024 ** exponent);
  return `${scaled >= 10 || exponent === 0 ? scaled.toFixed(0) : scaled.toFixed(1)} ${units[exponent]}`;
}

function formatTimestamp(value) {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}

function formatDockerTone(dockerState) {
  if (!dockerState?.available || !dockerState?.daemon_reachable) {
    return 'warning';
  }
  return 'good';
}

function formatInstanceTone(instance) {
  if (instance?.state === 'running') {
    return 'good';
  }
  if (instance?.state === 'created' || instance?.state === 'restarting') {
    return 'warning';
  }
  return 'muted';
}

function formatOperationTone(operation) {
  if (operation?.status === 'failed') {
    return 'warning';
  }
  if (operation?.status === 'succeeded') {
    return 'good';
  }
  if (operation?.status === 'running' || operation?.status === 'accepted') {
    return 'default';
  }
  return 'muted';
}

function getPrimaryInstanceIp(instance, preferredNetworkName) {
  if (!instance?.ip_addresses || typeof instance.ip_addresses !== 'object') {
    return 'No IP';
  }
  if (preferredNetworkName && instance.ip_addresses[preferredNetworkName]) {
    return instance.ip_addresses[preferredNetworkName];
  }
  const fallback = Object.values(instance.ip_addresses).find((value) => value);
  return fallback || 'No IP';
}

function SummaryCard({ icon: Icon, label, value, tone = 'default', detail = '' }) {
  return (
    <div className={`sitl-summary-card sitl-summary-card--${tone}`}>
      <div className="sitl-summary-card__icon">
        <Icon />
      </div>
      <div className="sitl-summary-card__body">
        <span>{label}</span>
        <strong>{value}</strong>
        {detail ? <small>{detail}</small> : null}
      </div>
    </div>
  );
}

function SectionHeader({ title, detail = '', action = null }) {
  return (
    <div className="sitl-section-header">
      <div>
        <h2>{title}</h2>
        {detail ? <p>{detail}</p> : null}
      </div>
      {action}
    </div>
  );
}

function EmptyState({ title, detail }) {
  return (
    <div className="sitl-empty-state">
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function SitlControlPage() {
  const [policy, setPolicy] = useState(null);
  const [host, setHost] = useState(null);
  const [images, setImages] = useState([]);
  const [instances, setInstances] = useState([]);
  const [operations, setOperations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [selectedOperationId, setSelectedOperationId] = useState(null);
  const [selectedOperation, setSelectedOperation] = useState(null);
  const [operationLoading, setOperationLoading] = useState(false);
  const [logTail, setLogTail] = useState(200);
  const [logLines, setLogLines] = useState([]);
  const [logLoading, setLogLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [reconcileForm, setReconcileForm] = useState({
    targetCount: 3,
    imageRef: '',
    startId: 1,
    startIp: 2,
    subnet: '',
    dockerNetworkName: '',
    gitSyncEnabled: true,
    requirementsSyncEnabled: true,
  });

  useEffect(() => {
    let mounted = true;

    const loadInventory = async ({ background = false } = {}) => {
      if (!background) {
        setLoading(true);
      } else {
        setRefreshing(true);
      }

      try {
        const [policyData, hostData, imageData, instanceData, operationData] = await Promise.all([
          getSitlControlPolicy(),
          getSitlControlHost(),
          getSitlControlImages(),
          getSitlControlInstances(),
          getSitlControlOperations(),
        ]);

        if (!mounted) {
          return;
        }

        const nextImages = Array.isArray(imageData?.images) ? imageData.images : [];
        const nextInstances = Array.isArray(instanceData?.instances) ? instanceData.instances : [];
        const nextOperations = Array.isArray(operationData?.operations) ? operationData.operations : [];

        setPolicy(policyData);
        setHost(hostData?.host || null);
        setImages(nextImages);
        setInstances(nextInstances);
        setOperations(nextOperations);
        setSelectedInstance((current) => {
          if (current?.name) {
            return nextInstances.find((instance) => instance.name === current.name) || nextInstances[0] || null;
          }
          return nextInstances[0] || null;
        });
        setSelectedOperationId((current) => {
          if (current && nextOperations.some((operation) => operation.operation_id === current)) {
            return current;
          }
          return nextOperations[0]?.operation_id || null;
        });
      } catch (error) {
        if (mounted) {
          toast.error(`Failed to load SITL control inventory: ${error.message}`);
        }
      } finally {
        if (!mounted) {
          return;
        }
        setLoading(false);
        setRefreshing(false);
      }
    };

    loadInventory();
    const timer = ENABLE_BACKGROUND_POLLING
      ? setInterval(() => loadInventory({ background: true }), INVENTORY_POLL_INTERVAL_MS)
      : null;

    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [refreshTick]);

  useEffect(() => {
    setReconcileForm((current) => ({
      targetCount: current.targetCount || Math.max(instances.length, 3) || 3,
      imageRef: current.imageRef || images[0]?.primary_tag || policy?.defaults?.default_image || '',
      startId: current.startId || 1,
      startIp: current.startIp || 2,
      subnet: current.subnet,
      dockerNetworkName: current.dockerNetworkName || policy?.defaults?.default_network_name || '',
      gitSyncEnabled: typeof current.gitSyncEnabled === 'boolean'
        ? current.gitSyncEnabled
        : Boolean(policy?.defaults?.default_git_sync),
      requirementsSyncEnabled: typeof current.requirementsSyncEnabled === 'boolean'
        ? current.requirementsSyncEnabled
        : Boolean(policy?.defaults?.default_requirements_sync),
    }));
  }, [images, instances.length, policy]);

  useEffect(() => {
    let mounted = true;

    const loadLogs = async () => {
      if (!selectedInstance?.name) {
        setLogLines([]);
        return;
      }
      setLogLoading(true);
      try {
        const payload = await getSitlControlInstanceLogs(selectedInstance.name, { tail: logTail });
        if (mounted) {
          setLogLines(Array.isArray(payload?.lines) ? payload.lines : []);
        }
      } catch (error) {
        if (mounted) {
          setLogLines([]);
          toast.error(`Failed to load SITL logs for ${selectedInstance.name}: ${error.message}`);
        }
      } finally {
        if (mounted) {
          setLogLoading(false);
        }
      }
    };

    loadLogs();
    return () => {
      mounted = false;
    };
  }, [selectedInstance, logTail]);

  useEffect(() => {
    if (!selectedOperationId) {
      setSelectedOperation(null);
      return undefined;
    }

    let mounted = true;
    let timer = null;
    let terminalRefreshSent = false;

    const loadOperation = async () => {
      setOperationLoading(true);
      try {
        const payload = await getSitlControlOperation(selectedOperationId);
        if (!mounted) {
          return;
        }
        setSelectedOperation(payload);
        setOperations((current) => {
          const others = current.filter((item) => item.operation_id !== payload.operation_id);
          return [payload, ...others].slice(0, 20);
        });

        if (TERMINAL_OPERATION_STATES.has(payload.status) && !terminalRefreshSent) {
          terminalRefreshSent = true;
          setRefreshTick((current) => current + 1);
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
        }
      } catch (error) {
        if (mounted) {
          toast.error(`Failed to load SITL operation ${selectedOperationId}: ${error.message}`);
        }
      } finally {
        if (mounted) {
          setOperationLoading(false);
        }
      }
    };

    loadOperation();
    timer = ENABLE_BACKGROUND_POLLING ? setInterval(loadOperation, OPERATION_POLL_INTERVAL_MS) : null;

    return () => {
      mounted = false;
      if (timer) {
        clearInterval(timer);
      }
    };
  }, [selectedOperationId]);

  const dockerState = policy?.docker || host?.docker || null;
  const simModeEnabled = Boolean(policy?.sim_mode);
  const preferredNetworkName = policy?.defaults?.default_network_name || 'drone-network';
  const mutationsEnabled = Boolean(policy?.features?.lifecycle_mutations);

  const hostCards = useMemo(() => {
    if (!host) {
      return [];
    }
    return [
      { icon: FaServer, label: 'Host', value: host.hostname, detail: `${host.platform} ${host.platform_release}` },
      { icon: FaMicrochip, label: 'CPU', value: `${host.cpu_count_logical} logical`, detail: host.architecture },
      { icon: FaMemory, label: 'Memory Free', value: formatBytes(host.memory_available_bytes), detail: `${formatBytes(host.memory_total_bytes)} total` },
      { icon: FaHdd, label: 'Disk Free', value: formatBytes(host.disk_free_bytes), detail: `${formatBytes(host.disk_total_bytes)} total` },
    ];
  }, [host]);

  const handleRefresh = () => setRefreshTick((current) => current + 1);

  const handleReconcileFieldChange = (field, value) => {
    setReconcileForm((current) => ({ ...current, [field]: value }));
  };

  const handleReconcileSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      const operation = await reconcileSitlFleet({
        target_count: Number(reconcileForm.targetCount),
        image_ref: reconcileForm.imageRef || null,
        start_id: Number(reconcileForm.startId),
        start_ip: Number(reconcileForm.startIp),
        subnet: reconcileForm.subnet || null,
        docker_network_name: reconcileForm.dockerNetworkName || null,
        git_sync_enabled: Boolean(reconcileForm.gitSyncEnabled),
        requirements_sync_enabled: Boolean(reconcileForm.requirementsSyncEnabled),
      });
      setSelectedOperationId(operation.operation_id);
      toast.success(operation.summary || 'SITL reconcile queued');
      handleRefresh();
    } catch (error) {
      toast.error(`Failed to reconcile SITL fleet: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRestartInstance = async () => {
    if (!selectedInstance?.name) {
      return;
    }
    setSubmitting(true);
    try {
      const operation = await restartSitlInstance(selectedInstance.name);
      setSelectedOperationId(operation.operation_id);
      toast.success(operation.summary || `Restart queued for ${selectedInstance.name}`);
      handleRefresh();
    } catch (error) {
      toast.error(`Failed to restart ${selectedInstance.name}: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemoveInstance = async () => {
    if (!selectedInstance?.name) {
      return;
    }
    if (!window.confirm(`Remove ${selectedInstance.name} from the local SITL fleet?`)) {
      return;
    }
    setSubmitting(true);
    try {
      const operation = await removeSitlInstance(selectedInstance.name);
      setSelectedOperationId(operation.operation_id);
      toast.success(operation.summary || `Removal queued for ${selectedInstance.name}`);
      handleRefresh();
    } catch (error) {
      toast.error(`Failed to remove ${selectedInstance.name}: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="sitl-control-page">
      <SectionHeader
        title="SITL Control"
        detail="Local Docker SITL supervisor for image inventory, fleet reconcile, runtime inspection, and container lifecycle control."
        action={(
          <button
            type="button"
            className="sitl-action-button"
            onClick={handleRefresh}
            disabled={loading || refreshing}
          >
            <FaRedoAlt />
            <span>{refreshing ? 'Refreshing…' : 'Refresh'}</span>
          </button>
        )}
      />

      {loading ? (
        <div className="sitl-loading-shell" aria-live="polite">
          <div className="sitl-loading-shell__pulse" />
          <div className="sitl-loading-shell__pulse" />
          <div className="sitl-loading-shell__pulse" />
        </div>
      ) : null}

      {!loading ? (
        <>
          <div className="sitl-summary-grid">
            <SummaryCard
              icon={FaDocker}
              label="Docker"
              value={dockerState?.daemon_reachable ? 'Connected' : 'Unavailable'}
              detail={dockerState?.error || dockerState?.server_version || dockerState?.socket_path || ''}
              tone={formatDockerTone(dockerState)}
            />
            <SummaryCard
              icon={FaInfoCircle}
              label="Mode"
              value={simModeEnabled ? 'SITL runtime' : 'Disabled on this GCS'}
              detail={mutationsEnabled ? 'Inventory + lifecycle controls active' : 'Read-only'}
              tone={simModeEnabled ? 'good' : 'warning'}
            />
            <SummaryCard
              icon={FaCube}
              label="Images"
              value={String(images.length)}
              detail="Filtered to MDS SITL images"
            />
            <SummaryCard
              icon={FaStream}
              label="Instances"
              value={String(instances.length)}
              detail="Detected MDS SITL containers"
            />
          </div>

          {!simModeEnabled ? (
            <EmptyState
              title="SITL control is disabled on this runtime"
              detail="This page is intended for GCS instances running in simulation mode."
            />
          ) : null}

          {simModeEnabled ? (
            <>
              <section className="sitl-section">
                <SectionHeader
                  title="Fleet Reconcile"
                  detail="Beginner defaults stay simple. Expand Advanced only when you need to override image, network, or sync behavior."
                />
                <form className="sitl-reconcile-card" onSubmit={handleReconcileSubmit}>
                  <div className="sitl-form-grid">
                    <label className="sitl-field">
                      <span>Desired instances</span>
                      <input
                        type="number"
                        min="1"
                        max="50"
                        value={reconcileForm.targetCount}
                        onChange={(event) => handleReconcileFieldChange('targetCount', event.target.value)}
                      />
                    </label>

                    <label className="sitl-field">
                      <span>Image</span>
                      <input
                        type="text"
                        list="sitl-image-options"
                        placeholder={policy?.defaults?.default_image || 'mavsdk-drone-show-sitl:latest'}
                        value={reconcileForm.imageRef}
                        onChange={(event) => handleReconcileFieldChange('imageRef', event.target.value)}
                      />
                    </label>
                  </div>
                  <datalist id="sitl-image-options">
                    {images.map((image) => (
                      <option key={image.image_id} value={image.primary_tag || image.image_id} />
                    ))}
                  </datalist>

                  <details className="sitl-advanced-panel">
                    <summary>Advanced</summary>
                    <div className="sitl-form-grid sitl-form-grid--advanced">
                      <label className="sitl-field">
                        <span>Start ID</span>
                        <input
                          type="number"
                          min="1"
                          max="999"
                          value={reconcileForm.startId}
                          onChange={(event) => handleReconcileFieldChange('startId', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <span>Start IP</span>
                        <input
                          type="number"
                          min="2"
                          max="254"
                          value={reconcileForm.startIp}
                          onChange={(event) => handleReconcileFieldChange('startIp', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <span>Subnet</span>
                        <input
                          type="text"
                          placeholder="172.18.0.0/24"
                          value={reconcileForm.subnet}
                          onChange={(event) => handleReconcileFieldChange('subnet', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <span>Docker network</span>
                        <input
                          type="text"
                          placeholder={preferredNetworkName}
                          value={reconcileForm.dockerNetworkName}
                          onChange={(event) => handleReconcileFieldChange('dockerNetworkName', event.target.value)}
                        />
                      </label>
                    </div>
                    <div className="sitl-toggle-row">
                      <label className="sitl-toggle">
                        <input
                          type="checkbox"
                          checked={Boolean(reconcileForm.gitSyncEnabled)}
                          onChange={(event) => handleReconcileFieldChange('gitSyncEnabled', event.target.checked)}
                        />
                        <span>Git sync on boot</span>
                      </label>
                      <label className="sitl-toggle">
                        <input
                          type="checkbox"
                          checked={Boolean(reconcileForm.requirementsSyncEnabled)}
                          onChange={(event) => handleReconcileFieldChange('requirementsSyncEnabled', event.target.checked)}
                        />
                        <span>Requirements sync on boot</span>
                      </label>
                    </div>
                  </details>

                  <div className="sitl-reconcile-card__actions">
                    <button
                      type="submit"
                      className="sitl-action-button sitl-action-button--primary"
                      disabled={!dockerState?.daemon_reachable || submitting}
                    >
                      <FaPlay />
                      <span>{submitting ? 'Submitting…' : 'Reconcile fleet'}</span>
                    </button>
                    <small>
                      Uses the canonical `multiple_sitl/create_dockers.sh` launcher, then removes stale extra containers outside the requested range.
                    </small>
                  </div>
                </form>
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Host"
                  detail="Quick host health context for local SITL operations."
                />
                <div className="sitl-host-grid">
                  {hostCards.map((card) => (
                    <SummaryCard key={card.label} {...card} />
                  ))}
                </div>
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Operations"
                  detail="Tracked reconcile and lifecycle actions. The latest operation keeps its own progress lines instead of forcing you into raw shell output."
                />
                {operations.length === 0 ? (
                  <EmptyState
                    title="No SITL operations yet"
                    detail="Run a reconcile, restart, or remove action to populate the operation log."
                  />
                ) : (
                  <div className="sitl-instance-layout">
                    <div className="sitl-card-grid sitl-card-grid--instances">
                      {operations.map((operation) => (
                        <button
                          key={operation.operation_id}
                          type="button"
                          className={`sitl-entity-card sitl-entity-card--button ${selectedOperationId === operation.operation_id ? 'is-active' : ''}`.trim()}
                          onClick={() => setSelectedOperationId(operation.operation_id)}
                        >
                          <div className="sitl-entity-card__header">
                            <strong>{operation.summary}</strong>
                            <span className={`sitl-badge sitl-badge--${formatOperationTone(operation)}`}>
                              {operation.status}
                            </span>
                          </div>
                          <div className="sitl-entity-card__meta">
                            <span>{operation.operation_type}</span>
                            <span>{operation.affected_instances.join(', ') || 'No instance target'}</span>
                            <span>{formatTimestamp(operation.updated_at)}</span>
                          </div>
                        </button>
                      ))}
                    </div>

                    <aside className="sitl-instance-detail">
                      {selectedOperation ? (
                        <>
                          <div className="sitl-instance-detail__header">
                            <div>
                              <h3>{selectedOperation.summary}</h3>
                              <p>{selectedOperation.detail || selectedOperation.operation_type}</p>
                            </div>
                            <div className={`sitl-badge sitl-badge--${formatOperationTone(selectedOperation)}`}>
                              {operationLoading && !TERMINAL_OPERATION_STATES.has(selectedOperation.status) ? 'updating…' : selectedOperation.status}
                            </div>
                          </div>

                          <dl className="sitl-key-value-grid">
                            <div>
                              <dt>Operation</dt>
                              <dd>{selectedOperation.operation_type}</dd>
                            </div>
                            <div>
                              <dt>Targets</dt>
                              <dd>{selectedOperation.affected_instances.join(', ') || '—'}</dd>
                            </div>
                            <div>
                              <dt>Created</dt>
                              <dd>{formatTimestamp(selectedOperation.created_at)}</dd>
                            </div>
                            <div>
                              <dt>Updated</dt>
                              <dd>{formatTimestamp(selectedOperation.updated_at)}</dd>
                            </div>
                          </dl>

                          <div className="sitl-log-panel">
                            <div className="sitl-log-panel__header">
                              <strong>Operation progress</strong>
                              <span className="sitl-inline-note">{selectedOperation.log_lines.length} line(s)</span>
                            </div>
                            <div className="sitl-log-panel__body">
                              {selectedOperation.log_lines.length === 0 ? (
                                <span className="sitl-log-panel__loading">No progress lines recorded yet.</span>
                              ) : (
                                <pre>{selectedOperation.log_lines.join('\n')}</pre>
                              )}
                            </div>
                          </div>
                        </>
                      ) : (
                        <EmptyState
                          title="Select an operation"
                          detail="The detail panel shows progress lines and completion state for the selected SITL action."
                        />
                      )}
                    </aside>
                  </div>
                )}
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Images"
                  detail="Available local SITL images with provenance labels when present."
                />
                {images.length === 0 ? (
                  <EmptyState
                    title="No SITL images detected"
                    detail="Build or load an MDS SITL image on this host before trying to reconcile a fleet."
                  />
                ) : (
                  <div className="sitl-card-grid">
                    {images.map((image) => (
                      <article key={image.image_id} className="sitl-entity-card">
                        <div className="sitl-entity-card__header">
                          <strong>{image.primary_tag || image.image_id}</strong>
                          <span className="sitl-badge">{image.in_use_by_instances} in use</span>
                        </div>
                        <div className="sitl-entity-card__meta">
                          <span>Branch: {image.branch || '—'}</span>
                          <span>Commit: {image.commit || '—'}</span>
                          <span>Size: {formatBytes(image.size_bytes)}</span>
                          <span>Created: {formatTimestamp(image.created_at)}</span>
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Instances"
                  detail="Click a container to inspect its current runtime facts, tailed logs, and lifecycle controls."
                />
                {instances.length === 0 ? (
                  <EmptyState
                    title="No SITL containers detected"
                    detail="Use Fleet Reconcile above to create a fresh local SITL fleet from the selected image."
                  />
                ) : (
                  <div className="sitl-instance-layout">
                    <div className="sitl-card-grid sitl-card-grid--instances">
                      {instances.map((instance) => (
                        <button
                          key={instance.name}
                          type="button"
                          className={`sitl-entity-card sitl-entity-card--button ${selectedInstance?.name === instance.name ? 'is-active' : ''}`.trim()}
                          onClick={() => setSelectedInstance(instance)}
                        >
                          <div className="sitl-entity-card__header">
                            <strong>{instance.name}</strong>
                            <span className={`sitl-badge sitl-badge--${formatInstanceTone(instance)}`}>
                              {instance.state}
                            </span>
                          </div>
                          <div className="sitl-entity-card__meta">
                            <span>{formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name)}</span>
                            <span>{getPrimaryInstanceIp(instance, preferredNetworkName)}</span>
                            <span>{instance.image_ref || 'Unknown image'}</span>
                            <span>{instance.git_branch ? `Branch ${instance.git_branch}` : 'Branch —'}</span>
                          </div>
                        </button>
                      ))}
                    </div>

                    <aside className="sitl-instance-detail">
                      {selectedInstance ? (
                        <>
                          <div className="sitl-instance-detail__header">
                            <div>
                              <h3>{selectedInstance.name}</h3>
                              <p>{formatCompactDroneIdentity(selectedInstance.pos_id_hint, selectedInstance.hw_id, selectedInstance.name)}</p>
                            </div>
                            <div className={`sitl-badge sitl-badge--${formatInstanceTone(selectedInstance)}`}>
                              {selectedInstance.status}
                            </div>
                          </div>

                          <div className="sitl-inline-actions">
                            <button
                              type="button"
                              className="sitl-action-button"
                              onClick={handleRestartInstance}
                              disabled={submitting}
                            >
                              <FaSyncAlt />
                              <span>Restart</span>
                            </button>
                            <button
                              type="button"
                              className="sitl-action-button sitl-action-button--danger"
                              onClick={handleRemoveInstance}
                              disabled={submitting}
                            >
                              <FaStop />
                              <span>Remove</span>
                            </button>
                          </div>

                          <dl className="sitl-key-value-grid">
                            <div>
                              <dt>Image</dt>
                              <dd>{selectedInstance.image_ref || '—'}</dd>
                            </div>
                            <div>
                              <dt>Git branch</dt>
                              <dd>{selectedInstance.git_branch || '—'}</dd>
                            </div>
                            <div>
                              <dt>Git sync</dt>
                              <dd>{selectedInstance.git_sync_enabled === null ? '—' : selectedInstance.git_sync_enabled ? 'Enabled' : 'Disabled'}</dd>
                            </div>
                            <div>
                              <dt>Req sync</dt>
                              <dd>{selectedInstance.requirements_sync_enabled === null ? '—' : selectedInstance.requirements_sync_enabled ? 'Enabled' : 'Disabled'}</dd>
                            </div>
                            <div>
                              <dt>Primary IP</dt>
                              <dd>{getPrimaryInstanceIp(selectedInstance, preferredNetworkName)}</dd>
                            </div>
                            <div>
                              <dt>Started</dt>
                              <dd>{formatTimestamp(selectedInstance.started_at)}</dd>
                            </div>
                          </dl>

                          <div className="sitl-log-panel">
                            <div className="sitl-log-panel__header">
                              <strong>Container logs</strong>
                              <label>
                                Tail
                                <select value={logTail} onChange={(event) => setLogTail(Number(event.target.value))}>
                                  {LOG_TAIL_OPTIONS.map((value) => (
                                    <option key={value} value={value}>{value}</option>
                                  ))}
                                </select>
                              </label>
                            </div>
                            <div className="sitl-log-panel__body">
                              {logLoading ? <span className="sitl-log-panel__loading">Loading logs…</span> : null}
                              {!logLoading && logLines.length === 0 ? (
                                <span className="sitl-log-panel__loading">No log lines returned.</span>
                              ) : null}
                              {!logLoading && logLines.length > 0 ? (
                                <pre>{logLines.join('\n')}</pre>
                              ) : null}
                            </div>
                          </div>
                        </>
                      ) : (
                        <EmptyState
                          title="Select an instance"
                          detail="The detail panel will show runtime facts, lifecycle controls, and tailed logs for the selected SITL container."
                        />
                      )}
                    </aside>
                  </div>
                )}
              </section>
            </>
          ) : null}
        </>
      ) : null}
    </div>
  );
}

export default SitlControlPage;
