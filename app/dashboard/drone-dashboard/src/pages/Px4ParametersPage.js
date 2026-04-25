import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid } from '@mui/x-data-grid';
import { toast } from 'react-toastify';
import {
  FaBook,
  FaChevronDown,
  FaChevronRight,
  FaRedoAlt,
} from 'react-icons/fa';
import {
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  getSwarmConfigResponse,
  unwrapFleetTelemetryPayload,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import {
  diffPx4ParamSnapshot,
  importQgcParameterFile,
  createPx4ParamPatchJob,
  getPx4ParamPolicy,
  getPx4ParamProfile,
  listPx4ParamProfiles,
  refreshPx4ParamSnapshots,
} from '../services/px4ParamsApiService';
import { buildQgcParameterFile } from '../utilities/px4ParameterFiles';
import { buildMdsParameterProfileFile } from '../utilities/px4ParameterProfiles';
import {
  DRONE_SEARCH_HELP_TEXT,
  DRONE_SEARCH_PLACEHOLDER,
  getDroneDisplayIdentity,
  matchesDroneSearchQuery,
} from '../utilities/dronePresentation';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
import { normalizeTelemetryResponse, FIELD_NAMES } from '../constants/fieldMappings';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import ClusterScopeBar from '../components/ClusterScopeBar';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  filterClustersByScope,
} from '../utilities/swarmDesignUtils';
import Px4ParamInspector from '../components/px4/Px4ParamInspector';
import Px4ParamProfilePanel from '../components/px4/Px4ParamProfilePanel';
import '../styles/Px4ParametersPage.css';

const SNAPSHOT_REFRESH_INTERVAL_MS = 15000;
const COMPACT_BREAKPOINT = 1120;
const TOUCH_COMPACT_BREAKPOINT = 1400;

function isTouchViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  const coarsePointer = typeof window.matchMedia === 'function'
    ? window.matchMedia('(pointer: coarse)').matches
    : false;
  return coarsePointer || (window.navigator?.maxTouchPoints || 0) > 0;
}

function isCompactParameterViewport() {
  if (typeof window === 'undefined') {
    return false;
  }
  const compactLimit = isTouchViewport() ? TOUCH_COMPACT_BREAKPOINT : COMPACT_BREAKPOINT;
  return window.innerWidth <= compactLimit;
}

function trimTrailingZeros(value) {
  return String(value)
    .replace(/(\.\d*?[1-9])0+$/, '$1')
    .replace(/\.0+$/, '')
    .replace(/^-0$/, '0');
}

function formatParameterValue(value, row = null) {
  if (value === null || value === undefined || value === '') {
    return '—';
  }

  if (typeof value === 'number' && Number.isFinite(value)) {
    if (row?.value_type === 'int') {
      return String(Math.trunc(value));
    }

    if (row?.value_type === 'float') {
      const decimalPlaces = Number.isFinite(Number(row?.decimal_places))
        ? Math.min(Math.max(Number(row.decimal_places), 0), 6)
        : null;

      if (decimalPlaces !== null) {
        return trimTrailingZeros(value.toFixed(decimalPlaces));
      }

      return trimTrailingZeros(value.toFixed(4));
    }
  }

  return String(value);
}

function formatParameterRange(row = null) {
  const hasMin = row?.min_value !== null && row?.min_value !== undefined;
  const hasMax = row?.max_value !== null && row?.max_value !== undefined;

  if (!hasMin && !hasMax) {
    return '—';
  }

  if (hasMin && hasMax) {
    return `${formatParameterValue(row.min_value, row)} – ${formatParameterValue(row.max_value, row)}`;
  }

  if (hasMin) {
    return `≥ ${formatParameterValue(row.min_value, row)}`;
  }

  return `≤ ${formatParameterValue(row.max_value, row)}`;
}

function formatRelativeSnapshotAge(snapshot) {
  if (!snapshot?.created_at) {
    return 'No snapshot';
  }

  const ageMs = Math.max(0, Date.now() - snapshot.created_at);
  const seconds = Math.round(ageMs / 1000);
  if (seconds < 60) {
    return `${seconds}s ago`;
  }
  const minutes = Math.round(seconds / 60);
  return `${minutes}m ago`;
}

function isSnapshotStale(snapshot) {
  if (!snapshot?.created_at || !snapshot?.stale_after_ms) {
    return false;
  }
  return Date.now() - snapshot.created_at > snapshot.stale_after_ms;
}

function deriveWriteBlockedReason(policy, selectedDrone, snapshotSummary = null) {
  if (!selectedDrone) {
    return 'Select a target drone first.';
  }

  if (!selectedDrone.online) {
    return 'PX4 parameter writes are blocked while the target drone is offline.';
  }

  if (policy?.mutations?.require_disarmed && selectedDrone[FIELD_NAMES.IS_ARMED]) {
    return 'PX4 parameter writes are blocked while the target drone is armed.';
  }

  if (isSnapshotStale(snapshotSummary)) {
    return 'Refresh the PX4 snapshot before writing stale values.';
  }

  return '';
}

function getSnapshotStatusLabel({ selectedDrone, writeBlockedReason, snapshotSummary }) {
  if (!selectedDrone) {
    return 'No target';
  }
  if (!selectedDrone.online) {
    return 'Offline';
  }
  if (writeBlockedReason) {
    return 'Read only';
  }
  if (isSnapshotStale(snapshotSummary)) {
    return 'Stale snapshot';
  }
  return 'Writable';
}

function buildNotice(tone, title, detail = '', busy = false) {
  return { tone, title, detail, busy };
}

function buildTrackingNotice(snapshot, fallbackTitle = 'Command update') {
  if (!snapshot) {
    return buildNotice('info', fallbackTitle);
  }

  const tone = snapshot.trackingIssue
    ? 'warning'
    : snapshot.isTerminal
      ? snapshot.outcome === 'completed'
        ? 'success'
        : snapshot.outcome === 'partial'
          ? 'warning'
          : 'danger'
      : 'info';

  return buildNotice(
    tone,
    snapshot.progress?.label || fallbackTitle,
    snapshot.progress?.message || '',
  );
}

function summarizeBatchResults(results = []) {
  const total = results.length;
  const applied = results.filter((result) => result.applied).length;
  const verified = results.filter((result) => result.verified).length;
  const failed = results.filter((result) => result.error || !result.applied).length;
  return {
    total,
    applied,
    verified,
    failed,
  };
}

const StatusNotice = ({ notice, className = '' }) => {
  if (!notice) {
    return null;
  }

  return (
    <div
      className={`px4-inline-notice px4-inline-notice--${notice.tone || 'info'} ${className}`.trim()}
      role="status"
      aria-live="polite"
    >
      <strong>
        {notice.busy ? <span className="px4-inline-notice__spinner" aria-hidden="true" /> : null}
        {notice.title}
      </strong>
      {notice.detail ? <span>{notice.detail}</span> : null}
    </div>
  );
};

const CompactParameterRow = ({
  row,
  active,
  onSelect,
  showGroupLabel = false,
}) => {
  const metaLine = [showGroupLabel ? row.group : null, row.category].filter(Boolean).join(' · ');
  const valueMeta = [row.unit, row.value_type?.toUpperCase()].filter(Boolean).join(' · ');

  return (
    <button
      key={row.id}
      type="button"
      className={`px4-compact-card ${active ? 'active' : ''}`}
      onClick={() => onSelect(row.name)}
      aria-label={`Open details for ${row.name}`}
    >
      <div className="px4-compact-card__identity">
        <strong>{row.name}</strong>
        {metaLine ? <span>{metaLine}</span> : null}
      </div>
      <div className="px4-compact-card__aside">
        <div className="px4-compact-card__reading">
          <strong>{row.value}</strong>
          {valueMeta ? <small>{valueMeta}</small> : null}
        </div>
        <div className="px4-compact-card__signals">
          {row.reboot_required ? (
            <span
              className="px4-compact-signal px4-compact-signal--warning"
              role="img"
              aria-label="Restart required"
            >
              <FaRedoAlt />
            </span>
          ) : null}
          {row.docs_url ? (
            <span
              className="px4-compact-signal"
              role="img"
              aria-label="PX4 Docs available"
            >
              <FaBook />
            </span>
          ) : null}
          <span className="px4-compact-signal px4-compact-signal--chevron" aria-hidden="true">
            <FaChevronRight />
          </span>
        </div>
      </div>
    </button>
  );
};

