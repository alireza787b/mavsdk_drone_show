import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  FaCube,
  FaDocker,
  FaExclamationTriangle,
  FaInfoCircle,
  FaLayerGroup,
  FaLink,
  FaPlay,
  FaPlus,
  FaRedoAlt,
  FaSave,
  FaSearch,
  FaStop,
  FaStream,
  FaSyncAlt,
  FaTimes,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import InfoHint from '../components/InfoHint';
import { GIT_COMMIT } from '../version';
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
  releaseSitlImage,
  reconcileSitlFleet,
  runSitlInstanceAction,
  removeSitlInstance,
  restartSitlInstance,
} from '../services/sitlControlService';
import '../styles/SitlControlPage.css';

const INVENTORY_POLL_INTERVAL_MS = 10000;
const OPERATION_POLL_INTERVAL_MS = 2000;
const LOG_TAIL_OPTIONS = [80, 200, 500];
const TERMINAL_OPERATION_STATES = new Set(['failed', 'succeeded']);
const ENABLE_BACKGROUND_POLLING = process.env.NODE_ENV !== 'test';

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

function FieldLabel({ label, hint = '' }) {
  return (
    <span className="sitl-field-label">
      <span>{label}</span>
      {hint ? <InfoHint content={hint} label={`${label} help`} /> : null}
    </span>
  );
}

