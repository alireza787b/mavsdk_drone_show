import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  FaCube,
  FaDocker,
  FaInfoCircle,
  FaPlay,
  FaPlus,
  FaRedoAlt,
  FaSearch,
  FaStop,
  FaStream,
  FaSyncAlt,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { clearThrottledToast, toastErrorThrottled } from '../utilities/toastFeedback';
import {
  createSitlInstance,
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
const COMPACT_DETAIL_BREAKPOINT_PX = 1100;

function useCompactDetailLayout() {
  const getValue = () => {
    if (typeof window === 'undefined') {
      return false;
    }
    return window.innerWidth <= COMPACT_DETAIL_BREAKPOINT_PX;
  };

  const [isCompact, setIsCompact] = useState(getValue);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return undefined;
    }
    const handleResize = () => setIsCompact(getValue());
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return isCompact;
}

function splitImageRef(imageRef) {
  const normalized = String(imageRef || '').trim();
  if (!normalized) {
    return { repo: '', tag: '' };
  }
  const separatorIndex = normalized.lastIndexOf(':');
  const lastSlashIndex = normalized.lastIndexOf('/');
  if (separatorIndex > lastSlashIndex) {
    return {
      repo: normalized.slice(0, separatorIndex),
      tag: normalized.slice(separatorIndex + 1),
    };
  }
  return { repo: normalized, tag: '' };
}

function buildImageCatalog(images) {
  const repos = new Map();
  images.forEach((image) => {
    const refs = Array.isArray(image?.repo_tags) && image.repo_tags.length > 0
      ? image.repo_tags
      : [image?.primary_tag].filter(Boolean);
    refs.forEach((ref) => {
      const { repo, tag } = splitImageRef(ref);
      if (!repo) {
        return;
      }
      if (!repos.has(repo)) {
        repos.set(repo, new Set());
      }
      if (tag) {
        repos.get(repo).add(tag);
      }
    });
  });
  return Array.from(repos.entries())
    .map(([repo, tags]) => ({
      repo,
      tags: Array.from(tags).sort((left, right) => {
        if (left === 'latest') {
          return -1;
        }
        if (right === 'latest') {
          return 1;
        }
        return left.localeCompare(right);
      }),
    }))
    .sort((left, right) => left.repo.localeCompare(right.repo));
}

function getImageShortLabel(imageRef) {
  const { repo, tag } = splitImageRef(imageRef);
  const repoLabel = repo ? repo.split('/').slice(-1)[0] : 'unknown';
  return tag ? `${repoLabel}:${tag}` : repoLabel;
}