const CompactParameterList = ({
  rows,
  selectedParamName,
  onSelect,
  grouped = false,
  expandedGroup = '',
  onToggleGroup = () => {},
}) => {
  if (!rows.length) {
    return (
      <div className="px4-compact-list__empty">
        No parameters match the current filters.
      </div>
    );
  }

  if (!grouped) {
    return (
      <div className="px4-compact-list">
        {rows.map((row) => (
          <CompactParameterRow
            key={row.id}
            row={row}
            active={row.name === selectedParamName}
            onSelect={onSelect}
            showGroupLabel
          />
        ))}
      </div>
    );
  }

  const groupedRows = rows.reduce((accumulator, row) => {
    const groupLabel = row.group || row.category || 'Ungrouped';
    if (!accumulator.has(groupLabel)) {
      accumulator.set(groupLabel, []);
    }
    accumulator.get(groupLabel).push(row);
    return accumulator;
  }, new Map());

  return (
    <div className="px4-compact-list">
      {Array.from(groupedRows.entries()).map(([groupLabel, groupRows]) => {
        const groupActive = expandedGroup === groupLabel;
        return (
          <section key={groupLabel} className={`px4-compact-group ${groupActive ? 'active' : ''}`}>
            <button
              type="button"
              className={`px4-compact-group__header ${groupActive ? 'active' : ''}`}
              onClick={() => onToggleGroup(groupLabel)}
              aria-expanded={groupActive}
            >
              <div className="px4-compact-group__title">
                <span className="px4-compact-group__chevron" aria-hidden="true">
                  {groupActive ? <FaChevronDown /> : <FaChevronRight />}
                </span>
                <strong>{groupLabel}</strong>
              </div>
              <span className="px4-compact-group__count">{groupRows.length}</span>
            </button>
            {groupActive ? (
              <div className="px4-compact-group__rows">
                {groupRows.map((row) => (
                  <CompactParameterRow
                    key={row.id}
                    row={row}
                    active={row.name === selectedParamName}
                    onSelect={onSelect}
                  />
                ))}
              </div>
            ) : null}
          </section>
        );
      })}
    </div>
  );
};

function parseDraftValue(row, draftValue) {
  if (row.value_type === 'int') {
    return Number.parseInt(draftValue, 10);
  }
  if (row.value_type === 'float') {
    return Number.parseFloat(draftValue);
  }
  return String(draftValue);
}