function ConfirmDialog({ dialog, onCancel, onConfirm, busy = false }) {
  if (!dialog) {
    return null;
  }

  const {
    title,
    message,
    facts = [],
    confirmLabel = 'Confirm',
    tone = 'default',
  } = dialog;

  return (
    <div className="sitl-dialog-backdrop" role="presentation" onClick={busy ? undefined : onCancel}>
      <div
        className={`sitl-dialog sitl-dialog--${tone}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby="sitl-confirm-dialog-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="sitl-dialog__header">
          <div>
            <h3 id="sitl-confirm-dialog-title">{title}</h3>
            {message ? <p>{message}</p> : null}
          </div>
          <button
            type="button"
            className="sitl-icon-button"
            onClick={onCancel}
            disabled={busy}
            aria-label="Close confirmation dialog"
          >
            <FaTimes />
          </button>
        </div>
        {facts.length > 0 ? (
          <div className="sitl-dialog__facts">
            {facts.map((fact) => (
              <span key={fact} className="sitl-badge sitl-badge--muted">{fact}</span>
            ))}
          </div>
        ) : null}
        <div className="sitl-dialog__actions">
          <button
            type="button"
            className="sitl-action-button"
            onClick={onCancel}
            disabled={busy}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`sitl-action-button ${tone === 'danger' ? 'sitl-action-button--danger' : 'sitl-action-button--primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function sanitizeTagValue(value, { fallback = '' } = {}) {
  const normalized = String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return normalized || fallback;
}

function buildDefaultReleaseVersionTag(image, policy) {
  const preferred = image?.version_tag && image.version_tag !== 'latest'
    ? image.version_tag
    : GIT_COMMIT
      || image?.commit?.slice(0, 7)
      || image?.branch
      || policy?.defaults?.default_image
      || 'manual-tag';
  return sanitizeTagValue(preferred, { fallback: 'manual-tag' });
}

function buildDefaultArchiveBasename(imageRepo) {
  const repoTail = String(imageRepo || 'mds-sitl')
    .split('/')
    .slice(-1)[0]
    .replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return `${repoTail || 'mds-sitl'}-image`;
}

function formatPercent(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    return '—';
  }
  return `${Math.round(numeric)}%`;
}

function buildPortainerUrl(host) {
  if (!host?.portainer_available || !host?.portainer_port || typeof window === 'undefined') {
    return null;
  }

  return `${host.portainer_scheme || 'http'}://${window.location.hostname}:${host.portainer_port}`;
}

function evaluateHostResources(host) {
  if (!host) {
    return { badges: [], warnings: [], detailRows: [] };
  }

  const badges = [];
  const warnings = [];
  const cpuLoad = Number(host.load_avg_1m || 0);
  const cpuCapacity = Number(host.cpu_count_logical || 0);
  const cpuUsagePercent = Number(host.cpu_usage_percent);
  const memoryFree = Number(host.memory_available_bytes || 0);
  const memoryTotal = Number(host.memory_total_bytes || 0);
  const diskFree = Number(host.disk_free_bytes || 0);
  const diskTotal = Number(host.disk_total_bytes || 0);
  const memoryFreePercent = memoryTotal > 0 ? (memoryFree / memoryTotal) * 100 : null;
  const diskFreePercent = diskTotal > 0 ? (diskFree / diskTotal) * 100 : null;

  if (Number.isFinite(cpuUsagePercent)) {
    badges.push({
      label: 'CPU',
      value: formatPercent(cpuUsagePercent),
      tone: cpuUsagePercent >= 85 ? 'warning' : 'muted',
    });
    if (cpuUsagePercent >= 85) {
      warnings.push('High CPU');
    }
  }
  if (memoryTotal > 0) {
    badges.push({
      label: 'RAM',
      value: `${formatBytes(memoryFree)} free`,
      tone: memoryFree < 1.5 * 1024 * 1024 * 1024 || memoryFreePercent < 20 ? 'warning' : 'muted',
    });
    if (memoryFree < 1.5 * 1024 * 1024 * 1024 || memoryFreePercent < 20) {
      warnings.push('Low RAM');
    }
  }
  if (diskTotal > 0) {
    badges.push({
      label: 'Disk',
      value: `${formatBytes(diskFree)} free`,
      tone: diskFree < 5 * 1024 * 1024 * 1024 || diskFreePercent < 12 ? 'warning' : 'muted',
    });
    if (diskFree < 5 * 1024 * 1024 * 1024 || diskFreePercent < 12) {
      warnings.push('Low disk');
    }
  }

  if (host.portainer_available) {
    badges.push({
      label: 'Portainer',
      value: host.portainer_port ? `:${host.portainer_port}` : 'ready',
      tone: 'muted',
    });
  }

  return {
    badges,
    warnings,
    detailRows: [
      { label: 'Host', value: host.hostname || '—' },
      { label: 'Platform', value: `${host.platform || '—'} ${host.platform_release || ''}`.trim() || '—' },
      { label: 'Python', value: host.python_version || '—' },
      { label: 'CPU usage', value: Number.isFinite(cpuUsagePercent) ? `${formatPercent(cpuUsagePercent)} · 1m load ${cpuLoad.toFixed(1)} on ${cpuCapacity} cores` : '—' },
      { label: 'Memory', value: memoryTotal > 0 ? `${formatBytes(memoryFree)} free / ${formatBytes(memoryTotal)}` : '—' },
      { label: 'Disk', value: diskTotal > 0 ? `${formatBytes(diskFree)} free / ${formatBytes(diskTotal)} at ${host.disk_path}` : '—' },
      { label: 'Docker', value: host.docker?.server_version || host.docker?.error || '—' },
      { label: 'Docker API', value: host.docker?.api_version || '—' },
    ],
  };
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
  const [releasingImage, setReleasingImage] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [customCreateExpanded, setCustomCreateExpanded] = useState(false);
  const [batchActionsExpanded, setBatchActionsExpanded] = useState(false);
  const [imageReleaseExpanded, setImageReleaseExpanded] = useState(false);
  const [hostDetailsExpanded, setHostDetailsExpanded] = useState(false);
  const [addInstanceForm, setAddInstanceForm] = useState({
    instanceId: '',
    ipLastOctet: '',
  });
  const [imageReleaseForm, setImageReleaseForm] = useState({
    baseImageRef: '',
    imageRepo: '',
    versionTag: '',
    tagLatest: true,
    tagCommit: true,
    exportArchive: false,
    compressArchive: false,
    outputDir: '',
    archiveBasename: '',
    repoUrl: '',
    branch: '',
  });
  const refreshVisibilityRef = useRef('auto');
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
            return nextInstances.find((instance) => instance.name === current.name) || null;
          }
          return null;
        });
        setSelectedOperationId((current) => {
          if (current && nextOperations.some((operation) => operation.operation_id === current)) {
            return current;
          }
          return null;
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
    setImageReleaseForm((current) => {
      const preferredImage = current.baseImageRef || images[0]?.primary_tag || policy?.defaults?.default_image || '';
      const preferredSplit = splitImageRef(preferredImage);
      return {
        ...current,
        baseImageRef: preferredImage,
        imageRepo: current.imageRepo || preferredSplit.repo || 'mavsdk-drone-show-sitl',
        versionTag: current.versionTag || buildDefaultReleaseVersionTag(images[0], policy),
        archiveBasename: current.archiveBasename || buildDefaultArchiveBasename(current.imageRepo || preferredSplit.repo),
        branch: current.branch || images[0]?.branch || '',
      };
    });
  }, [images, policy]);

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
  const hostResourceState = useMemo(() => evaluateHostResources(host), [host]);
  const portainerUrl = useMemo(() => buildPortainerUrl(host), [host]);

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

  const visibleInstanceNames = useMemo(
    () => filteredInstances.map((instance) => instance.name),
    [filteredInstances],
  );

  const activeOperationCount = useMemo(
    () => operations.filter((operation) => !TERMINAL_OPERATION_STATES.has(operation.status)).length,
    [operations],
  );

  const releaseSourceSelection = useMemo(
    () => splitImageRef(imageReleaseForm.baseImageRef || images[0]?.primary_tag || policy?.defaults?.default_image || ''),
    [imageReleaseForm.baseImageRef, images, policy],
  );
  const resolvedReleaseVersionTag = useMemo(
    () => sanitizeTagValue(
      imageReleaseForm.versionTag,
      { fallback: buildDefaultReleaseVersionTag(images[0], policy) },
    ),
    [imageReleaseForm.versionTag, images, policy],
  );

  const availableReleaseImageTags = useMemo(
    () => imageCatalog.find((item) => item.repo === releaseSourceSelection.repo)?.tags || [],
    [imageCatalog, releaseSourceSelection.repo],
  );

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

  const handleReleaseFieldChange = (field, value) => {
    setImageReleaseForm((current) => ({ ...current, [field]: value }));
  };

  const handleReleaseSourceRepoChange = (repo) => {
    const matched = imageCatalog.find((item) => item.repo === repo);
    const nextTag = matched?.tags[0] || '';
    const nextBaseRef = repo && nextTag ? `${repo}:${nextTag}` : repo;
    setImageReleaseForm((current) => ({
      ...current,
      baseImageRef: nextBaseRef,
      imageRepo: current.imageRepo || repo,
      archiveBasename: current.archiveBasename || buildDefaultArchiveBasename(current.imageRepo || repo),
    }));
  };

  const handleReleaseSourceTagChange = (tag) => {
    const repo = releaseSourceSelection.repo;
    setImageReleaseForm((current) => ({
      ...current,
      baseImageRef: repo && tag ? `${repo}:${tag}` : current.baseImageRef,
    }));
  };

  const toggleImageReleasePanel = () => {
    setImageReleaseExpanded((current) => {
      const next = !current;
      if (next) {
        setImageReleaseForm((form) => {
          const baseImageRef = form.baseImageRef || images[0]?.primary_tag || policy?.defaults?.default_image || '';
          const fallbackRepo = splitImageRef(baseImageRef).repo || 'mavsdk-drone-show-sitl';
          const imageRepo = form.imageRepo || fallbackRepo;
          return {
            ...form,
            baseImageRef,
            imageRepo,
            versionTag: form.versionTag || buildDefaultReleaseVersionTag(images[0], policy),
            archiveBasename: form.archiveBasename || buildDefaultArchiveBasename(imageRepo),
            branch: form.branch || images[0]?.branch || '',
          };
        });
      }
      return next;
    });
  };

  const openConfirmDialog = (dialog) => {
    setConfirmDialog(dialog);
  };

  const closeConfirmDialog = () => {
    if (confirmBusy) {
      return;
    }
    setConfirmDialog(null);
  };

  const handleConfirmDialog = async () => {
    if (!confirmDialog?.run) {
      setConfirmDialog(null);
      return;
    }
    setConfirmBusy(true);
    try {
      await confirmDialog.run();
      setConfirmDialog(null);
    } finally {
      setConfirmBusy(false);
    }
  };

  const executeReconcile = async () => {
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
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to reconcile SITL fleet: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleReconcileSubmit = async (event) => {
    event.preventDefault();
    openConfirmDialog({
      title: 'Reconcile SITL fleet?',
      message: 'This recreates the requested slot range from the selected image and prunes extra containers outside that range.',
      facts: [
        `${Number(reconcileForm.targetCount)} instance(s)`,
        `${resolvedImageSelection.repo || 'image'}:${resolvedImageSelection.tag || 'latest'}`,
        `start ${Number(reconcileForm.startId)} / .${Number(reconcileForm.startIp)}`,
        ...hostResourceState.warnings,
      ],
      confirmLabel: 'Reconcile',
      tone: 'default',
      run: executeReconcile,
    });
  };

  const executeAddInstance = async ({ custom = false } = {}) => {
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
      toast.success(operation.summary || 'SITL instance create queued');
      setAddInstanceForm({ instanceId: '', ipLastOctet: '' });
      setCustomCreateExpanded(false);
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to add SITL instance: ${error.message}`);
    } finally {
      setCreatingInstance(false);
    }
  };

  const handleAddInstance = ({ custom = false } = {}) => {
    const resolvedSlot = custom && addInstanceForm.instanceId
      ? Number(addInstanceForm.instanceId)
      : nextSuggestedInstance.instanceId;
    const resolvedIp = custom && addInstanceForm.ipLastOctet
      ? Number(addInstanceForm.ipLastOctet)
      : nextSuggestedInstance.ipLastOctet;

    openConfirmDialog({
      title: custom ? 'Add custom SITL container?' : 'Add next SITL container?',
      message: custom
        ? 'This creates one container without pruning the rest of the fleet.'
        : 'This creates the next free slot without changing the rest of the fleet.',
      facts: [
        `slot ${resolvedSlot}`,
        `IP .${resolvedIp}`,
        `${resolvedImageSelection.repo || 'image'}:${resolvedImageSelection.tag || 'latest'}`,
      ],
      confirmLabel: custom ? 'Create' : 'Add next',
      tone: 'default',
      run: () => executeAddInstance({ custom }),
    });
  };

  const executeRestartInstance = async (instanceName) => {
    if (!instanceName) {
      return;
    }
    setSubmitting(true);
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

  const handleRestartInstance = (instance = selectedInstance) => {
    if (!instance?.name) {
      return;
    }
    openConfirmDialog({
      title: `Restart ${instance.name}?`,
      message: 'Only the selected container will restart. The rest of the fleet stays visible and running.',
      facts: [
        formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name),
        getPrimaryInstanceIp(instance, preferredNetworkName),
      ],
      confirmLabel: 'Restart',
      tone: 'default',
      run: () => executeRestartInstance(instance.name),
    });
  };

  const executeRemoveInstance = async (instanceName) => {
    setSubmitting(true);
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
      toast.success(operation.summary || `Removal queued for ${instanceName}`);
      setSelectedInstance((current) => (current?.name === instanceName ? null : current));
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

  const handleRemoveInstance = (instance = selectedInstance) => {
    if (!instance?.name) {
      return;
    }
    openConfirmDialog({
      title: `Remove ${instance.name}?`,
      message: 'This force-removes the selected local SITL container.',
      facts: [
        formatCompactDroneIdentity(instance.pos_id_hint, instance.hw_id, instance.name),
        getPrimaryInstanceIp(instance, preferredNetworkName),
      ],
      confirmLabel: 'Remove',
      tone: 'danger',
      run: () => executeRemoveInstance(instance.name),
    });
  };

  const executeBatchInstanceAction = async (action) => {
    setSubmitting(true);
    try {
      const operation = await runSitlInstanceAction({
        action,
        instance_names: visibleInstanceNames,
      });
      setSelectedOperationId(operation.operation_id);
      toast.success(operation.summary || `Queued ${action} for ${visibleInstanceNames.length} instance(s)`);
      setBatchActionsExpanded(false);
      if (action === 'remove') {
        setSelectedInstance(null);
      }
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to ${action} filtered instances: ${error.message}`);
    } finally {
      setSubmitting(false);
    }
  };

  const handleBatchInstanceAction = (action) => {
    if (visibleInstanceNames.length === 0) {
      return;
    }
    const label = action === 'restart' ? 'Restart visible' : 'Remove visible';
    openConfirmDialog({
      title: `${label}?`,
      message: action === 'restart'
        ? 'This applies restart to every container in the current filtered list.'
        : 'This removes every container in the current filtered list.',
      facts: [
        `${visibleInstanceNames.length} visible`,
        visibleInstanceNames.slice(0, 3).join(', '),
        ...(visibleInstanceNames.length > 3 ? [`+${visibleInstanceNames.length - 3} more`] : []),
      ],
      confirmLabel: label,
      tone: action === 'remove' ? 'danger' : 'default',
      run: () => executeBatchInstanceAction(action),
    });
  };

  const executeImageRelease = async () => {
    if (!resolvedReleaseVersionTag) {
      toast.error('Output Docker tag is required before saving an image.');
      return;
    }
    setReleasingImage(true);
    try {
      const operation = await releaseSitlImage({
        base_image_ref: imageReleaseForm.baseImageRef,
        image_repo: imageReleaseForm.imageRepo,
        version_tag: resolvedReleaseVersionTag,
        repo_url: imageReleaseForm.repoUrl || null,
        branch: imageReleaseForm.branch || null,
        tag_latest: Boolean(imageReleaseForm.tagLatest),
        tag_commit: Boolean(imageReleaseForm.tagCommit),
        export_archive: Boolean(imageReleaseForm.exportArchive),
        archive_basename: imageReleaseForm.archiveBasename || null,
        output_dir: imageReleaseForm.outputDir || null,
        compress_archive: Boolean(imageReleaseForm.compressArchive),
      });
      setSelectedOperationId(operation.operation_id);
      toast.success(operation.summary || 'SITL image save queued');
      setImageReleaseExpanded(false);
      refreshVisibilityRef.current = 'auto';
      setRefreshTick((current) => current + 1);
    } catch (error) {
      toast.error(`Failed to save SITL image: ${error.message}`);
    } finally {
      setReleasingImage(false);
    }
  };

  const handleImageRelease = () => {
    if (!resolvedReleaseVersionTag) {
      toast.error('Set an output Docker tag before saving the image.');
      return;
    }
    openConfirmDialog({
      title: 'Save SITL image?',
      message: 'This builds a fresh flattened image from the selected base image and applies the requested tags.',
      facts: [
        `${imageReleaseForm.baseImageRef}`,
        `${imageReleaseForm.imageRepo}:${resolvedReleaseVersionTag}`,
        ...(imageReleaseForm.tagLatest ? ['tag latest'] : []),
        ...(imageReleaseForm.tagCommit ? ['tag commit'] : []),
        ...(imageReleaseForm.exportArchive
          ? [imageReleaseForm.compressArchive ? 'export .7z' : 'export .tar']
          : []),
        ...hostResourceState.warnings,
      ],
      confirmLabel: 'Save image',
      tone: 'default',
      run: executeImageRelease,
    });
  };

  const toggleSelectedInstance = (instance) => {
    setSelectedInstance((current) => (current?.name === instance.name ? null : instance));
  };

  const toggleSelectedOperation = (operationId) => {
    setSelectedOperationId((current) => (current === operationId ? null : operationId));
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
            onClick={() => handleRestartInstance(instance)}
            disabled={submitting || Boolean(pendingAction)}
            title="Restart only this container and keep the rest of the fleet visible"
          >
            <FaSyncAlt />
            <span>{pendingAction === 'restart' ? 'Restarting…' : 'Restart'}</span>
          </button>
          <button
            type="button"
            className="sitl-action-button sitl-action-button--danger"
            onClick={() => handleRemoveInstance(instance)}
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
              <div className="sitl-host-health">
                <div className="sitl-collapsible sitl-collapsible--tight">
                  <button
                    type="button"
                    className="sitl-collapsible__toggle"
                    onClick={() => setHostDetailsExpanded((current) => !current)}
                    aria-expanded={hostDetailsExpanded}
                  >
                    <span>Host</span>
                    <span className="sitl-inline-facts">
                      {hostResourceState.badges.map((badge) => (
                        <span key={`${badge.label}-${badge.value}`} className={`sitl-badge sitl-badge--${badge.tone || 'muted'}`}>
                          {badge.label} {badge.value}
                        </span>
                      ))}
                      {hostResourceState.warnings.length > 0 ? (
                        <span className="sitl-badge sitl-badge--warning">
                          <FaExclamationTriangle />
                          <span>{hostResourceState.warnings.length}</span>
                        </span>
                      ) : null}
                    </span>
                  </button>
                  {hostDetailsExpanded ? (
                    <div className="sitl-host-details">
                      {hostResourceState.warnings.length > 0 ? (
                        <div className="sitl-inline-facts">
                          {hostResourceState.warnings.map((warning) => (
                            <span key={warning} className="sitl-badge sitl-badge--warning">
                              <FaExclamationTriangle />
                              <span>{warning}</span>
                            </span>
                          ))}
                        </div>
                      ) : null}
                      <dl className="sitl-key-value-grid">
                        {hostResourceState.detailRows.map((row) => (
                          <div key={row.label}>
                            <dt>{row.label}</dt>
                            <dd>{row.value}</dd>
                          </div>
                        ))}
                        <div>
                          <dt>Portainer</dt>
                          <dd>
                            {portainerUrl ? (
                              <a className="sitl-inline-link" href={portainerUrl} target="_blank" rel="noreferrer">
                                <FaLink />
                                <span>Open panel</span>
                              </a>
                            ) : host?.portainer_available ? 'Detected on this host' : 'Not detected'}
                          </dd>
                        </div>
                      </dl>
                    </div>
                  ) : null}
                </div>
              </div>

              <section className="sitl-section">
                <SectionHeader
                  title="Fleet"
                  detail=""
                />
                <form className="sitl-reconcile-card" onSubmit={handleReconcileSubmit}>
                  <div className="sitl-form-grid">
                    <label className="sitl-field">
                      <FieldLabel label="Count" hint="How many Docker SITL containers should exist after reconcile." />
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
                          <FieldLabel label="Repo" hint="Discovered SITL image repository." />
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
                          <FieldLabel label="Tag" hint="Discovered tag for the selected repository." />
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
                        <FieldLabel label="Image ref" hint="Manual full image reference when no discovered images are available." />
                        <input
                          type="text"
                          aria-label="Manual image reference"
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
                        <FieldLabel label="Custom image ref" hint="Override the discovered repo/tag with a full Docker image reference." />
                        <input
                          type="text"
                          aria-label="Custom image reference"
                          placeholder={policy?.defaults?.default_image || 'mavsdk-drone-show-sitl:latest'}
                          value={reconcileForm.imageRef}
                          onChange={(event) => handleReconcileFieldChange('imageRef', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <FieldLabel label="Start slot" hint="First slot/container ID in the reconciled range." />
                        <input
                          type="number"
                          aria-label="Start slot"
                          min="1"
                          max="999"
                          value={reconcileForm.startId}
                          onChange={(event) => handleReconcileFieldChange('startId', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <FieldLabel label="Start IP" hint="Enter the last octet for the first container IP in the subnet." />
                        <input
                          type="number"
                          aria-label="Start IP last octet"
                          min="2"
                          max="254"
                          value={reconcileForm.startIp}
                          onChange={(event) => handleReconcileFieldChange('startIp', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <FieldLabel label="Subnet" hint="Optional Docker subnet override, for example 172.18.0.0/24." />
                        <input
                          type="text"
                          aria-label="Subnet override"
                          placeholder="172.18.0.0/24"
                          value={reconcileForm.subnet}
                          onChange={(event) => handleReconcileFieldChange('subnet', event.target.value)}
                        />
                      </label>
                      <label className="sitl-field">
                        <FieldLabel label="Docker network" hint="Docker network name used for container IP allocation." />
                        <input
                          type="text"
                          aria-label="Docker network name"
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
                      <button
                        type="button"
                        className={`sitl-action-button ${customCreateExpanded ? 'sitl-action-button--active' : ''}`.trim()}
                        disabled={!dockerState?.daemon_reachable || creatingInstance}
                        onClick={() => setCustomCreateExpanded((current) => !current)}
                        title="Create one exact slot/IP container without pruning the rest of the fleet"
                      >
                        <FaLayerGroup />
                        <span>Custom</span>
                      </button>
                    </div>

                    {customCreateExpanded ? (
                      <div className="sitl-inline-create-card">
                        <div className="sitl-inline-create-form">
                          <label className="sitl-field">
                            <FieldLabel label="Slot" hint={`Example: ${nextSuggestedInstance.instanceId}`} />
                            <input
                              type="number"
                              aria-label="Custom slot"
                              min="1"
                              max="999"
                              placeholder={String(nextSuggestedInstance.instanceId)}
                              value={addInstanceForm.instanceId}
                              onChange={(event) => setAddInstanceForm((current) => ({ ...current, instanceId: event.target.value }))}
                            />
                          </label>
                          <label className="sitl-field">
                            <FieldLabel label="IP" hint={`Enter only the last octet, for example ${nextSuggestedInstance.ipLastOctet}`} />
                            <input
                              type="number"
                              aria-label="Custom IP last octet"
                              min="2"
                              max="254"
                              placeholder={String(nextSuggestedInstance.ipLastOctet)}
                              value={addInstanceForm.ipLastOctet}
                              onChange={(event) => setAddInstanceForm((current) => ({ ...current, ipLastOctet: event.target.value }))}
                            />
                          </label>
                        </div>
                        <div className="sitl-inline-actions">
                          <button
                            type="button"
                            className="sitl-action-button sitl-action-button--primary"
                            disabled={!dockerState?.daemon_reachable || creatingInstance}
                            onClick={() => handleAddInstance({ custom: true })}
                            title="Create one exact-slot container without pruning the rest of the fleet"
                          >
                            <FaPlus />
                            <span>{creatingInstance ? 'Adding…' : 'Add exact'}</span>
                          </button>
                          <button
                            type="button"
                            className="sitl-action-button"
                            onClick={() => {
                              setCustomCreateExpanded(false);
                              setAddInstanceForm({ instanceId: '', ipLastOctet: '' });
                            }}
                            disabled={creatingInstance}
                          >
                            <FaTimes />
                            <span>Close</span>
                          </button>
                        </div>
                      </div>
                    ) : null}

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
                <div className="sitl-collapsible">
                  <button
                    type="button"
                    className="sitl-collapsible__toggle"
                    onClick={() => setOperationsExpanded((current) => !current)}
                    aria-expanded={operationsExpanded}
                  >
                    <span>Ops</span>
                    <span className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">{operations.length}</span>
                      {activeOperationCount > 0 ? (
                        <span className="sitl-badge sitl-badge--warning">{activeOperationCount} active</span>
                      ) : null}
                    </span>
                  </button>
                  {operationsExpanded ? (
                    operations.length === 0 ? (
                      <EmptyState
                        title="No SITL operations yet"
                        detail="Run a reconcile, add, restart, remove, or image save action to populate this list."
                      />
                    ) : (
                      <div className="sitl-compact-list">
                        {operations.map((operation) => {
                          const isSelected = selectedOperationId === operation.operation_id;
                          const detailOperation = selectedOperation?.operation_id === operation.operation_id
                            ? selectedOperation
                            : operation;

                          return (
                            <div key={operation.operation_id} className="sitl-instance-stack">
                              <button
                                type="button"
                                className={`sitl-compact-row ${isSelected ? 'is-active' : ''}`.trim()}
                                onClick={() => toggleSelectedOperation(operation.operation_id)}
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
                              {isSelected ? (
                                <aside className="sitl-instance-detail sitl-instance-detail--inline">
                                  <div className="sitl-instance-detail__header">
                                    <div>
                                      <h3>{detailOperation.summary}</h3>
                                      <p>{detailOperation.detail || detailOperation.operation_type}</p>
                                    </div>
                                    <div className={`sitl-badge sitl-badge--${formatOperationTone(detailOperation)}`}>
                                      {operationLoading && !TERMINAL_OPERATION_STATES.has(detailOperation.status)
                                        ? 'updating…'
                                        : detailOperation.status}
                                    </div>
                                  </div>

                                  <dl className="sitl-key-value-grid">
                                    <div>
                                      <dt>Operation</dt>
                                      <dd>{detailOperation.operation_type}</dd>
                                    </div>
                                    <div>
                                      <dt>Targets</dt>
                                      <dd>{detailOperation.affected_instances.join(', ') || '—'}</dd>
                                    </div>
                                    <div>
                                      <dt>Created</dt>
                                      <dd>{formatTimestamp(detailOperation.created_at)}</dd>
                                    </div>
                                    <div>
                                      <dt>Updated</dt>
                                      <dd>{formatTimestamp(detailOperation.updated_at)}</dd>
                                    </div>
                                  </dl>

                                  <div className="sitl-log-panel">
                                    <div className="sitl-log-panel__header">
                                      <strong>Progress</strong>
                                      <span className="sitl-inline-note">{detailOperation.log_lines.length} line(s)</span>
                                    </div>
                                    <div className="sitl-log-panel__body">
                                      {detailOperation.log_lines.length === 0 ? (
                                        <span className="sitl-log-panel__loading">No progress lines recorded yet.</span>
                                      ) : (
                                        <pre>{detailOperation.log_lines.join('\n')}</pre>
                                      )}
                                    </div>
                                  </div>
                                </aside>
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    )
                  ) : null}
                </div>
              </section>

              <section className="sitl-section">
                <div className="sitl-collapsible">
                  <button
                    type="button"
                    className="sitl-collapsible__toggle"
                    onClick={() => setImagesExpanded((current) => !current)}
                    aria-expanded={imagesExpanded}
                  >
                    <span>Images</span>
                    <span className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">{images.length}</span>
                    </span>
                  </button>
                  {imagesExpanded ? (
                    <>
                      <div className="sitl-section-toolbar">
                        <div className="sitl-inline-facts">
                          <span className="sitl-badge sitl-badge--muted">source {imageReleaseForm.baseImageRef || '—'}</span>
                        </div>
                        <button
                          type="button"
                          className={`sitl-action-button ${imageReleaseExpanded ? 'sitl-action-button--active' : ''}`.trim()}
                          onClick={toggleImageReleasePanel}
                          disabled={!dockerState?.daemon_reachable || releasingImage || images.length === 0}
                          title="Build and optionally export a fresh flattened SITL image"
                        >
                          <FaSave />
                          <span>Save image</span>
                        </button>
                      </div>

                      {imageReleaseExpanded ? (
                        <div className="sitl-image-release-card">
                          <div className="sitl-form-grid">
                            <label className="sitl-field">
                              <FieldLabel label="Source repo" hint="Docker image repository used as the base for the saved image." />
                              <select
                                aria-label="Source image repository"
                                value={releaseSourceSelection.repo}
                                onChange={(event) => handleReleaseSourceRepoChange(event.target.value)}
                              >
                                {imageCatalog.map((image) => (
                                  <option key={image.repo} value={image.repo}>{image.repo}</option>
                                ))}
                              </select>
                            </label>
                          <label className="sitl-field">
                            <FieldLabel label="Source Docker tag" hint="Docker tag from the source image repository. This is not a Git branch or GitHub release." />
                              <select
                                aria-label="Source image tag"
                                value={releaseSourceSelection.tag}
                                onChange={(event) => handleReleaseSourceTagChange(event.target.value)}
                              >
                                {availableReleaseImageTags.map((tag) => (
                                  <option key={tag} value={tag}>{tag}</option>
                                ))}
                              </select>
                            </label>
                            <label className="sitl-field">
                              <FieldLabel label="Output repo" hint="Docker image repository to write after the save operation finishes." />
                              <input
                                type="text"
                                aria-label="Output image repository"
                                value={imageReleaseForm.imageRepo}
                                onChange={(event) => handleReleaseFieldChange('imageRepo', event.target.value)}
                                placeholder="mavsdk-drone-show-sitl"
                              />
                            </label>
                          <label className="sitl-field">
                            <FieldLabel label="Output tag" hint="Docker image tag for the saved image, for example latest, v5.1, demo-20260414, or a short commit tag." />
                              <input
                                type="text"
                                aria-label="Output Docker tag"
                                value={imageReleaseForm.versionTag || resolvedReleaseVersionTag}
                                onChange={(event) => handleReleaseFieldChange('versionTag', sanitizeTagValue(event.target.value, { fallback: '' }))}
                                placeholder={resolvedReleaseVersionTag}
                              />
                            </label>
                          </div>

                          <div className="sitl-toggle-row">
                            <label className="sitl-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(imageReleaseForm.tagLatest)}
                                onChange={(event) => handleReleaseFieldChange('tagLatest', event.target.checked)}
                              />
                              <span>also tag latest</span>
                            </label>
                            <label className="sitl-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(imageReleaseForm.tagCommit)}
                                onChange={(event) => handleReleaseFieldChange('tagCommit', event.target.checked)}
                              />
                              <span>also tag current commit</span>
                            </label>
                            <label className="sitl-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(imageReleaseForm.exportArchive)}
                                onChange={(event) => handleReleaseFieldChange('exportArchive', event.target.checked)}
                              />
                              <span>export archive</span>
                            </label>
                            <label className="sitl-toggle">
                              <input
                                type="checkbox"
                                checked={Boolean(imageReleaseForm.compressArchive)}
                                onChange={(event) => handleReleaseFieldChange('compressArchive', event.target.checked)}
                                disabled={!imageReleaseForm.exportArchive}
                              />
                              <span>compress</span>
                            </label>
                          </div>

                          <div className="sitl-inline-note sitl-inline-note--stacked">
                            <div className="sitl-inline-note__row">
                              <InfoHint
                                label="Archive export guidance"
                                content="Export and compression are optional and slower. Leave them off for the normal fast image-save path."
                              />
                              <span>
                                Optional archive path:{' '}
                                <code>{imageReleaseForm.outputDir || '.'}/{imageReleaseForm.archiveBasename || buildDefaultArchiveBasename(imageReleaseForm.imageRepo || releaseSourceSelection.repo)}.{imageReleaseForm.compressArchive ? '7z' : 'tar'}</code>
                              </span>
                            </div>
                          </div>

                          <details className="sitl-advanced-panel">
                            <summary>Advanced</summary>
                            <div className="sitl-form-grid sitl-form-grid--advanced">
                              <label className="sitl-field">
                                <FieldLabel label="Repo URL" hint="Optional Git repo override baked into the saved image." />
                                <input
                                  type="text"
                                  aria-label="Image repo URL override"
                                  value={imageReleaseForm.repoUrl}
                                  onChange={(event) => handleReleaseFieldChange('repoUrl', event.target.value)}
                                  placeholder="https://github.com/alireza787b/mavsdk_drone_show.git"
                                />
                              </label>
                              <label className="sitl-field">
                                <FieldLabel label="Branch" hint="Optional Git branch override baked into the saved image." />
                                <input
                                  type="text"
                                  aria-label="Image branch override"
                                  value={imageReleaseForm.branch}
                                  onChange={(event) => handleReleaseFieldChange('branch', event.target.value)}
                                  placeholder="main-candidate"
                                />
                              </label>
                              <label className="sitl-field">
                                <FieldLabel label="Output dir" hint="Directory used when exporting an image archive." />
                                <input
                                  type="text"
                                  aria-label="Archive output directory"
                                  value={imageReleaseForm.outputDir}
                                  onChange={(event) => handleReleaseFieldChange('outputDir', event.target.value)}
                                  placeholder="release_artifacts"
                                  disabled={!imageReleaseForm.exportArchive}
                                />
                              </label>
                              <label className="sitl-field">
                                <FieldLabel label="Archive basename" hint="Archive file prefix used when exporting the image." />
                                <input
                                  type="text"
                                  aria-label="Archive basename"
                                  value={imageReleaseForm.archiveBasename}
                                  onChange={(event) => handleReleaseFieldChange('archiveBasename', sanitizeTagValue(event.target.value, { fallback: '' }))}
                                  placeholder="mavsdk-drone-show-sitl-image"
                                  disabled={!imageReleaseForm.exportArchive}
                                />
                              </label>
                            </div>
                          </details>

                          <div className="sitl-inline-actions">
                            <button
                              type="button"
                              className="sitl-action-button sitl-action-button--primary"
                              onClick={handleImageRelease}
                              disabled={!dockerState?.daemon_reachable || releasingImage || images.length === 0}
                            >
                              <FaSave />
                              <span>{releasingImage ? 'Saving…' : 'Save image'}</span>
                            </button>
                            <button
                              type="button"
                              className="sitl-action-button"
                              onClick={() => setImageReleaseExpanded(false)}
                              disabled={releasingImage}
                            >
                              <FaTimes />
                              <span>Close</span>
                            </button>
                          </div>
                        </div>
                      ) : null}

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
                                <span>{image.branch || 'branch —'} · {image.commit || 'commit —'}</span>
                              </div>
                              <div className="sitl-compact-row__side">
                                <span className="sitl-badge" title="Tag">{splitImageRef(image.primary_tag || '').tag || 'untagged'}</span>
                                <small>{formatBytes(image.size_bytes)}</small>
                              </div>
                            </article>
                          ))}
                        </div>
                      )}
                    </>
                  ) : null}
                </div>
              </section>

              <section className="sitl-section">
                <SectionHeader
                  title="Instances"
                  detail=""
                />
                <div className="sitl-section-toolbar">
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
                  <div className="sitl-inline-actions">
                    <button
                      type="button"
                      className={`sitl-action-button ${batchActionsExpanded ? 'sitl-action-button--active' : ''}`.trim()}
                      onClick={() => setBatchActionsExpanded((current) => !current)}
                    >
                      <FaLayerGroup />
                      <span>Batch</span>
                    </button>
                  </div>
                </div>
                {batchActionsExpanded ? (
                  <div className="sitl-batch-panel">
                    <div className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">
                        {filteredInstances.length} of {instances.length} visible
                      </span>
                    </div>
                    <div className="sitl-inline-actions">
                      <button
                        type="button"
                        className="sitl-action-button"
                        onClick={() => handleBatchInstanceAction('restart')}
                        disabled={submitting || visibleInstanceNames.length === 0}
                        title="Restart every container in the filtered list"
                      >
                        <FaSyncAlt />
                        <span>Restart visible</span>
                      </button>
                      <button
                        type="button"
                        className="sitl-action-button sitl-action-button--danger"
                        onClick={() => handleBatchInstanceAction('remove')}
                        disabled={submitting || visibleInstanceNames.length === 0}
                        title="Remove every container in the filtered list"
                      >
                        <FaStop />
                        <span>Remove visible</span>
                      </button>
                    </div>
                  </div>
                ) : null}

                {instances.length === 0 ? (
                  <EmptyState
                    title="No SITL containers detected"
                    detail="Use Fleet Reconcile above to create a fresh local SITL fleet from the selected image."
                  />
                ) : (
                  <div className="sitl-compact-list sitl-compact-list--instances">
                    <div className="sitl-inline-facts">
                      <span className="sitl-badge sitl-badge--muted">
                        {filteredInstances.length} of {instances.length}
                      </span>
                    </div>
                    {filteredInstances.map((instance) => {
                      const isSelected = selectedInstance?.name === instance.name;
                      return (
                        <div key={instance.name} className="sitl-instance-stack">
                          <button
                            type="button"
                            className={`sitl-compact-row ${isSelected ? 'is-active' : ''}`.trim()}
                            onClick={() => toggleSelectedInstance(instance)}
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
                              <small title={`Repo ${getRepoLabel(instance.git_repo_url)} / ${instance.git_branch || 'branch —'}`}>
                                {getRepoLabel(instance.git_repo_url)} · {instance.git_branch || '—'}
                              </small>
                              <small title={`Image ${instance.image_ref || 'not reported'}`}>
                                {getImageShortLabel(instance.image_ref)}
                              </small>
                            </div>
                          </button>
                          {isSelected ? renderInstanceDetail(instance, { inline: true }) : null}
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
            </>
          ) : null}
        </>
      ) : null}
      <ConfirmDialog
        dialog={confirmDialog}
        onCancel={closeConfirmDialog}
        onConfirm={handleConfirmDialog}
        busy={confirmBusy}
      />
    </div>
  );
}

export default SitlControlPage;