function getRepoLabel(repoUrl) {
  const normalized = String(repoUrl || '').trim();
  if (!normalized) {
    return 'repo —';
  }
  const cleaned = normalized
    .replace(/^https?:\/\//, '')
    .replace(/^git@github\.com:/, '')
    .replace(/^github\.com\//, '')
    .replace(/\.git$/, '');
  return cleaned.split('/').slice(-2).join('/') || cleaned;
}

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
  const [hasLoadedOnce, setHasLoadedOnce] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [pendingInstanceActions, setPendingInstanceActions] = useState({});
  const [selectedInstance, setSelectedInstance] = useState(null);
  const [selectedOperationId, setSelectedOperationId] = useState(null);
  const [selectedOperation, setSelectedOperation] = useState(null);
  const [operationLoading, setOperationLoading] = useState(false);
  const [operationsExpanded, setOperationsExpanded] = useState(false);
  const [imagesExpanded, setImagesExpanded] = useState(false);
  const [logTail, setLogTail] = useState(200);
  const [logLines, setLogLines] = useState([]);
  const [logSource, setLogSource] = useState(null);
  const [logLoading, setLogLoading] = useState(false);
  const [refreshTick, setRefreshTick] = useState(0);
  const [instanceQuery, setInstanceQuery] = useState('');
  const [creatingInstance, setCreatingInstance] = useState(false);
  const [addInstanceForm, setAddInstanceForm] = useState({
    instanceId: '',
    ipLastOctet: '',
  });
  const refreshVisibilityRef = useRef('auto');
  const compactDetailLayout = useCompactDetailLayout();
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
      const foregroundLoad = !background && !hasLoadedOnce;
      const showRefreshIndicator = !foregroundLoad && refreshVisibilityRef.current === 'manual';

      if (foregroundLoad) {
        setLoading(true);
      } else if (showRefreshIndicator) {
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
        clearThrottledToast('sitl-control:inventory');
        setHasLoadedOnce(true);
      } catch (error) {
        if (mounted) {
          toastErrorThrottled(
            'sitl-control:inventory',
            `Failed to load SITL control inventory: ${error.message}`,
          );
        }
      } finally {
        if (!mounted) {
          return;
        }
        refreshVisibilityRef.current = 'auto';
        setLoading(false);
        if (showRefreshIndicator) {
          setRefreshing(false);
        }
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
  }, [hasLoadedOnce, refreshTick]);

  useEffect(() => {
    if (operations.some((operation) => !TERMINAL_OPERATION_STATES.has(operation.status))) {
      setOperationsExpanded(true);
    }
  }, [operations]);

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
        setLogSource(null);
        return;
      }
      setLogLoading(true);
      try {
        const payload = await getSitlControlInstanceLogs(selectedInstance.name, { tail: logTail });
        if (mounted) {
          setLogLines(Array.isArray(payload?.lines) ? payload.lines : []);
          setLogSource(payload?.source || null);
          clearThrottledToast(`sitl-control:logs:${selectedInstance.name}`);
        }
      } catch (error) {
        if (mounted) {
          setLogLines([]);
          setLogSource(null);
          toastErrorThrottled(
            `sitl-control:logs:${selectedInstance.name}`,
            `Failed to load SITL logs for ${selectedInstance.name}: ${error.message}`,
          );
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
        clearThrottledToast(`sitl-control:operation:${selectedOperationId}`);
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
          toastErrorThrottled(
            `sitl-control:operation:${selectedOperationId}`,
            `Failed to load SITL operation ${selectedOperationId}: ${error.message}`,
          );
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

  useEffect(() => {
    if (!pendingInstanceActions || Object.keys(pendingInstanceActions).length === 0) {
      return;
    }

    setPendingInstanceActions((current) => {
      const nextEntries = Object.entries(current).filter(([instanceName, pending]) => {
        const instance = instances.find((item) => item.name === instanceName);

        if (pending?.action === 'remove') {
          if (!instance) {
            return false;
          }
        }

        if (pending?.action === 'restart') {
          if (instance?.state === 'running') {
            const matchingOperation = operations.find((operation) => (
              operation.operation_id === pending.operationId
            ));
            if (matchingOperation && TERMINAL_OPERATION_STATES.has(matchingOperation.status)) {
              return false;
            }
          }
        }

        return true;
      });

      return nextEntries.length === Object.keys(current).length
        ? current
        : Object.fromEntries(nextEntries);
    });
  }, [instances, operations, pendingInstanceActions]);

  const dockerState = policy?.docker || host?.docker || null;
  const simModeEnabled = Boolean(policy?.sim_mode);
  const preferredNetworkName = policy?.defaults?.default_network_name || 'drone-network';
  const mutationsEnabled = Boolean(policy?.features?.lifecycle_mutations);
  const imageCatalog = useMemo(() => buildImageCatalog(images), [images]);

  const resolvedImageSelection = useMemo(() => {
    const split = splitImageRef(reconcileForm.imageRef || policy?.defaults?.default_image || '');
    const hasRepo = imageCatalog.some((item) => item.repo === split.repo);
    if (hasRepo) {
      return {
        repo: split.repo,
        tag: split.tag,
      };
    }
    return {
      repo: imageCatalog[0]?.repo || '',
      tag: imageCatalog[0]?.tags[0] || '',
    };
  }, [imageCatalog, policy, reconcileForm.imageRef]);

  const availableImageTags = useMemo(() => (
    imageCatalog.find((item) => item.repo === resolvedImageSelection.repo)?.tags || []
  ), [imageCatalog, resolvedImageSelection.repo]);

  const selectedImageSummary = useMemo(() => {
    const selectedRef = reconcileForm.imageRef || '';
    return images.find((image) => (image.primary_tag || '') === selectedRef)
      || images.find((image) => splitImageRef(image.primary_tag || '').repo === resolvedImageSelection.repo
        && splitImageRef(image.primary_tag || '').tag === resolvedImageSelection.tag)
      || null;
  }, [images, reconcileForm.imageRef, resolvedImageSelection.repo, resolvedImageSelection.tag]);

  const filteredInstances = useMemo(() => {
    const query = instanceQuery.trim().toLowerCase();
    if (!query) {
      return instances;
    }
    return instances.filter((instance) => {
      const haystack = [
        instance.name,
        instance.hw_id,
        instance.pos_id_hint,
        getPrimaryInstanceIp(instance, preferredNetworkName),
        instance.image_ref,
        instance.git_branch,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      return haystack.includes(query);
    });
  }, [instanceQuery, instances, preferredNetworkName]);

  const nextSuggestedInstance = useMemo(() => {
    const ids = instances
      .map((instance) => Number(instance.pos_id_hint || instance.hw_id))
      .filter((value) => Number.isFinite(value));
    const ipOctets = instances
      .map((instance) => {
        const ip = getPrimaryInstanceIp(instance, preferredNetworkName);
        const octet = Number(String(ip).split('.').slice(-1)[0]);
        return Number.isFinite(octet) ? octet : null;
      })
      .filter((value) => value !== null);
    return {
      instanceId: ids.length > 0 ? Math.max(...ids) + 1 : 1,
      ipLastOctet: ipOctets.length > 0 ? Math.max(...ipOctets) + 1 : 2,
    };
  }, [instances, preferredNetworkName]);

  const handleRefresh = () => {
    refreshVisibilityRef.current = 'manual';
    setRefreshTick((current) => current + 1);
  };

  const handleReconcileFieldChange = (field, value) => {
    setReconcileForm((current) => ({ ...current, [field]: value }));
  };

  const handleImageRepoChange = (repo) => {
    const matched = imageCatalog.find((item) => item.repo === repo);
    const nextTag = matched?.tags[0] || '';
    handleReconcileFieldChange('imageRef', repo && nextTag ? `${repo}:${nextTag}` : repo);
  };

  const handleImageTagChange = (tag) => {
    const repo = resolvedImageSelection.repo;
    handleReconcileFieldChange('imageRef', repo && tag ? `${repo}:${tag}` : reconcileForm.imageRef);
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
      setOperationsExpanded(true);
      toast.success(operation.summary || 'SITL reconcile queued');
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to reconcile SITL fleet: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleAddInstance = async ({ custom = false } = {}) => {
    setCreatingInstance(true);
    try {
      const payload = {
        image_ref: reconcileForm.imageRef || null,
        docker_network_name: reconcileForm.dockerNetworkName || null,
        git_sync_enabled: Boolean(reconcileForm.gitSyncEnabled),
        requirements_sync_enabled: Boolean(reconcileForm.requirementsSyncEnabled),
      };
      if (custom && addInstanceForm.instanceId) {
        payload.instance_id = Number(addInstanceForm.instanceId);
      }
      if (custom && addInstanceForm.ipLastOctet) {
        payload.ip_last_octet = Number(addInstanceForm.ipLastOctet);
      }
      const operation = await createSitlInstance(payload);
      setSelectedOperationId(operation.operation_id);
      setOperationsExpanded(true);
      toast.success(operation.summary || 'SITL instance create queued');
      setAddInstanceForm({ instanceId: '', ipLastOctet: '' });
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to add SITL instance: ${error.message}`);
    } finally {
      setCreatingInstance(false);
    }
  };

  const handleRestartInstance = async () => {
    if (!selectedInstance?.name) {
      return;
    }
    setSubmitting(true);
    const instanceName = selectedInstance.name;
    setPendingInstanceActions((current) => ({
      ...current,
      [instanceName]: { action: 'restart', operationId: null },
    }));
    setInstances((current) => current.map((instance) => (
      instance.name === instanceName
        ? { ...instance, state: 'restarting', status: 'restarting' }
        : instance
    )));
    setSelectedInstance((current) => (
      current?.name === instanceName
        ? { ...current, state: 'restarting', status: 'restarting' }
        : current
    ));
    try {
      const operation = await restartSitlInstance(instanceName);
      setPendingInstanceActions((current) => ({
        ...current,
        [instanceName]: { action: 'restart', operationId: operation.operation_id },
      }));
      setSelectedOperationId(operation.operation_id);
      setOperationsExpanded(true);
      toast.success(operation.summary || `Restart queued for ${instanceName}`);
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      setInstances((current) => current.map((instance) => (
        instance.name === instanceName
          ? { ...instance, state: 'running', status: 'running' }
          : instance
      )));
      setSelectedInstance((current) => (
        current?.name === instanceName
          ? { ...current, state: 'running', status: 'running' }
          : current
      ));
      setPendingInstanceActions((current) => {
        const next = { ...current };
        delete next[instanceName];
        return next;
      });
      toast.error(`Failed to restart ${instanceName}: ${error.message}`);
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
    const instanceName = selectedInstance.name;
    setPendingInstanceActions((current) => ({
      ...current,
      [instanceName]: { action: 'remove', operationId: null },
    }));
    try {
      const operation = await removeSitlInstance(instanceName);
      setPendingInstanceActions((current) => ({
        ...current,
        [instanceName]: { action: 'remove', operationId: operation.operation_id },
      }));
      setSelectedOperationId(operation.operation_id);
      setOperationsExpanded(true);
      toast.success(operation.summary || `Removal queued for ${instanceName}`);
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      setPendingInstanceActions((current) => {
        const next = { ...current };
        delete next[instanceName];
        return next;
      });
      toast.error(`Failed to remove ${instanceName}: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const renderInstanceDetail = (instance, { inline = false } = {}) => {
    if (!instance) {
      return (
        <EmptyState
          title="Select an instance"
          detail="The detail panel will show runtime facts, lifecycle controls, and tailed logs for the selected SITL container."
        />
      );
    }

    const pendingAction = pendingInstanceActions[instance.name]?.action || null;

    return (
      <aside className={`sitl-instance-detail ${inline ? 'sitl-instance-detail--inline' : ''}`.trim()}>
        <div className="sitl-instance-detail__header">
          <div>
            <h3>{instance.name}</h3>
            <p>{formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name)}</p>
          </div>
          <div className={`sitl-badge sitl-badge--${formatInstanceTone(instance)}`}>
            {instance.status}
          </div>
        </div>

        <div className="sitl-inline-facts">
          <span className="sitl-badge sitl-badge--muted" title={`Repository: ${instance.git_repo_url || 'not reported'}`}>
            {getRepoLabel(instance.git_repo_url)}
          </span>
          <span className="sitl-badge sitl-badge--muted" title={`Branch: ${instance.git_branch || 'not reported'}`}>
            {instance.git_branch || 'branch —'}
          </span>
          <span className="sitl-badge sitl-badge--muted" title={`Image: ${instance.image_ref || 'not reported'}`}>
            {getImageShortLabel(instance.image_ref)}
          </span>
        </div>

        <div className="sitl-inline-actions">
          <button
            type="button"
            className="sitl-action-button"
            onClick={handleRestartInstance}
            disabled={submitting || Boolean(pendingAction)}
            title="Restart only this container and keep the rest of the fleet visible"
          >
            <FaSyncAlt />
            <span>{pendingAction === 'restart' ? 'Restarting…' : 'Restart'}</span>
          </button>
          <button
            type="button"
            className="sitl-action-button sitl-action-button--danger"
            onClick={handleRemoveInstance}
            disabled={submitting || Boolean(pendingAction)}
            title="Remove only this container from the local SITL fleet"
          >
            <FaStop />
            <span>{pendingAction === 'remove' ? 'Removing…' : 'Remove'}</span>
          </button>
        </div>

        {pendingAction ? (
          <div className="sitl-inline-note-banner" aria-live="polite">
            {pendingAction === 'restart'
              ? 'This container is restarting. The rest of the fleet view remains live while readiness returns.'
              : 'This container is being removed. The inventory stays visible while the operation completes.'}
          </div>
        ) : null}

        <dl className="sitl-key-value-grid">
          <div>
            <dt>Image</dt>
            <dd>{instance.image_ref || '—'}</dd>
          </div>
          <div>
            <dt>Git branch</dt>
            <dd>{instance.git_branch || '—'}</dd>
          </div>
          <div>
            <dt>Git sync</dt>
            <dd>{instance.git_sync_enabled === null ? '—' : instance.git_sync_enabled ? 'Enabled' : 'Disabled'}</dd>
          </div>
          <div>
            <dt>Req sync</dt>
            <dd>{instance.requirements_sync_enabled === null ? '—' : instance.requirements_sync_enabled ? 'Enabled' : 'Disabled'}</dd>
          </div>
          <div>
            <dt>Primary IP</dt>
            <dd>{getPrimaryInstanceIp(instance, preferredNetworkName)}</dd>
          </div>
          <div>
            <dt>Started</dt>
            <dd>{formatTimestamp(instance.started_at)}</dd>
          </div>
        </dl>

        <div className="sitl-log-panel">
          <div className="sitl-log-panel__header">
            <strong>Logs</strong>
            {logSource ? <span className="sitl-badge sitl-badge--muted">{logSource}</span> : null}
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
      </aside>
    );
  };

  return (
    <div className="sitl-control-page">
      <SectionHeader
        title="SITL Control"
        detail="Local Docker SITL fleet supervisor."
        action={(
          <button
            type="button"
            className="sitl-action-button"
            onClick={handleRefresh}
            disabled={loading || refreshing}
            title="Refresh host, image, instance, and operation inventory"
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
                  title="Fleet"
                  detail=""
                />
                <form className="sitl-reconcile-card" onSubmit={handleReconcileSubmit}>
                  <div className="sitl-form-grid">
                    <label className="sitl-field">
                      <span>Count</span>
                      <input
                        type="number"
                        min="1"
                        max="50"
                        aria-label="Desired instances"
                        value={reconcileForm.targetCount}
                        onChange={(event) => handleReconcileFieldChange('targetCount', event.target.value)}
                      />
                    </label>

                    {imageCatalog.length > 0 ? (
                      <>
                        <label className="sitl-field">
                          <span>Repo</span>
                          <select
                            aria-label="Image repository"
                            value={resolvedImageSelection.repo}
                            onChange={(event) => handleImageRepoChange(event.target.value)}
                            title="Select a discovered SITL image repository"
                          >
                            {imageCatalog.map((image) => (
                              <option key={image.repo} value={image.repo}>{image.repo}</option>
                            ))}
                          </select>
                        </label>
                        <label className="sitl-field">
                          <span>Tag</span>
                          <select
                            aria-label="Image tag"
                            value={resolvedImageSelection.tag}
                            onChange={(event) => handleImageTagChange(event.target.value)}
                            title="Select a discovered tag for the chosen image repository"
                          >
                            {availableImageTags.map((tag) => (
                              <option key={tag} value={tag}>{tag}</option>
                            ))}
                          </select>
                        </label>
                      </>
                    ) : (
                      <label className="sitl-field">
                        <span>Image ref</span>
                        <input
                          type="text"
                          placeholder={policy?.defaults?.default_image || 'mavsdk-drone-show-sitl:latest'}
                          value={reconcileForm.imageRef}
                          onChange={(event) => handleReconcileFieldChange('imageRef', event.target.value)}
                        />
                      </label>
                    )}
                  </div>

                  <details className="sitl-advanced-panel">
                    <summary>Advanced</summary>
                    <div className="sitl-form-grid sitl-form-grid--advanced">
                      <label className="sitl-field">
                        <span>Custom image ref</span>
                        <input
                          type="text"
                          placeholder={policy?.defaults?.default_image || 'mavsdk-drone-show-sitl:latest'}
                          value={reconcileForm.imageRef}
                          onChange={(event) => handleReconcileFieldChange('imageRef', event.target.value)}
                        />
                      </label>
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
                    <div className="sitl-inline-actions">
                      <button
                        type="submit"
                        className="sitl-action-button sitl-action-button--primary"
                        disabled={!dockerState?.daemon_reachable || submitting}
                        title="Recreate the requested range and prune extra containers outside that range"
                      >
                        <FaPlay />
                        <span>{submitting ? 'Submitting…' : 'Reconcile'}</span>
                      </button>
                      <button
                        type="button"
                        className="sitl-action-button"
                        disabled={!dockerState?.daemon_reachable || creatingInstance}
                        title={`Add one new SITL container using the next free ID/IP (${nextSuggestedInstance.instanceId} / ${nextSuggestedInstance.ipLastOctet})`}
                        onClick={() => handleAddInstance({ custom: false })}
                      >
                        <FaPlus />
                        <span>{creatingInstance ? 'Adding…' : 'Next'}</span>
                      </button>
                      <details className="sitl-inline-disclosure">
                        <summary title="Add a specific slot/IP without pruning the rest of the fleet">Custom</summary>
                        <div className="sitl-inline-create-form">
                          <label className="sitl-field">
                            <span>Slot</span>
                            <input
                              type="number"
                              min="1"
                              max="999"
                              placeholder={String(nextSuggestedInstance.instanceId)}
                              value={addInstanceForm.instanceId}
                              onChange={(event) => setAddInstanceForm((current) => ({ ...current, instanceId: event.target.value }))}
                            />
                          </label>
                          <label className="sitl-field">
                            <span>IP</span>
                            <input
                              type="number"
                              min="2"
                              max="254"
                              placeholder={String(nextSuggestedInstance.ipLastOctet)}
                              value={addInstanceForm.ipLastOctet}
                              onChange={(event) => setAddInstanceForm((current) => ({ ...current, ipLastOctet: event.target.value }))}
                            />
                          </label>
                          <button
                            type="button"
                            className="sitl-action-button"
                            disabled={!dockerState?.daemon_reachable || creatingInstance}
                            onClick={() => handleAddInstance({ custom: true })}
                            title="Create one exact-slot container without pruning the rest of the fleet"
                          >
                            <FaPlus />
                            <span>{creatingInstance ? 'Adding…' : 'Add'}</span>
                          </button>
                        </div>
                      </details>
                    </div>
                    <div className="sitl-inline-facts" aria-label="Fleet reconcile behavior">
                      <span className="sitl-badge sitl-badge--muted" title="Reconcile recreates the requested range fresh">fresh</span>
                      <span className="sitl-badge sitl-badge--muted" title="Reconcile removes extra containers outside the requested range">prune</span>
                      {resolvedImageSelection.tag ? (
                        <span className="sitl-badge sitl-badge--muted" title="Selected image tag">
                          {resolvedImageSelection.tag}
                        </span>
                      ) : null}
                      {selectedImageSummary?.commit ? (
                        <span className="sitl-badge sitl-badge--muted" title="Selected image commit">
                          {selectedImageSummary.commit.slice(0, 7)}
                        </span>
                      ) : null}
                      <span className="sitl-badge sitl-badge--muted" title="Next free slot and IP">
                        next {nextSuggestedInstance.instanceId}
                      </span>
                    </div>
                  </div>
                </form>
              </section>

              <section className="sitl-section">
                <details className="sitl-collapsible" open={operationsExpanded} onToggle={(event) => setOperationsExpanded(event.currentTarget.open)}>
                  <summary>
                    <span>Ops</span>
                    <span className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">{operations.length}</span>
                      <span className="sitl-badge sitl-badge--muted">
                        {operations.filter((operation) => !TERMINAL_OPERATION_STATES.has(operation.status)).length} active
                      </span>
                    </span>
                  </summary>
                  {operations.length === 0 ? (
                    <EmptyState
                      title="No SITL operations yet"
                      detail="Run a reconcile, add, restart, or remove action to populate this list."
                    />
                  ) : (
                    <div className="sitl-instance-layout">
                      <div className="sitl-compact-list">
                        {operations.map((operation) => (
                          <button
                            key={operation.operation_id}
                            type="button"
                            className={`sitl-compact-row ${selectedOperationId === operation.operation_id ? 'is-active' : ''}`.trim()}
                            onClick={() => setSelectedOperationId(operation.operation_id)}
                            title={operation.detail || operation.summary}
                          >
                            <div className="sitl-compact-row__main">
                              <strong>{operation.summary}</strong>
                              <span>{operation.affected_instances.join(', ') || operation.operation_type}</span>
                            </div>
                            <div className="sitl-compact-row__side">
                              <span className={`sitl-badge sitl-badge--${formatOperationTone(operation)}`}>
                                {operation.status}
                              </span>
                              <small>{formatTimestamp(operation.updated_at)}</small>
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
                                <strong>Progress</strong>
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
                </details>
              </section>

              <section className="sitl-section">
                <details className="sitl-collapsible" open={imagesExpanded} onToggle={(event) => setImagesExpanded(event.currentTarget.open)}>
                  <summary>
                    <span>Images</span>
                    <span className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">{images.length}</span>
                    </span>
                  </summary>
                  {images.length === 0 ? (
                    <EmptyState
                      title="No SITL images detected"
                      detail="Build or load an MDS SITL image on this host before trying to reconcile a fleet."
                    />
                  ) : (
                    <div className="sitl-compact-list">
                      {images.map((image) => (
                        <article key={image.image_id} className="sitl-compact-row sitl-compact-row--static">
                          <div className="sitl-compact-row__main">
                            <strong>{splitImageRef(image.primary_tag || image.image_id).repo || image.primary_tag || image.image_id}</strong>
                            <span>{image.commit || 'commit —'}</span>
                          </div>
                          <div className="sitl-compact-row__side">
                            <span className="sitl-badge" title="Tag">{splitImageRef(image.primary_tag || '').tag || 'untagged'}</span>
                            <small>{formatBytes(image.size_bytes)}</small>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                </details>
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Instances"
                  detail=""
                  action={(
                    <label className="sitl-search-field">
                      <FaSearch />
                      <input
                        type="search"
                        value={instanceQuery}
                        onChange={(event) => setInstanceQuery(event.target.value)}
                        placeholder="Search name, Pn|Hm, IP, branch"
                        aria-label="Search SITL instances"
                      />
                    </label>
                  )}
                />
                {instances.length === 0 ? (
                  <EmptyState
                    title="No SITL containers detected"
                    detail="Use Fleet Reconcile above to create a fresh local SITL fleet from the selected image."
                  />
                ) : (
                  <div className="sitl-instance-layout">
                    <div className="sitl-compact-list sitl-compact-list--instances">
                      <div className="sitl-inline-facts">
                        <span className="sitl-badge sitl-badge--muted">
                          {filteredInstances.length} of {instances.length}
                        </span>
                      </div>
                      {filteredInstances.map((instance) => (
                        <div key={instance.name} className="sitl-instance-stack">
                          <button
                            type="button"
                            className={`sitl-compact-row ${selectedInstance?.name === instance.name ? 'is-active' : ''}`.trim()}
                            onClick={() => setSelectedInstance(instance)}
                            title={`${formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name)} · ${getPrimaryInstanceIp(instance, preferredNetworkName)}`}
                          >
                            <div className="sitl-compact-row__main">
                              <strong>{instance.name}</strong>
                              <span>{formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name)} · {getPrimaryInstanceIp(instance, preferredNetworkName)}</span>
                            </div>
                            <div className="sitl-compact-row__side">
                              <span className={`sitl-badge sitl-badge--${formatInstanceTone(instance)}`}>
                                {instance.state}
                              </span>
                              <small>{getRepoLabel(instance.git_repo_url)}</small>
                              <small>{getImageShortLabel(instance.image_ref)}</small>
                            </div>
                          </button>
                          {compactDetailLayout && selectedInstance?.name === instance.name ? renderInstanceDetail(instance, { inline: true }) : null}
                        </div>
                      ))}
                    </div>

                    {!compactDetailLayout ? renderInstanceDetail(selectedInstance, { inline: false }) : null}
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