function downloadTextFile(filename, text) {
  const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

const Px4ParametersPage = () => {
  const [configDrones, setConfigDrones] = useState([]);
  const [telemetryByHwId, setTelemetryByHwId] = useState({});
  const [policy, setPolicy] = useState(null);
  const [droneQuery, setDroneQuery] = useState('');
  const [workspaceMode, setWorkspaceMode] = useState('single');
  const [selectedHwId, setSelectedHwId] = useState('');
  const [swarmAssignments, setSwarmAssignments] = useState([]);
  const [snapshotResponse, setSnapshotResponse] = useState(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [paramQuery, setParamQuery] = useState('');
  const [showModifiedOnly, setShowModifiedOnly] = useState(false);
  const [showSessionChangesOnly, setShowSessionChangesOnly] = useState(false);
  const [showRebootOnly, setShowRebootOnly] = useState(false);
  const [selectedParamName, setSelectedParamName] = useState('');
  const [draftValue, setDraftValue] = useState('');
  const [saving, setSaving] = useState(false);
  const [sessionChangedNames, setSessionChangedNames] = useState(() => new Set());
  const [importPreview, setImportPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [batchTargetMode, setBatchTargetMode] = useState('');
  const [batchSelectedDrones, setBatchSelectedDrones] = useState([]);
  const [batchClusterScope, setBatchClusterScope] = useState('');
  const [batchComposerMode, setBatchComposerMode] = useState('profile');
  const [batchParamName, setBatchParamName] = useState('');
  const [batchValueType, setBatchValueType] = useState('float');
  const [batchDraftValue, setBatchDraftValue] = useState('');
  const [batchApplying, setBatchApplying] = useState(false);
  const [batchJobResult, setBatchJobResult] = useState(null);
  const [profileSummaries, setProfileSummaries] = useState([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileDiffPreview, setProfileDiffPreview] = useState(null);
  const [profileDiffLoading, setProfileDiffLoading] = useState(false);
  const [isCompactViewport, setIsCompactViewport] = useState(
    () => isCompactParameterViewport(),
  );
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [singleNotice, setSingleNotice] = useState(null);
  const [batchNotice, setBatchNotice] = useState(null);
  const [profileNotice, setProfileNotice] = useState(null);
  const [allowOfflineSkip, setAllowOfflineSkip] = useState(false);
  const [rebootingPx4, setRebootingPx4] = useState(false);
  const [expandedCompactGroup, setExpandedCompactGroup] = useState('');
  const fileInputRef = useRef(null);

  const deferredDroneQuery = useDeferredValue(droneQuery);
  const deferredParamQuery = useDeferredValue(paramQuery);

  useEffect(() => {
    const handleResize = () => {
      setIsCompactViewport(isCompactParameterViewport());
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    let active = true;

    async function loadPolicy() {
      try {
        const response = await getPx4ParamPolicy();
        if (active) {
          setPolicy(response.data);
        }
      } catch (error) {
        console.warn('Failed to load PX4 parameter policy:', error);
      }
    }

    loadPolicy();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadProfiles() {
      setProfilesLoading(true);
      try {
        const response = await listPx4ParamProfiles();
        if (!active) {
          return;
        }
        const profiles = Array.isArray(response.data?.profiles) ? response.data.profiles : [];
        setProfileSummaries(profiles);
      } catch (error) {
        toast.error('Failed to load PX4 parameter profiles.');
      } finally {
        if (active) {
          setProfilesLoading(false);
        }
      }
    }

    loadProfiles();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadSwarmAssignments() {
      try {
        const response = await getSwarmConfigResponse();
        if (active) {
          setSwarmAssignments(unwrapSwarmConfigPayload(response.data));
        }
      } catch (error) {
        console.warn('Failed to load swarm assignments for PX4 parameter batch scope:', error);
      }
    }

    loadSwarmAssignments();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadFleetConfig() {
      try {
        const response = await getFleetConfigResponse();
        if (active && Array.isArray(response.data)) {
          setConfigDrones(response.data);
        }
      } catch (error) {
        toast.error('Failed to load fleet configuration for PX4 parameter management.');
      }
    }

    loadFleetConfig();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    async function loadTelemetry() {
      try {
        const response = await getFleetTelemetryResponse();
        if (!active) {
          return;
        }
        const clockMeta = {
          receivedAtMs: Date.now(),
          serverNowMs: response.headers?.['x-mds-server-time'] ?? response.headers?.date ?? null,
        };
        const normalized = normalizeTelemetryResponse(
          unwrapFleetTelemetryPayload(response.data),
          clockMeta,
        );
        setTelemetryByHwId(normalized || {});
      } catch (error) {
        console.warn('Failed to load fleet telemetry for PX4 parameter management:', error);
      }
    }

    loadTelemetry();
    const interval = setInterval(loadTelemetry, SNAPSHOT_REFRESH_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const mergedDrones = useMemo(() => {
    const configMap = new Map(
      (configDrones || []).map((entry) => [String(entry.hw_id), entry]),
    );
    const merged = (configDrones || []).map((entry) => {
      const hwId = String(entry.hw_id);
      return {
        ...entry,
        ...(telemetryByHwId[hwId] || {}),
        hw_id: hwId,
        online: Boolean(telemetryByHwId[hwId]),
      };
    });

    Object.entries(telemetryByHwId || {}).forEach(([hwId, telemetry]) => {
      if (!configMap.has(hwId)) {
        merged.push({
          ...telemetry,
          hw_id: hwId,
          pos_id: telemetry?.pos_id || '',
          online: true,
        });
      }
    });

    return merged;
  }, [configDrones, telemetryByHwId]);

  const filteredDrones = useMemo(
    () => mergedDrones.filter((drone) => matchesDroneSearchQuery(drone, deferredDroneQuery)),
    [deferredDroneQuery, mergedDrones],
  );
  const swarmViewModel = useMemo(
    () => buildSwarmViewModel(swarmAssignments, mergedDrones),
    [mergedDrones, swarmAssignments],
  );
  const batchClusterOptions = useMemo(
    () => buildClusterScopeOptions(swarmViewModel?.clusters || [], mergedDrones.length)
      .filter((option) => option.id !== 'all' && option.id !== 'attention'),
    [mergedDrones.length, swarmViewModel?.clusters],
  );
  const batchClusterTargetIds = useMemo(() => {
    if (!batchClusterScope) {
      return [];
    }
    return Array.from(
      new Set(
        filterClustersByScope(swarmViewModel?.clusters || [], batchClusterScope)
          .flatMap((cluster) => cluster.drones.map((drone) => String(drone.hw_id))),
      ),
    );
  }, [batchClusterScope, swarmViewModel?.clusters]);

  useEffect(() => {
    if (!filteredDrones.length) {
      return;
    }
    if (!selectedHwId) {
      setSelectedHwId(String(filteredDrones[0].hw_id));
    }
  }, [filteredDrones, selectedHwId]);

  useEffect(() => {
    if (!profileSummaries.length) {
      setSelectedProfileId('');
      return;
    }
    if (!selectedProfileId || !profileSummaries.some((profile) => profile.profile_id === selectedProfileId)) {
      setSelectedProfileId(profileSummaries[0].profile_id);
    }
  }, [profileSummaries, selectedProfileId]);

  useEffect(() => {
    if (!selectedProfileId) {
      setSelectedProfile(null);
      return;
    }

    let active = true;
    async function loadProfile() {
      setProfileLoading(true);
      try {
        const response = await getPx4ParamProfile(selectedProfileId);
        if (active) {
          setSelectedProfile(response.data);
        }
      } catch (error) {
        if (active) {
          toast.error('Failed to load the selected PX4 parameter profile.');
          setSelectedProfile(null);
        }
      } finally {
        if (active) {
          setProfileLoading(false);
        }
      }
    }

    loadProfile();
    return () => {
      active = false;
    };
  }, [selectedProfileId]);

  useEffect(() => {
    setProfileDiffPreview(null);
  }, [selectedProfileId, snapshotResponse?.snapshot?.snapshot_id]);

  useEffect(() => {
    if (workspaceMode !== 'single') {
      setInspectorOpen(false);
    }
  }, [workspaceMode]);

  useEffect(() => {
    if (!batchClusterOptions.length) {
      if (batchTargetMode === 'cluster') {
        setBatchTargetMode('');
      }
      if (batchClusterScope) {
        setBatchClusterScope('');
      }
      return;
    }

    if (!batchClusterOptions.some((option) => String(option.id) === String(batchClusterScope))) {
      setBatchClusterScope(String(batchClusterOptions[0].id));
    }
  }, [batchClusterOptions, batchClusterScope, batchTargetMode]);

  const selectedDrone = useMemo(
    () => mergedDrones.find((drone) => String(drone.hw_id) === String(selectedHwId)) || null,
    [mergedDrones, selectedHwId],
  );

  const selectedIdentity = useMemo(
    () => (selectedDrone ? getDroneDisplayIdentity(selectedDrone) : null),
    [selectedDrone],
  );

  const refreshSnapshot = React.useCallback(async () => {
    if (!selectedHwId) {
      return;
    }

    setSnapshotLoading(true);
    setSingleNotice(buildNotice('info', 'Refreshing snapshot', `Reading PX4 parameters for ${selectedIdentity?.primary || `H${selectedHwId}`}.`, true));
    try {
      const response = await refreshPx4ParamSnapshots({
        hwIds: [String(selectedHwId)],
        componentId: policy?.mutations?.supported_component_ids?.[0] || 1,
      });
      const snapshot = response.data?.snapshots?.[0] || null;
      const error = response.data?.errors?.[0] || null;

      if (error && !snapshot) {
        toast.error(error.error || 'Failed to refresh PX4 parameter snapshot.');
        setSnapshotResponse(null);
        setSingleNotice(buildNotice('danger', 'Snapshot refresh failed', error.error || 'No snapshot was returned.'));
        return;
      }

      if (snapshot) {
        setSnapshotResponse(snapshot);
        setSelectedParamName((currentName) => {
          return snapshot.rows.some((row) => row.name === currentName) ? currentName : '';
        });
        setSingleNotice(buildNotice(
          'success',
          'Snapshot ready',
          `${snapshot.rows.length} parameter row(s) loaded for ${selectedIdentity?.primary || `H${selectedHwId}`}.`,
        ));
      }
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to refresh PX4 parameter snapshot.');
      setSingleNotice(buildNotice(
        'danger',
        'Snapshot refresh failed',
        error?.response?.data?.detail || 'Unable to read PX4 parameters from the selected drone.',
      ));
    } finally {
      setSnapshotLoading(false);
    }
  }, [policy?.mutations?.supported_component_ids, selectedHwId, selectedIdentity?.primary]);

  useEffect(() => {
    if (!selectedHwId) {
      return;
    }
    refreshSnapshot();
  }, [refreshSnapshot, selectedHwId]);

  const selectedRow = useMemo(
    () => snapshotResponse?.rows?.find((row) => row.name === selectedParamName) || null,
    [selectedParamName, snapshotResponse],
  );

  useEffect(() => {
    setDraftValue(selectedRow ? String(selectedRow.value ?? '') : '');
  }, [selectedRow]);

  const filteredRows = useMemo(() => {
    const rows = Array.isArray(snapshotResponse?.rows) ? snapshotResponse.rows : [];
    const query = String(deferredParamQuery || '').trim().toLowerCase();

    return rows.filter((row) => {
      if (showModifiedOnly && (row.default_value === null || row.default_value === undefined || row.default_value === row.value)) {
        return false;
      }
      if (showSessionChangesOnly && !sessionChangedNames.has(row.name)) {
        return false;
      }
      if (showRebootOnly && !row.reboot_required) {
        return false;
      }
      if (!query) {
        return true;
      }
      return [
        row.name,
        row.short_description,
        row.long_description,
        row.unit,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(query);
    });
  }, [deferredParamQuery, sessionChangedNames, showModifiedOnly, showRebootOnly, showSessionChangesOnly, snapshotResponse?.rows]);

  const compactGroupingEnabled = isCompactViewport && !String(deferredParamQuery || '').trim();

  useEffect(() => {
    if (!compactGroupingEnabled || !filteredRows.length) {
      return;
    }
    const availableGroups = new Set(
      filteredRows.map((row) => row.group || row.category || 'Ungrouped'),
    );
    if (expandedCompactGroup && availableGroups.has(expandedCompactGroup)) {
      return;
    }
    const selectedGroup = filteredRows.find((row) => row.name === selectedParamName)?.group
      || filteredRows.find((row) => row.name === selectedParamName)?.category
      || filteredRows[0]?.group
      || filteredRows[0]?.category
      || 'Ungrouped';
    if (selectedGroup && expandedCompactGroup !== selectedGroup) {
      setExpandedCompactGroup(selectedGroup);
    }
  }, [compactGroupingEnabled, expandedCompactGroup, filteredRows, selectedParamName]);

  const writeBlockedReason = deriveWriteBlockedReason(policy, selectedDrone, snapshotResponse?.snapshot);
  const snapshotStatusLabel = getSnapshotStatusLabel({
    selectedDrone,
    writeBlockedReason,
    snapshotSummary: snapshotResponse?.snapshot,
  });
  const metadataQualityLabel = snapshotResponse?.snapshot?.metadata_quality
    ? String(snapshotResponse.snapshot.metadata_quality).replace(/_/g, ' ')
    : 'unknown';
  const metadataWarning = snapshotResponse?.snapshot?.metadata_warning || '';
  const metadataWarningSummary = metadataWarning
    ? 'Live values are available; labels, defaults, ranges, or docs may be incomplete.'
    : '';
  const modifiedRowCount = useMemo(
    () => (snapshotResponse?.rows || []).filter((row) => row.default_value !== null
      && row.default_value !== undefined
      && row.default_value !== row.value).length,
    [snapshotResponse?.rows],
  );
  const rebootFlaggedCount = useMemo(
    () => (snapshotResponse?.rows || []).filter((row) => row.reboot_required).length,
    [snapshotResponse?.rows],
  );
  const selectedHiddenByFilter = Boolean(
    selectedDrone && deferredDroneQuery && !filteredDrones.some((drone) => String(drone.hw_id) === String(selectedHwId)),
  );
  const compareTargetLabel = selectedIdentity?.primary || '';
  const batchTargetHwIds = useMemo(() => {
    if (!batchTargetMode) {
      return [];
    }
    if (batchTargetMode === 'selected') {
      return batchSelectedDrones.map((value) => String(value));
    }
    if (batchTargetMode === 'cluster') {
      return batchClusterTargetIds;
    }
    return mergedDrones.map((drone) => String(drone.hw_id));
  }, [batchClusterTargetIds, batchSelectedDrones, batchTargetMode, mergedDrones]);
  const batchTargetLabel = !batchTargetMode
    ? 'No scope selected'
    : batchTargetMode === 'selected'
    ? `${batchSelectedDrones.length} selected drone${batchSelectedDrones.length === 1 ? '' : 's'}`
    : batchTargetMode === 'cluster'
      ? `${batchClusterOptions.find((option) => String(option.id) === String(batchClusterScope))?.label || 'Cluster'} · ${batchClusterTargetIds.length} drones`
      : `All ${mergedDrones.length} drones`;
  const offlineBatchTargets = useMemo(
    () => mergedDrones.filter((drone) => batchTargetHwIds.includes(String(drone.hw_id)) && !drone.online),
    [batchTargetHwIds, mergedDrones],
  );
  const onlineBatchTargetHwIds = useMemo(
    () => batchTargetHwIds.filter((hwId) => !offlineBatchTargets.some((drone) => String(drone.hw_id) === String(hwId))),
    [batchTargetHwIds, offlineBatchTargets],
  );
  const effectiveBatchTargetHwIds = useMemo(
    () => (allowOfflineSkip ? onlineBatchTargetHwIds : batchTargetHwIds),
    [allowOfflineSkip, batchTargetHwIds, onlineBatchTargetHwIds],
  );
  const batchTargetWarning = useMemo(() => {
    if (offlineBatchTargets.length === 0) {
      return '';
    }
    if (allowOfflineSkip) {
      return `${offlineBatchTargets.length} offline target drone${offlineBatchTargets.length === 1 ? '' : 's'} will be skipped.`;
    }
    return `${offlineBatchTargets.length} target drone${offlineBatchTargets.length === 1 ? '' : 's'} are offline. Confirm that you want to skip them or adjust the scope.`;
  }, [allowOfflineSkip, offlineBatchTargets.length]);

  useEffect(() => {
    if (offlineBatchTargets.length === 0 && allowOfflineSkip) {
      setAllowOfflineSkip(false);
    }
  }, [allowOfflineSkip, offlineBatchTargets.length]);

  const batchWriteBlockedReason = useMemo(() => {
    if (!batchTargetMode) {
      return 'Choose a target scope before applying batch parameter changes.';
    }
    if (batchTargetHwIds.length === 0) {
      return 'Choose at least one target drone.';
    }
    if (offlineBatchTargets.length > 0 && !allowOfflineSkip) {
      return 'Offline drones are included in the current target scope. Enable skip-offline mode or adjust the scope.';
    }
    if (effectiveBatchTargetHwIds.length === 0) {
      return 'No online target drones remain after applying the current scope rules.';
    }
    if (!policy?.mutations?.require_disarmed) {
      return '';
    }
    const armedTargets = mergedDrones.filter((drone) => effectiveBatchTargetHwIds.includes(String(drone.hw_id)) && drone[FIELD_NAMES.IS_ARMED]);
    if (armedTargets.length > 0) {
      return `${armedTargets.length} target drone${armedTargets.length === 1 ? '' : 's'} are armed. Batch writes are blocked.`;
    }
    return '';
  }, [
    allowOfflineSkip,
    batchTargetHwIds,
    batchTargetMode,
    effectiveBatchTargetHwIds,
    mergedDrones,
    offlineBatchTargets.length,
    policy?.mutations?.require_disarmed,
  ]);
  const batchResultSummary = useMemo(
    () => summarizeBatchResults(batchJobResult?.results || []),
    [batchJobResult?.results],
  );
  const rebootBlockedReason = useMemo(() => {
    if (!selectedDrone) {
      return 'Select a target drone first.';
    }
    if (!selectedDrone.online) {
      return 'PX4 reboot is blocked while the target drone is offline.';
    }
    if (selectedDrone[FIELD_NAMES.IS_ARMED]) {
      return 'PX4 reboot is blocked while the target drone is armed.';
    }
    return '';
  }, [selectedDrone]);

  const handleSelectParameter = (paramName) => {
    setSelectedParamName(paramName);
    setInspectorOpen(true);
  };

  const handleSave = async () => {
    if (!selectedRow || !selectedDrone) {
      return;
    }

    const parsedValue = parseDraftValue(selectedRow, draftValue);
    if (Number.isNaN(parsedValue)) {
      toast.error('Enter a valid value before saving.');
      return;
    }

    setSaving(true);
    setSingleNotice(buildNotice('info', 'Writing and verifying', `${selectedRow.name} → ${selectedIdentity?.primary || `H${selectedDrone.hw_id}`}.`, true));
    try {
      const response = await createPx4ParamPatchJob({
        hwIds: [String(selectedDrone.hw_id)],
        source: 'manual',
        verifyReadback: true,
        entries: [
          {
            component_id: selectedRow.component_id || 1,
            name: selectedRow.name,
            value_type: selectedRow.value_type,
            value: parsedValue,
          },
        ],
      });

      const job = response.data;
      const result = job?.results?.[0];
      if (!result || result.error || !result.applied) {
        toast.error(result?.error || 'PX4 parameter update failed.');
        return;
      }

      if (result.verified) {
        toast.success(`${selectedRow.name} updated and verified.`);
        setSingleNotice(buildNotice('success', 'Parameter saved', `${selectedRow.name} updated and verified on ${selectedIdentity?.primary || `H${selectedDrone.hw_id}`}.`));
      } else {
        toast.warn(`${selectedRow.name} was written, but verification did not fully confirm the readback.`);
        setSingleNotice(buildNotice('warning', 'Parameter saved with verification warning', `${selectedRow.name} was written, but readback verification was incomplete.`));
      }

      setSessionChangedNames((current) => {
        const next = new Set(current);
        next.add(selectedRow.name);
        return next;
      });
      await refreshSnapshot();
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply PX4 parameter patch job.');
      setSingleNotice(buildNotice(
        'danger',
        'Parameter save failed',
        error?.response?.data?.detail || 'The patch job did not complete successfully.',
      ));
    } finally {
      setSaving(false);
    }
  };

  const handleExportQgc = () => {
    if (!snapshotResponse) {
      return;
    }
    const exportBundle = buildQgcParameterFile(snapshotResponse);
    downloadTextFile(exportBundle.filename, exportBundle.text);
    if (exportBundle.skippedRows.length > 0) {
      toast.info(`Exported QGC parameter file. Skipped ${exportBundle.skippedRows.length} non-QGC row(s).`);
    } else {
      toast.success('Exported current snapshot as a QGC parameter file.');
    }
  };

  const handleChooseImportFile = () => {
    fileInputRef.current?.click();
  };

  const handleImportFile = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file || !snapshotResponse?.snapshot?.snapshot_id) {
      return;
    }

    setImporting(true);
    setSingleNotice(buildNotice('info', 'Reading imported file', `Comparing ${file.name} against the current drone snapshot.`, true));
    try {
      const content = await file.text();
      const importResponse = await importQgcParameterFile(content);
      const diffResponse = await diffPx4ParamSnapshot({
        snapshotId: snapshotResponse.snapshot.snapshot_id,
        desiredEntries: importResponse.data.entries,
        includeUnchanged: false,
      });

      setImportPreview({
        fileName: file.name,
        importResponse: importResponse.data,
        diffResponse: diffResponse.data,
      });

      if ((diffResponse.data?.total_changed || 0) === 0) {
        toast.info('Imported file matches the current PX4 snapshot. No changes are pending.');
        setSingleNotice(buildNotice('info', 'Imported file matches current snapshot', `${file.name} does not change any parameter values.`));
      } else {
        toast.success(`Imported ${importResponse.data.total_entries} parameter row(s) for review.`);
        setSingleNotice(buildNotice('success', 'Imported file ready for review', `${diffResponse.data.total_changed} changed row(s) are ready to apply.`));
      }
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to import and compare the QGC parameter file.');
      setSingleNotice(buildNotice(
        'danger',
        'Import failed',
        error?.response?.data?.detail || 'The QGC parameter file could not be parsed or compared.',
      ));
    } finally {
      setImporting(false);
    }
  };

  const handleApplyImportedChanges = async () => {
    if (!selectedDrone || !importPreview?.importResponse?.entries?.length) {
      return;
    }

    setSaving(true);
    setSingleNotice(buildNotice('info', 'Applying imported changes', `${importPreview.importResponse.entries.length} imported row(s) are being written and verified.`, true));
    try {
      const response = await createPx4ParamPatchJob({
        hwIds: [String(selectedDrone.hw_id)],
        source: 'qgc_import',
        verifyReadback: true,
        entries: importPreview.importResponse.entries,
      });
      const result = response.data?.results?.[0];
      if (!result || result.error || !result.applied) {
        toast.error(result?.error || 'Imported PX4 parameter patch failed.');
        return;
      }

      toast.success(`Applied ${importPreview.importResponse.entries.length} imported parameter row(s).`);
      setSingleNotice(buildNotice('success', 'Imported changes applied', `${importPreview.importResponse.entries.length} parameter row(s) were applied successfully.`));
      setSessionChangedNames((current) => {
        const next = new Set(current);
        importPreview.importResponse.entries.forEach((entry) => next.add(entry.name));
        return next;
      });
      setImportPreview(null);
      await refreshSnapshot();
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply imported PX4 parameter patch.');
      setSingleNotice(buildNotice(
        'danger',
        'Imported changes failed',
        error?.response?.data?.detail || 'The imported patch could not be applied.',
      ));
    } finally {
      setSaving(false);
    }
  };

  const handlePreviewProfileDiff = async () => {
    if (!selectedProfile?.entries?.length || !snapshotResponse?.snapshot?.snapshot_id) {
      toast.info('Refresh a drone snapshot before comparing a saved profile.');
      return;
    }

    setProfileDiffLoading(true);
    setProfileNotice(buildNotice('info', 'Comparing profile', `Reviewing ${selectedProfile.name} against ${compareTargetLabel || 'the selected drone snapshot'}.`, true));
    try {
      const response = await diffPx4ParamSnapshot({
        snapshotId: snapshotResponse.snapshot.snapshot_id,
        desiredEntries: selectedProfile.entries,
        includeUnchanged: false,
      });
      setProfileDiffPreview(response.data);
      if ((response.data?.total_changed || 0) === 0) {
        toast.info('The selected profile already matches the current drone snapshot.');
        setProfileNotice(buildNotice('info', 'Profile already matches', `${selectedProfile.name} does not change the current snapshot.`));
      } else {
        setProfileNotice(buildNotice('success', 'Profile diff ready', `${response.data.total_changed} changed row(s) are ready for review.`));
      }
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to compare the selected profile against the current drone snapshot.');
      setProfileNotice(buildNotice(
        'danger',
        'Profile compare failed',
        error?.response?.data?.detail || 'Unable to compare the selected profile against the current drone snapshot.',
      ));
    } finally {
      setProfileDiffLoading(false);
    }
  };

  const handleExportProfile = () => {
    if (!selectedProfile) {
      return;
    }
    const exportBundle = buildMdsParameterProfileFile(selectedProfile);
    downloadTextFile(exportBundle.filename, exportBundle.text);
    toast.success('Exported typed MDS parameter profile JSON.');
  };

  const handleBatchTargetToggle = (hwId) => {
    setBatchSelectedDrones((current) => {
      const normalized = String(hwId);
      return current.includes(normalized)
        ? current.filter((value) => value !== normalized)
        : [...current, normalized];
    });
  };

  const handleApplyBatchPatch = async () => {
    const normalizedName = String(batchParamName || '').trim().toUpperCase();
    if (!normalizedName) {
      toast.error('Enter a PX4 parameter name for the batch patch.');
      return;
    }
    if (!effectiveBatchTargetHwIds.length) {
      toast.error('Choose at least one target drone for the batch patch.');
      return;
    }

    const parsedValue = batchValueType === 'int'
      ? Number.parseInt(batchDraftValue, 10)
      : batchValueType === 'float'
        ? Number.parseFloat(batchDraftValue)
        : String(batchDraftValue);
    if ((batchValueType === 'int' || batchValueType === 'float') && Number.isNaN(parsedValue)) {
      toast.error('Enter a valid numeric batch value.');
      return;
    }

    setBatchApplying(true);
    setBatchNotice(buildNotice(
      'info',
      'Applying manual patch',
      `Dispatching ${normalizedName} to ${effectiveBatchTargetHwIds.length} target drone(s)${offlineBatchTargets.length > 0 && allowOfflineSkip ? ` and skipping ${offlineBatchTargets.length} offline target(s)` : ''}.`,
      true,
    ));
    try {
      const response = await createPx4ParamPatchJob({
        hwIds: effectiveBatchTargetHwIds,
        source: 'manual',
        verifyReadback: true,
        entries: [
          {
            component_id: policy?.mutations?.supported_component_ids?.[0] || 1,
            name: normalizedName,
            value_type: batchValueType,
            value: parsedValue,
          },
        ],
      });
      setBatchJobResult(response.data);
      const summary = summarizeBatchResults(response.data?.results || []);
      toast.success(`Batch patch dispatched to ${effectiveBatchTargetHwIds.length} drone(s).`);
      setBatchNotice(buildNotice(
        summary.failed > 0 ? 'warning' : 'success',
        'Batch patch finished',
        `${summary.applied}/${summary.total} applied, ${summary.verified}/${summary.total} verified${offlineBatchTargets.length > 0 && allowOfflineSkip ? `, ${offlineBatchTargets.length} offline skipped` : ''}.`,
      ));
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply the PX4 batch patch.');
      setBatchNotice(buildNotice(
        'danger',
        'Batch patch failed',
        error?.response?.data?.detail || 'The batch patch could not be applied.',
      ));
    } finally {
      setBatchApplying(false);
    }
  };

  const handleApplyBatchProfile = async () => {
    if (!selectedProfile?.entries?.length) {
      toast.error('Choose a saved profile before applying a profile patch.');
      return;
    }
    if (batchWriteBlockedReason) {
      toast.error(batchWriteBlockedReason);
      return;
    }

    setBatchApplying(true);
    setBatchNotice(buildNotice(
      'info',
      'Applying saved profile',
      `Dispatching ${selectedProfile.name} to ${effectiveBatchTargetHwIds.length} target drone(s)${offlineBatchTargets.length > 0 && allowOfflineSkip ? ` and skipping ${offlineBatchTargets.length} offline target(s)` : ''}.`,
      true,
    ));
    try {
      const response = await createPx4ParamPatchJob({
        hwIds: effectiveBatchTargetHwIds,
        source: 'mds_profile',
        verifyReadback: true,
        entries: selectedProfile.entries,
      });
      setBatchJobResult(response.data);
      const summary = summarizeBatchResults(response.data?.results || []);
      toast.success(`Profile patch dispatched to ${effectiveBatchTargetHwIds.length} drone(s).`);
      setBatchNotice(buildNotice(
        summary.failed > 0 ? 'warning' : 'success',
        'Profile apply finished',
        `${summary.applied}/${summary.total} applied, ${summary.verified}/${summary.total} verified${offlineBatchTargets.length > 0 && allowOfflineSkip ? `, ${offlineBatchTargets.length} offline skipped` : ''}.`,
      ));
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply the selected PX4 profile.');
      setBatchNotice(buildNotice(
        'danger',
        'Profile apply failed',
        error?.response?.data?.detail || 'The selected profile could not be applied.',
      ));
    } finally {
      setBatchApplying(false);
    }
  };

  const handleRebootPx4 = async () => {
    if (!selectedDrone || rebootBlockedReason) {
      toast.error(rebootBlockedReason || 'Select a target drone first.');
      setSingleNotice(buildNotice('warning', 'PX4 reboot blocked', rebootBlockedReason || 'No target drone is selected.'));
      return;
    }

    setRebootingPx4(true);
    setSingleNotice(buildNotice('info', 'Dispatching PX4 reboot', `Submitting reboot for ${selectedIdentity?.primary || `H${selectedDrone.hw_id}`}.`, true));
    try {
      await submitCommandWithLifecycleFeedback({
        missionType: String(DRONE_ACTION_TYPES.REBOOT_FC),
        target_drones: [String(selectedDrone.hw_id)],
        triggerTime: '0',
        uiMeta: {
          operatorLabel: 'Reboot PX4',
        },
      }, {
        onCommandAccepted: (snapshot) => setSingleNotice(buildTrackingNotice(snapshot, 'PX4 reboot accepted')),
        onStatusUpdate: (snapshot) => setSingleNotice(buildTrackingNotice(snapshot, 'PX4 reboot update')),
        onTrackingComplete: (snapshot) => setSingleNotice(buildTrackingNotice(snapshot, 'PX4 reboot complete')),
        onTrackingUnavailable: (snapshot) => setSingleNotice(buildTrackingNotice(snapshot, 'PX4 reboot status unavailable')),
      });
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to dispatch PX4 reboot.');
      setSingleNotice(buildNotice(
        'danger',
        'PX4 reboot failed',
        error?.response?.data?.detail || 'The reboot command could not be dispatched.',
      ));
    } finally {
      setRebootingPx4(false);
    }
  };

  const rows = filteredRows.map((row) => ({
    id: row.name,
    ...row,
    value: formatParameterValue(row.value, row),
    default_display: formatParameterValue(row.default_value, row),
    range: formatParameterRange(row),
    modified: row.default_value !== null && row.default_value !== undefined && row.default_value !== row.value ? 'Yes' : '',
    session: sessionChangedNames.has(row.name) ? 'Edited' : '',
    reboot: row.reboot_required ? 'Reboot' : '',
    summary: row.short_description || row.long_description || '',
    group: row.group || '',
    category: row.category || '',
  }));

  const columns = [
    { field: 'name', headerName: 'Name', minWidth: 170, flex: 0.95, headerAlign: 'left', align: 'left' },
    { field: 'value', headerName: 'Current', minWidth: 120, flex: 0.7, headerAlign: 'right', align: 'right' },
    { field: 'value_type', headerName: 'Type', minWidth: 90, flex: 0.45, headerAlign: 'left', align: 'left' },
    { field: 'unit', headerName: 'Unit', minWidth: 80, flex: 0.4, headerAlign: 'left', align: 'left' },
    { field: 'group', headerName: 'Group', minWidth: 170, flex: 1.05, headerAlign: 'left', align: 'left' },
    { field: 'reboot', headerName: 'Restart', minWidth: 100, flex: 0.5, headerAlign: 'center', align: 'center' },
  ];

  return (
    <div className="px4-parameters-page">
      <header className="px4-parameters-page__header">
        <div>
          <span className="px4-parameters-page__eyebrow">Vehicle Tuning</span>
          <h1>PX4 Parameters</h1>
          <p>
            Inspect live PX4 values, review approved fleet profiles, and apply verified changes through the GCS.
          </p>
        </div>
        <div className="px4-parameters-page__policy">
          <span>{policy?.docs?.version ? `Docs ${policy.docs.version}` : 'Docs loading'}</span>
          <span>{policy?.mutations?.require_disarmed ? 'Writes require disarm' : 'Writes allowed when linked'}</span>
          <span>{profileSummaries.length} repo profile{profileSummaries.length === 1 ? '' : 's'}</span>
        </div>
      </header>

      <div className="px4-parameters-page__mode-toggle" role="tablist" aria-label="PX4 parameter workspace mode">
        <button
          type="button"
          className={workspaceMode === 'single' ? 'active' : ''}
          onClick={() => setWorkspaceMode('single')}
        >
          Single Drone
        </button>
        <button
          type="button"
          className={workspaceMode === 'batch' ? 'active' : ''}
          onClick={() => setWorkspaceMode('batch')}
        >
          Batch
        </button>
        <button
          type="button"
          className={workspaceMode === 'profiles' ? 'active' : ''}
          onClick={() => setWorkspaceMode('profiles')}
        >
          Profiles
        </button>
      </div>

      {workspaceMode === 'single' ? (
      <section className="px4-parameters-page__workspace">
        <aside className="px4-parameters-page__sidebar">
          <div className="px4-panel">
            <div className="px4-panel__header">
              <h2>Target Drone</h2>
              <span>{filteredDrones.length} visible</span>
            </div>
            <input
              className="px4-page-input"
              value={droneQuery}
              onChange={(event) => setDroneQuery(event.target.value)}
              placeholder={DRONE_SEARCH_PLACEHOLDER}
              aria-label="Search drones"
            />
            <p className="px4-panel__hint">{DRONE_SEARCH_HELP_TEXT}</p>
            {selectedHiddenByFilter ? (
              <div className="px4-inline-notice">
                Current target {selectedIdentity?.primary} is hidden by the active drone filter.
              </div>
            ) : null}
            <label className="px4-param-inspector__field">
              <span>Filtered target</span>
              <select
                className="px4-page-input"
                value={selectedHwId}
                onChange={(event) => setSelectedHwId(event.target.value)}
                aria-label="Filtered target drone"
              >
                {filteredDrones.map((drone) => {
                  const identity = getDroneDisplayIdentity(drone);
                  return (
                    <option key={drone.hw_id} value={String(drone.hw_id)}>
                      {identity.primary} · {drone.online ? 'Online' : 'Offline'}
                    </option>
                  );
                })}
              </select>
            </label>
            {selectedIdentity ? (
              <div className="px4-target-summary">
                <div>
                  <strong>{selectedIdentity.primary}</strong>
                  <span>{selectedIdentity.secondary}</span>
                </div>
                <span className={`px4-drone-option__status ${selectedDrone?.online ? 'online' : 'offline'}`}>
                  {selectedDrone?.online ? 'Online' : 'Offline'}
                </span>
              </div>
            ) : null}
            {!isCompactViewport ? (
              <div className="px4-parameters-page__drone-list">
                {filteredDrones.map((drone) => {
                  const identity = getDroneDisplayIdentity(drone);
                  const active = String(drone.hw_id) === String(selectedHwId);
                  return (
                    <button
                      key={drone.hw_id}
                      type="button"
                      className={`px4-drone-option ${active ? 'active' : ''}`}
                      onClick={() => setSelectedHwId(String(drone.hw_id))}
                    >
                      <div>
                        <strong>{identity.primary}</strong>
                        <span>{identity.secondary}</span>
                      </div>
                      <span className={`px4-drone-option__status ${drone.online ? 'online' : 'offline'}`}>
                        {drone.online ? 'Online' : 'Offline'}
                      </span>
                    </button>
                  );
                })}
              </div>
            ) : null}
          </div>

          <div className="px4-panel">
            <div className="px4-panel__header">
              <h2>Snapshot</h2>
              <span>{snapshotResponse?.snapshot?.total_params || 0} rows</span>
            </div>
            <div className="px4-parameters-page__snapshot-meta">
              <div>
                <span>Scope</span>
                <strong>{selectedIdentity?.primary || 'No drone selected'}</strong>
              </div>
              <div>
                <span>Last fetched snapshot</span>
                <strong>{formatRelativeSnapshotAge(snapshotResponse?.snapshot)}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>{snapshotStatusLabel}</strong>
              </div>
              <div>
                <span>Metadata</span>
                <strong aria-label={metadataWarning || 'PX4 metadata source quality'}>
                  {metadataQualityLabel}
                </strong>
              </div>
              <div>
                <span>Default delta</span>
                <strong>{modifiedRowCount}</strong>
              </div>
              <div>
                <span>Reboot flagged</span>
                <strong>{rebootFlaggedCount}</strong>
              </div>
            </div>
            <div className="px4-parameters-page__snapshot-actions">
              <button type="button" className="primary" onClick={refreshSnapshot} disabled={!selectedHwId || snapshotLoading}>
                {snapshotLoading ? 'Refreshing…' : 'Refresh Snapshot'}
              </button>
              <button type="button" onClick={handleExportQgc} disabled={!snapshotResponse}>
                Export QGC File
              </button>
              <button type="button" onClick={handleChooseImportFile} disabled={!snapshotResponse || importing}>
                {importing ? 'Importing…' : 'Import QGC File'}
              </button>
              <button type="button" onClick={() => setWorkspaceMode('profiles')} disabled={!profileSummaries.length}>
                Review Profiles
              </button>
              <button type="button" onClick={handleRebootPx4} disabled={rebootingPx4 || Boolean(rebootBlockedReason)}>
                {rebootingPx4 ? 'Rebooting…' : 'Reboot PX4'}
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".params,.txt,.tsv,.csv"
                className="px4-hidden-input"
                onChange={handleImportFile}
              />
            </div>
            <StatusNotice notice={singleNotice} />
            {metadataWarning ? (
              <div className="px4-inline-notice px4-inline-notice--warning">
                <strong>PX4 metadata limited</strong>
                <span>{metadataWarningSummary}</span>
                <details className="px4-metadata-details">
                  <summary>Why?</summary>
                  <span>{metadataWarning}</span>
                </details>
              </div>
            ) : null}
            {rebootBlockedReason && !rebootingPx4 ? (
              <div className="px4-inline-notice">
                <strong>Reboot safety</strong>
                <span>{rebootBlockedReason}</span>
              </div>
            ) : null}

            {importPreview ? (
              <div className="px4-import-preview">
                <div className="px4-import-preview__header">
                  <div>
                    <strong>{importPreview.fileName}</strong>
                    <span>{importPreview.diffResponse.total_changed} changed row(s) pending review</span>
                  </div>
                  <button type="button" onClick={() => setImportPreview(null)}>
                    Clear
                  </button>
                </div>
                <div className="px4-import-preview__list">
                  {importPreview.diffResponse.differences.slice(0, 6).map((difference) => (
                    <div key={`${difference.component_id}:${difference.name}`} className="px4-import-preview__row">
                      <strong>{difference.name}</strong>
                      <span>{String(difference.current_value ?? '—')} → {String(difference.desired_value ?? '—')}</span>
                    </div>
                  ))}
                </div>
                <div className="px4-import-preview__actions">
                  <button type="button" className="primary" onClick={handleApplyImportedChanges} disabled={saving || Boolean(writeBlockedReason)}>
                    Apply Imported Changes
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        </aside>

        <section className="px4-parameters-page__main">
            <div className="px4-panel px4-panel--toolbar">
              <div className="px4-panel__header">
                <h2>Parameter Table</h2>
                <span>{rows.length} rows shown</span>
              </div>
              <div className="px4-inline-notice">
                <strong>{isCompactViewport ? 'Tap a parameter' : 'Select a row'}</strong>
                <span>
                  Keep the list for scanning. Search flattens matching rows; otherwise compact screens stay grouped by PX4 section.
                </span>
              </div>
              {selectedRow ? (
                <div className="px4-selection-banner">
                  Editing {selectedIdentity?.primary || 'target'} → {selectedRow.name}
              </div>
            ) : null}
            <div className="px4-parameters-page__toolbar">
              <input
                className="px4-page-input"
                value={paramQuery}
                onChange={(event) => setParamQuery(event.target.value)}
                placeholder="Search name or description"
                aria-label="Search parameters"
              />
              <label className="px4-toggle">
                <input
                  type="checkbox"
                  checked={showModifiedOnly}
                  onChange={(event) => setShowModifiedOnly(event.target.checked)}
                />
                <span>Modified only</span>
              </label>
              <label className="px4-toggle">
                <input
                  type="checkbox"
                  checked={showSessionChangesOnly}
                  onChange={(event) => setShowSessionChangesOnly(event.target.checked)}
                />
                <span>Session edits</span>
              </label>
              <label className="px4-toggle">
                <input
                  type="checkbox"
                  checked={showRebootOnly}
                  onChange={(event) => setShowRebootOnly(event.target.checked)}
                />
                <span>Reboot flagged</span>
              </label>
            </div>
          </div>

          <div className="px4-parameters-page__content">
            <div className="px4-panel px4-panel--table">
              {snapshotLoading ? (
                <div className="px4-table-loading" role="status" aria-live="polite">
                  <span className="px4-table-loading__dot" aria-hidden="true" />
                  <span>Loading latest snapshot…</span>
                </div>
              ) : null}
              {isCompactViewport ? (
                <CompactParameterList
                  rows={rows}
                  selectedParamName={selectedParamName}
                  onSelect={handleSelectParameter}
                  grouped={compactGroupingEnabled}
                  expandedGroup={expandedCompactGroup}
                  onToggleGroup={(groupLabel) => setExpandedCompactGroup((current) => (current === groupLabel ? '' : groupLabel))}
                />
              ) : (
                <DataGrid
                  rows={rows}
                  columns={columns}
                  loading={snapshotLoading}
                  density="compact"
                  rowHeight={36}
                  columnHeaderHeight={38}
                  disableColumnMenu
                  disableRowSelectionOnClick
                  rowSelectionModel={selectedParamName ? [selectedParamName] : []}
                  getRowClassName={(params) => (params.indexRelativeToCurrentPage % 2 === 0 ? 'px4-grid-row-even' : 'px4-grid-row-odd')}
                  onRowClick={(params) => handleSelectParameter(params.row.name)}
                  pageSizeOptions={[25, 50, 100]}
                  initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
                  sx={{
                    border: 'none',
                    '& .MuiDataGrid-cell': {
                      color: 'var(--color-text-primary)',
                    },
                    '& .MuiDataGrid-columnHeader': {
                      color: 'var(--color-text-secondary)',
                      backgroundColor: 'var(--color-bg-tertiary)',
                    },
                    '& .MuiDataGrid-row.px4-grid-row-odd': {
                      backgroundColor: 'color-mix(in srgb, var(--color-bg-tertiary) 58%, transparent)',
                    },
                    '& .MuiDataGrid-row:hover': {
                      backgroundColor: 'color-mix(in srgb, var(--color-primary-light) 45%, var(--color-bg-secondary))',
                    },
                    '& .MuiDataGrid-footerContainer': {
                      color: 'var(--color-text-secondary)',
                      borderTopColor: 'var(--color-border-primary)',
                    },
                    '& .MuiDataGrid-row.Mui-selected': {
                      backgroundColor: 'var(--color-primary-light)',
                    },
                  }}
                />
              )}
            </div>
          </div>
        </section>
      </section>
      ) : workspaceMode === 'batch' ? (
        <section className="px4-parameters-page__workspace">
          <aside className="px4-parameters-page__sidebar">
            <div className="px4-panel">
              <div className="px4-panel__header">
                <h2>Batch Scope</h2>
                <span>{batchTargetLabel}</span>
              </div>
              <div className="px4-parameters-page__scope-toggle">
                <button type="button" className={batchTargetMode === '' ? 'active' : ''} onClick={() => setBatchTargetMode('')}>None</button>
                <button type="button" className={batchTargetMode === 'all' ? 'active' : ''} onClick={() => setBatchTargetMode('all')}>All</button>
                <button type="button" className={batchTargetMode === 'cluster' ? 'active' : ''} onClick={() => setBatchTargetMode('cluster')}>Cluster</button>
                <button type="button" className={batchTargetMode === 'selected' ? 'active' : ''} onClick={() => setBatchTargetMode('selected')}>Selected</button>
              </div>
              {batchTargetMode === 'cluster' ? (
                <ClusterScopeBar
                  label="Cluster Scope"
                  options={batchClusterOptions}
                  selectedId={batchClusterScope}
                  onSelect={setBatchClusterScope}
                  summary="Uses the current saved Smart Swarm topology."
                />
              ) : null}
              {batchTargetMode === 'selected' ? (
                <>
                  <input
                    className="px4-page-input"
                    value={droneQuery}
                    onChange={(event) => setDroneQuery(event.target.value)}
                    placeholder={DRONE_SEARCH_PLACEHOLDER}
                    aria-label="Search drones"
                  />
                  <p className="px4-panel__hint">{DRONE_SEARCH_HELP_TEXT}</p>
                  <div className="px4-parameters-page__drone-list">
                    {filteredDrones.map((drone) => {
                      const identity = getDroneDisplayIdentity(drone);
                      const selected = batchSelectedDrones.includes(String(drone.hw_id));
                      return (
                        <button
                          key={drone.hw_id}
                          type="button"
                          className={`px4-drone-option ${selected ? 'active' : ''}`}
                          onClick={() => handleBatchTargetToggle(drone.hw_id)}
                        >
                          <div>
                            <strong>{identity.primary}</strong>
                            <span>{identity.secondary}</span>
                          </div>
                          <span className={`px4-drone-option__status ${drone.online ? 'online' : 'offline'}`}>
                            {selected ? 'Selected' : (drone.online ? 'Online' : 'Offline')}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </>
              ) : null}
            </div>
          </aside>

          <section className="px4-parameters-page__main">
            <div className="px4-panel">
              <div className="px4-panel__header">
                <h2>Batch Patch Composer</h2>
                <span>{batchTargetHwIds.length} targets</span>
              </div>
              <div className="px4-parameters-page__scope-toggle px4-parameters-page__composer-toggle">
                <button
                  type="button"
                  className={batchComposerMode === 'profile' ? 'active' : ''}
                  onClick={() => setBatchComposerMode('profile')}
                >
                  Saved Profile
                </button>
                <button
                  type="button"
                  className={batchComposerMode === 'manual' ? 'active' : ''}
                  onClick={() => setBatchComposerMode('manual')}
                >
                  Advanced Manual Entry
                </button>
              </div>
              {batchComposerMode === 'profile' ? (
                <div className="px4-profile-apply">
                  <label className="px4-param-inspector__field">
                    <span>Profile</span>
                    <select
                      className="px4-page-input"
                      value={selectedProfileId}
                      onChange={(event) => setSelectedProfileId(event.target.value)}
                      aria-label="Saved PX4 profile"
                    >
                      {profileSummaries.map((profile) => (
                        <option key={profile.profile_id} value={profile.profile_id}>
                          {profile.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  {selectedProfile ? (
                    <>
                  <div className="px4-profile-apply__summary">
                    <strong>{selectedProfile.name}</strong>
                    <span>{selectedProfile.entries.length} row(s) · Recommended {selectedProfile.recommended_scope}</span>
                  </div>
                  <div className="px4-inline-notice">
                    <strong>Profile library</strong>
                    <span>Profiles are repo-managed under <code>resources/px4_param_profiles/</code>. Review and apply here; add or edit them through the repo workflow.</span>
                  </div>
                  <div className="px4-import-preview__list">
                        {selectedProfile.entries.slice(0, 6).map((entry) => (
                          <div key={`${entry.component_id}:${entry.name}`} className="px4-import-preview__row">
                            <strong>{entry.name}</strong>
                            <span>{String(entry.value)}</span>
                          </div>
                        ))}
                      </div>
                    </>
                  ) : (
                    <div className="px4-inline-notice">Select a saved profile to review and apply it to the chosen scope.</div>
                  )}
                </div>
              ) : (
                <>
                  <div className="px4-batch-form">
                    <label className="px4-param-inspector__field">
                      <span>Parameter Name</span>
                      <input
                        type="text"
                        value={batchParamName}
                        onChange={(event) => setBatchParamName(event.target.value.toUpperCase())}
                        placeholder="e.g. MPC_XY_VEL_MAX"
                        aria-label="Batch parameter name"
                      />
                    </label>
                    <label className="px4-param-inspector__field">
                      <span>Value Type</span>
                      <select
                        className="px4-page-input"
                        value={batchValueType}
                        onChange={(event) => setBatchValueType(event.target.value)}
                        aria-label="Batch parameter type"
                      >
                        <option value="int">INT</option>
                        <option value="float">FLOAT</option>
                        <option value="custom">CUSTOM</option>
                      </select>
                    </label>
                    <label className="px4-param-inspector__field">
                      <span>Value</span>
                      <input
                        type={batchValueType === 'custom' ? 'text' : 'number'}
                        step={batchValueType === 'int' ? '1' : 'any'}
                        value={batchDraftValue}
                        onChange={(event) => setBatchDraftValue(event.target.value)}
                        aria-label="Batch parameter value"
                      />
                    </label>
                  </div>
                  <div className="px4-inline-notice">
                    Use manual batch entry only for one-off overrides. Saved profiles remain the clean source of truth for repeatable fleet baselines.
                  </div>
                </>
              )}
              <StatusNotice notice={batchNotice} />
              {batchTargetWarning ? (
                <div className="px4-inline-notice px4-inline-notice--warning">
                  <strong>Batch scope warning</strong>
                  <span>{batchTargetWarning}</span>
                </div>
              ) : null}
              {offlineBatchTargets.length > 0 ? (
                <label className="px4-toggle px4-toggle--checkbox">
                  <input
                    type="checkbox"
                    checked={allowOfflineSkip}
                    onChange={(event) => setAllowOfflineSkip(event.target.checked)}
                  />
                  <span>Apply to online drones only and skip {offlineBatchTargets.length} offline target{offlineBatchTargets.length === 1 ? '' : 's'}</span>
                </label>
              ) : null}
              {batchWriteBlockedReason ? (
                <div className="px4-param-inspector__notice px4-param-inspector__notice--warning">
                  {batchWriteBlockedReason}
                </div>
              ) : null}
              <div className="px4-param-inspector__actions">
                <button
                  type="button"
                  className="primary"
                  onClick={batchComposerMode === 'profile' ? handleApplyBatchProfile : handleApplyBatchPatch}
                  disabled={batchApplying || Boolean(batchWriteBlockedReason) || (batchComposerMode === 'profile' && !selectedProfile)}
                >
                  {batchApplying
                    ? 'Applying…'
                    : batchComposerMode === 'profile'
                      ? 'Apply Saved Profile'
                      : 'Apply Manual Patch'}
                </button>
                <button type="button" onClick={() => setWorkspaceMode('profiles')} disabled={!profileSummaries.length}>
                  Open Profile Library
                </button>
              </div>
            </div>

            {batchJobResult ? (
              <div className="px4-panel">
                <div className="px4-panel__header">
                  <h2>Last Batch Result</h2>
                  <span>{batchResultSummary.applied}/{batchResultSummary.total} applied</span>
                </div>
                <div className="px4-inline-notice">
                  <strong>Result summary</strong>
                  <span>{batchResultSummary.verified}/{batchResultSummary.total} verified, {batchResultSummary.failed} failed.</span>
                </div>
                <div className="px4-import-preview__list">
                  {(batchJobResult.results || []).map((result) => (
                    <div key={result.hw_id} className="px4-import-preview__row">
                      <strong>Drone {result.hw_id}</strong>
                      <span>{result.error || (result.verified ? 'Applied + verified' : result.applied ? 'Applied' : 'Failed')}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        </section>
      ) : (
        <section className="px4-parameters-page__workspace">
          <aside className="px4-parameters-page__sidebar">
            <div className="px4-panel">
              <div className="px4-panel__header">
                <h2>Repo Profiles</h2>
                <span>{profileSummaries.length} available</span>
              </div>
              {profilesLoading ? (
                <div className="px4-profile-panel__empty">Loading profiles…</div>
              ) : (
                <div className="px4-parameters-page__drone-list">
                  {profileSummaries.map((profile) => (
                    <button
                      key={profile.profile_id}
                      type="button"
                      className={`px4-drone-option ${selectedProfileId === profile.profile_id ? 'active' : ''}`}
                      onClick={() => setSelectedProfileId(profile.profile_id)}
                    >
                      <div>
                        <strong>{profile.name}</strong>
                        <span>{profile.description || `${profile.entry_count} row(s)`}</span>
                      </div>
                      <span className="px4-drone-option__status online">
                        {profile.entry_count} rows
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="px4-panel">
              <div className="px4-panel__header">
                <h2>Compare Target</h2>
                <span>{selectedIdentity?.primary || 'No drone'}</span>
              </div>
              <div className="px4-parameters-page__snapshot-meta">
                <div>
                  <span>Scope</span>
                  <strong>{selectedIdentity?.primary || 'Select in Single Drone mode'}</strong>
                </div>
                <div>
                  <span>Snapshot</span>
                  <strong>{formatRelativeSnapshotAge(snapshotResponse?.snapshot)}</strong>
                </div>
                <div>
                  <span>Status</span>
                  <strong>{snapshotStatusLabel}</strong>
                </div>
                <div>
                  <span>Metadata</span>
                  <strong aria-label={metadataWarning || 'PX4 metadata source quality'}>
                    {metadataQualityLabel}
                  </strong>
                </div>
              </div>
              <div className="px4-param-inspector__actions">
                <button type="button" className="primary" onClick={refreshSnapshot} disabled={!selectedHwId || snapshotLoading}>
                  {snapshotLoading ? 'Refreshing…' : 'Refresh Snapshot'}
                </button>
                <button type="button" onClick={() => setWorkspaceMode('single')}>
                  Open Single Drone
                </button>
              </div>
              <StatusNotice notice={profileNotice} />
            </div>
          </aside>

          <section className="px4-parameters-page__main">
            <div className="px4-inline-notice">
              <strong>Repo-managed profiles</strong>
              <span>Use the browser to review, diff, and apply profiles. Add or revise them in <code>resources/px4_param_profiles/</code> so the approved library stays reviewable.</span>
            </div>
            <Px4ParamProfilePanel
              profile={selectedProfile}
              loading={profileLoading}
              compareTargetLabel={compareTargetLabel}
              compareResult={profileDiffPreview}
              compareLoading={profileDiffLoading}
              onPreviewDiff={handlePreviewProfileDiff}
              onUseInBatch={() => {
                setBatchComposerMode('profile');
                setWorkspaceMode('batch');
              }}
              onExportProfile={handleExportProfile}
            />
          </section>
        </section>
      )}

      {selectedRow && inspectorOpen ? (
        <div
          className="px4-inspector-dialog-backdrop"
          onClick={() => setInspectorOpen(false)}
        >
          <div
            className="px4-inspector-dialog"
            role="dialog"
            aria-modal="true"
            aria-label={selectedRow ? `${selectedRow.name} parameter details` : 'Parameter details'}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="px4-inspector-dialog__header">
              <div>
                <strong>{selectedRow?.name || 'Parameter details'}</strong>
                <span>{selectedIdentity?.primary || 'Selected drone'}</span>
              </div>
              <button type="button" onClick={() => setInspectorOpen(false)}>
                Close
              </button>
            </div>
            <Px4ParamInspector
              row={selectedRow}
              draftValue={draftValue}
              onDraftValueChange={setDraftValue}
              onResetToCurrent={() => setDraftValue(selectedRow ? String(selectedRow.value ?? '') : '')}
              onResetToDefault={() => setDraftValue(selectedRow && selectedRow.default_value !== null && selectedRow.default_value !== undefined ? String(selectedRow.default_value) : '')}
              onSave={handleSave}
              saving={saving}
              writeBlockedReason={writeBlockedReason}
            />
          </div>
        </div>
      ) : null}
    </div>
  );
};

export default Px4ParametersPage;
