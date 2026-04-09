import React, { useDeferredValue, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid } from '@mui/x-data-grid';
import { toast } from 'react-toastify';
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
  refreshPx4ParamSnapshots,
} from '../services/px4ParamsApiService';
import { buildQgcParameterFile } from '../utilities/px4ParameterFiles';
import { getDroneDisplayIdentity, matchesDroneSearchQuery } from '../utilities/dronePresentation';
import { normalizeTelemetryResponse, FIELD_NAMES } from '../constants/fieldMappings';
import ClusterScopeBar from '../components/ClusterScopeBar';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  filterClustersByScope,
} from '../utilities/swarmDesignUtils';
import Px4ParamInspector from '../components/px4/Px4ParamInspector';
import '../styles/Px4ParametersPage.css';

const SNAPSHOT_REFRESH_INTERVAL_MS = 15000;

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

function deriveWriteBlockedReason(policy, selectedDrone) {
  if (!selectedDrone) {
    return 'Select a target drone first.';
  }

  if (policy?.mutations?.require_disarmed && selectedDrone[FIELD_NAMES.IS_ARMED]) {
    return 'PX4 parameter writes are blocked while the target drone is armed.';
  }

  return '';
}

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
  const [batchTargetMode, setBatchTargetMode] = useState('all');
  const [batchSelectedDrones, setBatchSelectedDrones] = useState([]);
  const [batchClusterScope, setBatchClusterScope] = useState('');
  const [batchParamName, setBatchParamName] = useState('');
  const [batchValueType, setBatchValueType] = useState('float');
  const [batchDraftValue, setBatchDraftValue] = useState('');
  const [batchApplying, setBatchApplying] = useState(false);
  const [batchJobResult, setBatchJobResult] = useState(null);
  const fileInputRef = useRef(null);

  const deferredDroneQuery = useDeferredValue(droneQuery);
  const deferredParamQuery = useDeferredValue(paramQuery);

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
    if (!selectedHwId || !filteredDrones.some((drone) => String(drone.hw_id) === String(selectedHwId))) {
      setSelectedHwId(String(filteredDrones[0].hw_id));
    }
  }, [filteredDrones, selectedHwId]);

  useEffect(() => {
    if (!batchClusterOptions.length) {
      if (batchTargetMode === 'cluster') {
        setBatchTargetMode('all');
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
        return;
      }

      if (snapshot) {
        setSnapshotResponse(snapshot);
        setSelectedParamName((currentName) => {
          if (!currentName) {
            return snapshot.rows[0]?.name || '';
          }
          return snapshot.rows.some((row) => row.name === currentName)
            ? currentName
            : (snapshot.rows[0]?.name || '');
        });
      }
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to refresh PX4 parameter snapshot.');
    } finally {
      setSnapshotLoading(false);
    }
  }, [policy?.mutations?.supported_component_ids, selectedHwId]);

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

  const writeBlockedReason = deriveWriteBlockedReason(policy, selectedDrone);
  const batchTargetHwIds = useMemo(() => {
    if (batchTargetMode === 'selected') {
      return batchSelectedDrones.map((value) => String(value));
    }
    if (batchTargetMode === 'cluster') {
      return batchClusterTargetIds;
    }
    return mergedDrones.map((drone) => String(drone.hw_id));
  }, [batchClusterTargetIds, batchSelectedDrones, batchTargetMode, mergedDrones]);
  const batchTargetLabel = batchTargetMode === 'selected'
    ? `${batchSelectedDrones.length} selected drone${batchSelectedDrones.length === 1 ? '' : 's'}`
    : batchTargetMode === 'cluster'
      ? `${batchClusterOptions.find((option) => String(option.id) === String(batchClusterScope))?.label || 'Cluster'} · ${batchClusterTargetIds.length} drones`
      : `All ${mergedDrones.length} drones`;
  const batchWriteBlockedReason = useMemo(() => {
    if (batchTargetHwIds.length === 0) {
      return 'Choose at least one target drone.';
    }
    if (!policy?.mutations?.require_disarmed) {
      return '';
    }
    const armedTargets = mergedDrones.filter((drone) => batchTargetHwIds.includes(String(drone.hw_id)) && drone[FIELD_NAMES.IS_ARMED]);
    if (armedTargets.length > 0) {
      return `${armedTargets.length} target drone${armedTargets.length === 1 ? '' : 's'} are armed. Batch writes are blocked.`;
    }
    return '';
  }, [batchTargetHwIds, mergedDrones, policy?.mutations?.require_disarmed]);

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
      } else {
        toast.warn(`${selectedRow.name} was written, but verification did not fully confirm the readback.`);
      }

      setSessionChangedNames((current) => {
        const next = new Set(current);
        next.add(selectedRow.name);
        return next;
      });
      await refreshSnapshot();
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply PX4 parameter patch job.');
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
      } else {
        toast.success(`Imported ${importResponse.data.total_entries} parameter row(s) for review.`);
      }
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to import and compare the QGC parameter file.');
    } finally {
      setImporting(false);
    }
  };

  const handleApplyImportedChanges = async () => {
    if (!selectedDrone || !importPreview?.importResponse?.entries?.length) {
      return;
    }

    setSaving(true);
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
      setSessionChangedNames((current) => {
        const next = new Set(current);
        importPreview.importResponse.entries.forEach((entry) => next.add(entry.name));
        return next;
      });
      setImportPreview(null);
      await refreshSnapshot();
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply imported PX4 parameter patch.');
    } finally {
      setSaving(false);
    }
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
    if (!batchTargetHwIds.length) {
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
    try {
      const response = await createPx4ParamPatchJob({
        hwIds: batchTargetHwIds,
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
      toast.success(`Batch patch dispatched to ${batchTargetHwIds.length} drone(s).`);
    } catch (error) {
      toast.error(error?.response?.data?.detail || 'Failed to apply the PX4 batch patch.');
    } finally {
      setBatchApplying(false);
    }
  };

  const rows = filteredRows.map((row) => ({
    id: row.name,
    ...row,
    range: [row.min_value, row.max_value].every((value) => value !== null && value !== undefined)
      ? `${row.min_value} – ${row.max_value}`
      : '—',
    modified: row.default_value !== null && row.default_value !== undefined && row.default_value !== row.value ? 'Yes' : '',
    session: sessionChangedNames.has(row.name) ? 'Edited' : '',
    reboot: row.reboot_required ? 'Reboot' : '',
    summary: row.short_description || row.long_description || '',
  }));

  const columns = [
    { field: 'name', headerName: 'Name', minWidth: 150, flex: 0.9 },
    { field: 'value', headerName: 'Value', minWidth: 120, flex: 0.9 },
    { field: 'value_type', headerName: 'Type', minWidth: 90, flex: 0.5 },
    { field: 'unit', headerName: 'Unit', minWidth: 90, flex: 0.5 },
    { field: 'range', headerName: 'Range', minWidth: 140, flex: 0.8 },
    { field: 'modified', headerName: 'Default Δ', minWidth: 100, flex: 0.55 },
    { field: 'session', headerName: 'Session', minWidth: 90, flex: 0.55 },
    { field: 'reboot', headerName: 'Reboot', minWidth: 90, flex: 0.55 },
    { field: 'summary', headerName: 'Summary', minWidth: 220, flex: 1.4 },
  ];

  return (
    <div className="px4-parameters-page">
      <header className="px4-parameters-page__header">
        <div>
          <span className="px4-parameters-page__eyebrow">Vehicle Tuning</span>
          <h1>PX4 Parameters</h1>
          <p>
            Refresh one aircraft snapshot, inspect live PX4 values, and apply verified parameter edits through the GCS.
          </p>
        </div>
        <div className="px4-parameters-page__policy">
          <span>{policy?.docs?.version ? `Docs ${policy.docs.version}` : 'Docs loading'}</span>
          <span>{policy?.mutations?.require_disarmed ? 'Writes require disarm' : 'Writes allowed when linked'}</span>
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
              placeholder="Search, P1|H1, pos 1-5, or hw 2,4"
              aria-label="Search drones"
            />
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
                <span>Freshness</span>
                <strong>{formatRelativeSnapshotAge(snapshotResponse?.snapshot)}</strong>
              </div>
              <div>
                <span>Status</span>
                <strong>
                  {selectedDrone?.online
                    ? (writeBlockedReason ? 'Read only' : 'Writable')
                    : (writeBlockedReason ? 'Read only' : 'Telemetry delayed')}
                </strong>
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
              <input
                ref={fileInputRef}
                type="file"
                accept=".params,.txt,.tsv,.csv"
                className="px4-hidden-input"
                onChange={handleImportFile}
              />
            </div>

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
              <DataGrid
                rows={rows}
                columns={columns}
                density="compact"
                rowHeight={32}
                columnHeaderHeight={38}
                disableColumnMenu
                disableRowSelectionOnClick
                onRowClick={(params) => setSelectedParamName(params.row.name)}
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
                  '& .MuiDataGrid-footerContainer': {
                    color: 'var(--color-text-secondary)',
                    borderTopColor: 'var(--color-border-primary)',
                  },
                  '& .MuiDataGrid-row.Mui-selected': {
                    backgroundColor: 'var(--color-primary-light)',
                  },
                }}
              />
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
        </section>
      </section>
      ) : (
        <section className="px4-parameters-page__workspace">
          <aside className="px4-parameters-page__sidebar">
            <div className="px4-panel">
              <div className="px4-panel__header">
                <h2>Batch Scope</h2>
                <span>{batchTargetLabel}</span>
              </div>
              <div className="px4-parameters-page__scope-toggle">
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
                    placeholder="Search, P1|H1, pos 1-5, or hw 2,4"
                    aria-label="Search drones"
                  />
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
              {batchWriteBlockedReason ? (
                <div className="px4-param-inspector__notice px4-param-inspector__notice--warning">
                  {batchWriteBlockedReason}
                </div>
              ) : null}
              <div className="px4-param-inspector__actions">
                <button
                  type="button"
                  className="primary"
                  onClick={handleApplyBatchPatch}
                  disabled={batchApplying || Boolean(batchWriteBlockedReason)}
                >
                  {batchApplying ? 'Applying…' : 'Apply Batch Patch'}
                </button>
              </div>
            </div>

            {batchJobResult ? (
              <div className="px4-panel">
                <div className="px4-panel__header">
                  <h2>Last Batch Result</h2>
                  <span>{batchJobResult.status}</span>
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
      )}
    </div>
  );
};

export default Px4ParametersPage;
