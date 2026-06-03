import React, { useEffect, useMemo, useRef, useState } from 'react';
import Papa from 'papaparse';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  FaCloudUploadAlt,
  FaDownload,
  FaExclamationTriangle,
  FaLayerGroup,
  FaProjectDiagram,
  FaSave,
  FaSearch,
  FaSyncAlt,
  FaUndo,
  FaUpload,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import DroneCard from '../components/DroneCard';
import DroneGraph from '../components/DroneGraph';
import SwarmPlots from '../components/SwarmPlots';
import SwarmRuntimeControls from '../components/SwarmRuntimeControls';
import ClusterScopeBar from '../components/ClusterScopeBar';
import IdentityDoctrineStrip from '../components/IdentityDoctrineStrip';
import {
  ActionIconButton,
  ConfirmDialog,
  EmptyState,
  MetricStrip,
  OperatorNotice,
  PageActionBar,
  PageShell,
  StatusBadge,
} from '../components/ui/OperatorPrimitives';
import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';
import '../styles/SwarmDesign.css';
import {
  GCS_ROUTE_KEYS,
  getFleetConfigResponse,
  getSwarmConfigResponse,
  getUnifiedGitStatusResponse,
  saveSwarmConfigResponse,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  buildWorkingSwarmAssignments,
  filterClustersByScope,
  getDirtyAssignmentIds,
  normalizeConfigDrone,
  normalizeSwarmAssignment,
  toSwarmApiPayload,
} from '../utilities/swarmDesignUtils';
import { formatDroneLabel } from '../utilities/missionIdentityUtils';
import {
  DRONE_SEARCH_HELP_TEXT,
  DRONE_SEARCH_PLACEHOLDER,
  matchesDroneSearchQuery,
} from '../utilities/dronePresentation';

const CSV_HEADERS = ['hw_id', 'follow', 'offset_x', 'offset_y', 'offset_z', 'frame'];

function hasIncompleteNumericValue(value) {
  if (typeof value !== 'string') {
    return false;
  }

  return ['', '-', '.', '-.'].includes(value.trim());
}

function extractGcsUncommittedChanges(gitStatus) {
  const changes = gitStatus?.gcs_status?.uncommitted_changes;
  return Array.isArray(changes) ? changes.map((change) => String(change)) : [];
}

function isSwarmJsonChange(change) {
  return String(change || '').trim().split(/\s+/).includes('swarm.json')
    || String(change || '').includes('/swarm.json');
}

function buildGitResultMessage(gitResult) {
  if (!gitResult || typeof gitResult !== 'object') {
    return 'No git write-back report was returned by the GCS.';
  }

  const parts = [];
  if (gitResult.message) {
    parts.push(gitResult.message);
  }
  if (gitResult.commit_hash) {
    parts.push(`commit ${gitResult.commit_hash}`);
  }
  if (gitResult.pushed === true) {
    parts.push('pushed to remote');
  } else if (gitResult.auto_push_enabled === false) {
    parts.push('auto-push disabled');
  }

  return parts.length > 0 ? parts.join(' · ') : 'Git write-back finished.';
}

function getSwarmSaveGitResult(responseData) {
  return responseData?.git_result || responseData?.git_info || null;
}

function classifySwarmSaveOutcome(responseData, withCommit) {
  const gitResult = getSwarmSaveGitResult(responseData);
  const status = String(responseData?.status || 'success');

  if (!withCommit) {
    return {
      tone: 'warning',
      title: 'Draft saved',
      message: 'Draft saved on this GCS. Publish is available now.',
      stepStates: ['done', 'skipped', 'skipped'],
      gitResult,
    };
  }

  if (status === 'git_failed' || gitResult?.success === false) {
    return {
      tone: 'danger',
      title: 'Saved locally, commit failed',
      message: buildGitResultMessage(gitResult),
      stepStates: ['done', gitResult?.commit_hash ? 'done' : 'blocked', 'blocked'],
      gitResult,
    };
  }

  if (status === 'git_not_pushed' || gitResult?.pushed === false || gitResult?.auto_push_enabled === false) {
    return {
      tone: 'warning',
      title: 'Committed locally, push pending',
      message: buildGitResultMessage(gitResult),
      stepStates: ['done', 'done', 'blocked'],
      gitResult,
    };
  }

  return {
    tone: 'success',
    title: 'Published',
    message: `${buildGitResultMessage(gitResult)}. Use Fleet Ops if drones need to pull this commit.`,
    stepStates: ['done', 'done', 'done'],
    gitResult,
  };
}

function buildSwarmSaveProgress({ title, message, tone = 'info', stepStates = ['pending', 'pending', 'pending'], withCommit = true }) {
  const labels = ['Save draft', 'Commit', 'Push'];
  return {
    title,
    message,
    tone,
    steps: labels.map((label, index) => ({
      label,
      state: withCommit ? stepStates[index] : index === 0 ? stepStates[index] : 'skipped',
    })),
  };
}

function SwarmSaveProgress({ progress }) {
  if (!progress) {
    return null;
  }

  return (
    <section
      className={'swarm-save-progress is-' + (progress.tone || 'info')}
      aria-label="Smart Swarm save progress"
      aria-live="polite"
      role="status"
    >
      <div className="swarm-save-progress__copy">
        <strong>{progress.title}</strong>
        <span>{progress.message}</span>
      </div>
      <ol className="swarm-save-progress__steps">
        {(progress.steps || []).map((step) => (
          <li key={step.label} className={'is-' + (step.state || 'pending')}>
            <span aria-hidden="true" />
            <p>{step.label}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}

function SwarmDesign() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const cardRefs = useRef({});
  const handledRouteDroneRef = useRef('');

  const [configData, setConfigData] = useState([]);
  const [serverSwarmData, setServerSwarmData] = useState([]);
  const [baselineAssignments, setBaselineAssignments] = useState([]);
  const [workingAssignments, setWorkingAssignments] = useState([]);
  const [selectedDroneId, setSelectedDroneId] = useState(null);
  const [selectedClusterId, setSelectedClusterId] = useState(null);
  const [clusterScope, setClusterScope] = useState('all');
  const [expandedDroneId, setExpandedDroneId] = useState(null);
  const [pendingCardFocusId, setPendingCardFocusId] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveOperation, setSaveOperation] = useState(null);
  const [gitStatus, setGitStatus] = useState(null);
  const [gitStatusLoading, setGitStatusLoading] = useState(false);
  const [saveReport, setSaveReport] = useState(null);
  const [saveProgress, setSaveProgress] = useState(null);
  const [localSwarmCommitPending, setLocalSwarmCommitPending] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const requestedDroneId = String(searchParams.get('drone') || '').trim();
  const { data: telemetryById = {} } = useNormalizedTelemetry(GCS_ROUTE_KEYS.fleetTelemetry, 2000) || {};

  const viewModel = useMemo(
    () => buildSwarmViewModel(workingAssignments, configData),
    [configData, workingAssignments]
  );
  const dirtyIds = useMemo(
    () => getDirtyAssignmentIds(workingAssignments, baselineAssignments),
    [baselineAssignments, workingAssignments]
  );
  const dirtyIdSet = useMemo(() => new Set(dirtyIds), [dirtyIds]);
  const syncChanges = useMemo(
    () => buildWorkingSwarmAssignments(configData, serverSwarmData).syncChanges,
    [configData, serverSwarmData]
  );
  const selectedDrone = selectedDroneId ? viewModel.dronesById[selectedDroneId] : null;
  const hasPendingSync = syncChanges.addedIds.length > 0 || syncChanges.removedIds.length > 0;
  const hasStagedChanges = dirtyIds.length > 0;
  const gcsUncommittedChanges = useMemo(() => extractGcsUncommittedChanges(gitStatus), [gitStatus]);
  const hasSavedSwarmCommitPending = useMemo(
    () => gcsUncommittedChanges.some((change) => isSwarmJsonChange(change)),
    [gcsUncommittedChanges]
  );
  const hasCommitPending = hasSavedSwarmCommitPending || localSwarmCommitPending;
  const canUpdateSwarm = hasStagedChanges || hasPendingSync;
  const canCommitSwarm = canUpdateSwarm || hasCommitPending;
  const hasBlockingIssues = viewModel.summary.blockingIssueCount > 0;
  const hasIncompleteInputs = workingAssignments.some((assignment) =>
    ['offset_x', 'offset_y', 'offset_z'].some((field) => hasIncompleteNumericValue(assignment[field]))
  );
  const pendingSyncIds = useMemo(
    () => [...new Set([...syncChanges.addedIds, ...syncChanges.removedIds].map((value) => String(value)))],
    [syncChanges.addedIds, syncChanges.removedIds]
  );
  const clusterScopeOptions = useMemo(
    () => buildClusterScopeOptions(viewModel.clusters, viewModel.summary.totalDrones),
    [viewModel.clusters, viewModel.summary.totalDrones]
  );
  const scopedClusters = useMemo(
    () => filterClustersByScope(viewModel.clusters, clusterScope),
    [clusterScope, viewModel.clusters]
  );

  const searchValue = searchTerm.trim().toLowerCase();
  const filteredClusters = useMemo(
    () => scopedClusters
      .map((cluster) => ({
        ...cluster,
        drones: cluster.drones.filter((drone) => (
          searchValue.length === 0
          || matchesDroneSearchQuery(drone, searchValue, [
            drone.roleLabel,
            drone.ip,
            drone.follow,
            drone.title,
            drone.subtitle,
          ])
        )),
      }))
      .filter((cluster) => cluster.drones.length > 0),
    [scopedClusters, searchValue]
  );

  const filteredDroneIds = useMemo(
    () => new Set(filteredClusters.flatMap((cluster) => cluster.drones.map((drone) => drone.hw_id))),
    [filteredClusters]
  );
  const visibleDroneCount = useMemo(
    () => filteredClusters.reduce((count, cluster) => count + cluster.drones.length, 0),
    [filteredClusters]
  );

  useEffect(() => {
    let isActive = true;

    async function loadSwarmDesignData() {
      try {
        const [swarmResponse, configResponse] = await Promise.all([
          getSwarmConfigResponse(),
          getFleetConfigResponse(),
        ]);

        if (!isActive) {
          return;
        }

        const normalizedConfig = (Array.isArray(configResponse?.data) ? configResponse.data : [])
          .map((entry) => normalizeConfigDrone(entry))
          .filter(Boolean);
        const normalizedSwarm = (unwrapSwarmConfigPayload(swarmResponse?.data) || [])
          .map((entry) => normalizeSwarmAssignment(entry))
          .filter(Boolean);
        const { assignments } = buildWorkingSwarmAssignments(normalizedConfig, normalizedSwarm);
        const firstDroneId = assignments[0]?.hw_id || null;

        setConfigData(normalizedConfig);
        setServerSwarmData(normalizedSwarm);
        setBaselineAssignments(assignments);
        setWorkingAssignments(assignments);
        setSelectedDroneId((currentId) => assignments.some((assignment) => assignment.hw_id === currentId) ? currentId : firstDroneId);
        setExpandedDroneId((currentId) => assignments.some((assignment) => assignment.hw_id === currentId) ? currentId : firstDroneId);
      } catch (error) {
        console.error('Error fetching Smart Swarm data:', error);
        toast.error('Failed to load Smart Swarm configuration.');
      }
    }

    loadSwarmDesignData();

    return () => {
      isActive = false;
    };
  }, []);

  const refreshGitStatus = async () => {
    setGitStatusLoading(true);
    try {
      const response = await getUnifiedGitStatusResponse();
      setGitStatus(response?.data || null);
      return response?.data || null;
    } catch (error) {
      console.error('Error fetching GCS git status:', error);
      setGitStatus(null);
      setSaveReport({
        tone: 'warning',
        title: 'Git status unavailable',
        message: 'Smart Swarm can still save assignments, but commit readiness could not be checked from GCS git status.',
      });
      return null;
    } finally {
      setGitStatusLoading(false);
    }
  };

  useEffect(() => {
    refreshGitStatus();
  }, []);

  useEffect(() => {
    if (viewModel.drones.length === 0) {
      if (selectedDroneId !== null) {
        setSelectedDroneId(null);
      }
      if (expandedDroneId !== null) {
        setExpandedDroneId(null);
      }
      return;
    }

    if (!selectedDroneId || !viewModel.dronesById[selectedDroneId]) {
      const nextDroneId = viewModel.drones[0].hw_id;
      setSelectedDroneId(nextDroneId);
      setExpandedDroneId(nextDroneId);
    }
    if (expandedDroneId && !viewModel.dronesById[expandedDroneId]) {
      setExpandedDroneId(selectedDroneId || viewModel.drones[0].hw_id);
    }
  }, [expandedDroneId, selectedDroneId, viewModel.drones, viewModel.dronesById]);

  useEffect(() => {
    const executableClusterIds = new Set(
      viewModel.clusters
        .filter((cluster) => cluster.type === 'cluster')
        .map((cluster) => cluster.id)
    );

    if (executableClusterIds.size === 0) {
      if (selectedClusterId !== null) {
        setSelectedClusterId(null);
      }
      return;
    }

    if (selectedClusterId === 'all' || executableClusterIds.has(selectedClusterId)) {
      return;
    }

    const fallbackClusterId = selectedDrone?.clusterRootId
      || viewModel.clusters.find((cluster) => cluster.type === 'cluster')?.id
      || null;

    if (fallbackClusterId && fallbackClusterId !== selectedClusterId) {
      setSelectedClusterId(fallbackClusterId);
    }
  }, [selectedClusterId, selectedDrone?.clusterRootId, viewModel.clusters]);

  useEffect(() => {
    if (!pendingCardFocusId) {
      return;
    }

    const targetNode = cardRefs.current[pendingCardFocusId];
    if (!targetNode) {
      return;
    }

    targetNode.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });
    targetNode.focus({ preventScroll: true });
    setPendingCardFocusId(null);
  }, [filteredClusters, pendingCardFocusId]);

  useEffect(() => {
    if (!requestedDroneId) {
      handledRouteDroneRef.current = '';
      return;
    }

    if (!viewModel.dronesById[requestedDroneId] || handledRouteDroneRef.current === requestedDroneId) {
      return;
    }

    if (searchValue && !filteredDroneIds.has(requestedDroneId)) {
      setSearchTerm('');
    }

    handledRouteDroneRef.current = requestedDroneId;
    setSelectedDroneId(requestedDroneId);
    setExpandedDroneId(requestedDroneId);
    setPendingCardFocusId(requestedDroneId);
  }, [filteredDroneIds, requestedDroneId, searchValue, viewModel.dronesById]);

  const refreshFromServer = async () => {
    const [swarmResponse, configResponse] = await Promise.all([
      getSwarmConfigResponse(),
      getFleetConfigResponse(),
    ]);

    const normalizedConfig = (Array.isArray(configResponse?.data) ? configResponse.data : [])
      .map((entry) => normalizeConfigDrone(entry))
      .filter(Boolean);
    const normalizedSwarm = (unwrapSwarmConfigPayload(swarmResponse?.data) || [])
      .map((entry) => normalizeSwarmAssignment(entry))
      .filter(Boolean);
    const { assignments } = buildWorkingSwarmAssignments(normalizedConfig, normalizedSwarm);

    setConfigData(normalizedConfig);
    setServerSwarmData(normalizedSwarm);
    setBaselineAssignments(assignments);
    setWorkingAssignments(assignments);
  };

  const handleAssignmentChange = (hwId, patch) => {
    setSaveReport(null);
    setSaveProgress(null);
    setWorkingAssignments((currentAssignments) => (
      currentAssignments.map((assignment) => (
        assignment.hw_id === hwId
          ? {
              ...assignment,
              ...patch,
            }
          : assignment
      ))
    ));
  };

  const handleSelectDrone = (droneId, { fromGraph = false } = {}) => {
    if (fromGraph && searchValue && !filteredDroneIds.has(droneId)) {
      setSearchTerm('');
    }

    const nextDrone = viewModel.dronesById[droneId];
    setSelectedDroneId(droneId);
    setExpandedDroneId(droneId);
    setPendingCardFocusId(droneId);
    if (nextDrone?.clusterRootId) {
      setSelectedClusterId(nextDrone.clusterRootId);
    }
  };

  const handleToggleExpand = (droneId) => {
    setExpandedDroneId((currentId) => currentId === droneId ? null : droneId);
  };

  const handleImport = (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';

    if (!file) {
      return;
    }

    const reader = new FileReader();
    reader.onload = (loadEvent) => {
      const fileText = loadEvent.target?.result;
      if (typeof fileText !== 'string') {
        toast.error('Unable to read the selected file.');
        return;
      }

      const applyImportedAssignments = (rawAssignments) => {
        const importedAssignments = rawAssignments
          .map((assignment) => normalizeSwarmAssignment(assignment))
          .filter(Boolean);
        const importedResult = buildWorkingSwarmAssignments(configData, importedAssignments);

        setWorkingAssignments(importedResult.assignments);
        setSaveReport(null);
        setSaveProgress(null);

        const importedCount = importedAssignments.length;
        const defaultedCount = importedResult.syncChanges.addedIds.length;
        const ignoredCount = importedResult.syncChanges.removedIds.length;

        toast.success(
          `Imported ${importedCount} assignment${importedCount === 1 ? '' : 's'}`
          + `${defaultedCount > 0 ? `, added ${defaultedCount} default fleet entr${defaultedCount === 1 ? 'y' : 'ies'}` : ''}`
          + `${ignoredCount > 0 ? `, ignored ${ignoredCount} non-fleet entr${ignoredCount === 1 ? 'y' : 'ies'}` : ''}.`
        );
      };

      try {
        const parsedJson = JSON.parse(fileText);
        const rawAssignments = Array.isArray(parsedJson)
          ? parsedJson
          : parsedJson.assignments || [];

        if (rawAssignments.length === 0) {
          toast.error('No swarm assignments found in the JSON file.');
          return;
        }

        applyImportedAssignments(rawAssignments);
        return;
      } catch {
        Papa.parse(fileText, {
          header: false,
          skipEmptyLines: true,
          complete: ({ data }) => {
            if (!Array.isArray(data) || data.length < 2) {
              toast.error('The CSV file is empty or incomplete.');
              return;
            }

            const header = data[0].map((cell) => String(cell).trim());
            if (header.join(',') !== CSV_HEADERS.join(',')) {
              toast.error(`CSV header mismatch. Expected: ${CSV_HEADERS.join(', ')}`);
              return;
            }

            const rows = data.slice(1).map((row) => ({
              hw_id: row[0],
              follow: row[1],
              offset_x: row[2],
              offset_y: row[3],
              offset_z: row[4],
              frame: row[5],
            }));

            applyImportedAssignments(rows);
          },
          error: () => {
            toast.error('Failed to parse the imported CSV file.');
          },
        });
      }
    };

    reader.readAsText(file);
  };

  const handleJsonExport = () => {
    const payload = {
      version: 1,
      assignments: toSwarmApiPayload(workingAssignments),
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'swarm.json';
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleCsvExport = () => {
    const payload = toSwarmApiPayload(workingAssignments);
    const csv = Papa.unparse(payload, { columns: CSV_HEADERS });
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'swarm_assignments.csv';
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleRevert = () => {
    if (!hasStagedChanges) {
      return;
    }

    setConfirmDialog({
      title: 'Revert staged edits?',
      confirmLabel: 'Revert',
      message: (
        <p>
          Discard {dirtyIds.length} local Smart Swarm assignment change{dirtyIds.length === 1 ? '' : 's'} and restore
          the last loaded configuration.
        </p>
      ),
      onConfirm: () => {
        setConfirmDialog(null);
        setWorkingAssignments(baselineAssignments);
        setSaveReport(null);
        setSaveProgress(null);
        toast.info('Reverted local Smart Swarm changes.');
      },
    });
  };

  const saveSwarmData = async (withCommit) => {
    const operation = withCommit ? 'commit' : 'update';
    setSaveOperation(operation);
    setSaving(true);
    setSaveProgress(buildSwarmSaveProgress({
      title: withCommit ? 'Publishing Smart Swarm' : 'Saving Smart Swarm draft',
      message: withCommit
        ? 'Saving swarm.json, committing it, then pushing it to the repo.'
        : 'Saving swarm.json on this GCS. Drones will not pull this until it is published.',
      tone: 'info',
      withCommit,
      stepStates: withCommit ? ['active', 'pending', 'pending'] : ['active', 'skipped', 'skipped'],
    }));

    try {
      toast.info(withCommit ? 'Publishing Smart Swarm assignments...' : 'Saving Smart Swarm draft...');
      const response = await saveSwarmConfigResponse(
        toSwarmApiPayload(workingAssignments),
        { commit: withCommit }
      );

      const responseData = response?.data || {};
      const outcome = classifySwarmSaveOutcome(responseData, withCommit);
      const gitResult = outcome.gitResult;
      if (!withCommit) {
        setLocalSwarmCommitPending(true);
      } else if (outcome.tone === 'danger') {
        setLocalSwarmCommitPending(!gitResult?.commit_hash);
      } else {
        setLocalSwarmCommitPending(false);
      }
      if (withCommit && outcome.tone === 'danger') {
        toast.warning("Smart Swarm saved locally, but git commit/push failed: " + (gitResult?.message || responseData.message || "unknown git error"));
        setSaveReport({
          tone: outcome.tone,
          title: outcome.title,
          message: outcome.message,
        });
        setSaveProgress(buildSwarmSaveProgress({
          title: outcome.title,
          message: outcome.message,
          tone: outcome.tone,
          withCommit,
          stepStates: outcome.stepStates,
        }));
      } else {
        const toastMessage = responseData.message || (withCommit
          ? 'Smart Swarm configuration published successfully.'
          : 'Smart Swarm configuration saved successfully.');
        if (withCommit && outcome.tone === 'warning') {
          toast.warning(toastMessage);
        } else {
          toast.success(toastMessage);
        }
        setSaveReport({
          tone: outcome.tone,
          title: outcome.title,
          message: outcome.message,
        });
        setSaveProgress(buildSwarmSaveProgress({
          title: outcome.title,
          message: outcome.message,
          tone: outcome.tone,
          withCommit,
          stepStates: outcome.stepStates,
        }));
      }
      await refreshFromServer();
      await refreshGitStatus();
    } catch (error) {
      console.error('Failed to save Smart Swarm configuration:', error);
      setSaveReport({
        tone: 'danger',
        title: withCommit ? 'Commit failed' : 'Update failed',
        message: error?.response?.data?.detail || error?.message || 'GCS did not accept the Smart Swarm save request.',
      });
      setSaveProgress(buildSwarmSaveProgress({
        title: withCommit ? 'Commit failed' : 'Update failed',
        message: error?.response?.data?.detail || error?.message || 'GCS did not accept the Smart Swarm save request.',
        tone: 'danger',
        withCommit,
        stepStates: ['blocked', withCommit ? 'pending' : 'skipped', withCommit ? 'pending' : 'skipped'],
      }));
      toast.error('Failed to save Smart Swarm configuration.');
    } finally {
      setSaving(false);
      setSaveOperation(null);
    }
  };

  const confirmAndSave = (withCommit) => {
    if (hasBlockingIssues) {
      toast.error('Resolve blocking follow-chain issues before saving Smart Swarm assignments.');
      return;
    }

    if (hasIncompleteInputs) {
      toast.error('Complete or clear all offset fields before saving.');
      return;
    }

    if (!withCommit && !canUpdateSwarm) {
      toast.info('No Smart Swarm changes are staged for update.');
      return;
    }

    if (withCommit && !canCommitSwarm) {
      toast.info('No Smart Swarm changes are staged or pending commit.');
      return;
    }

    const summaryLines = [
      `${viewModel.summary.totalDrones} drones across ${viewModel.summary.clusterCount} cluster${viewModel.summary.clusterCount === 1 ? '' : 's'}`,
      `${viewModel.summary.topLeaderCount} top leaders, ${viewModel.summary.relayLeaderCount} relay leaders, ${viewModel.summary.followerCount} followers`,
      `${dirtyIds.length} staged assignment change${dirtyIds.length === 1 ? '' : 's'}`,
      `${syncChanges.addedIds.length + syncChanges.removedIds.length} fleet sync update${syncChanges.addedIds.length + syncChanges.removedIds.length === 1 ? '' : 's'}`,
      `${viewModel.summary.attentionCount} drone${viewModel.summary.attentionCount === 1 ? '' : 's'} flagged for operator attention`,
    ];

    if (withCommit && hasCommitPending && !canUpdateSwarm) {
      summaryLines.push('saved swarm.json change pending git commit');
    }

    setConfirmDialog({
      title: `${withCommit ? 'Publish' : 'Save draft'} Smart Swarm assignments?`,
      confirmLabel: withCommit ? 'Publish' : 'Save draft',
      message: (
        <div className="swarm-confirm-summary">
          <p>Review the formation summary before saving this assignment set.</p>
          <ul>
            {summaryLines.map((line) => <li key={line}>{line}</li>)}
          </ul>
        </div>
      ),
      onConfirm: () => {
        setConfirmDialog(null);
        saveSwarmData(withCommit);
      },
    });
  };

  const summaryItems = [
    {
      icon: <FaLayerGroup />,
      label: 'Drones',
      value: viewModel.summary.totalDrones,
      tone: 'neutral',
    },
    {
      icon: <FaProjectDiagram />,
      label: 'Clusters',
      value: viewModel.summary.clusterCount,
      tone: 'neutral',
    },
    {
      icon: <FaSyncAlt />,
      label: 'Relay Leaders',
      value: viewModel.summary.relayLeaderCount,
      tone: 'warning',
    },
    {
      icon: <FaSave />,
      label: 'Staged Changes',
      value: dirtyIds.length,
      tone: dirtyIds.length > 0 ? 'info' : 'neutral',
    },
    {
      icon: <FaExclamationTriangle />,
      label: 'Attention',
      value: viewModel.summary.attentionCount,
      tone: viewModel.summary.attentionCount > 0 ? 'danger' : 'success',
    },
  ];
  const pageStatusTone = saving
    ? 'info'
    : hasBlockingIssues || hasIncompleteInputs
    ? 'danger'
    : hasStagedChanges || hasPendingSync
      ? 'warning'
      : 'success';
  const pageStatusLabel = saving
    ? (saveOperation === 'commit' ? 'Committing' : 'Saving')
    : hasBlockingIssues || hasIncompleteInputs
      ? 'Blocked'
      : hasStagedChanges || hasPendingSync
        ? 'Staged'
      : 'Clean';

  return (
    <PageShell
      className="swarm-design-page"
      eyebrow="Smart swarm"
      title="Smart Swarm"
      subtitle="Formation roles, offsets, and git-backed fleet publish."
      icon={<FaProjectDiagram />}
      docsRoute="/swarm-design"
      status={<StatusBadge tone={pageStatusTone}>{pageStatusLabel}</StatusBadge>}
      actions={(
        <PageActionBar
          className="swarm-design-actions"
          primary={[
            <ActionIconButton
              key="update"
              icon={<FaSyncAlt />}
              label="Save Smart Swarm draft on this GCS"
              onClick={() => confirmAndSave(false)}
              tone="info"
              active={saving && saveOperation === 'update'}
              aria-busy={saving && saveOperation === 'update'}
              className={saving && saveOperation === 'update' ? 'is-busy' : ''}
              disabled={saving || hasBlockingIssues || hasIncompleteInputs || !canUpdateSwarm}
              data-help="Save swarm.json on this GCS only. Publish next when the formation is ready for fleet sync."
            >
              {saving && saveOperation === 'update' ? 'Saving' : 'Save Draft'}
            </ActionIconButton>,
            <ActionIconButton
              key="commit"
              icon={<FaCloudUploadAlt />}
              label="Publish Smart Swarm assignment changes"
              onClick={() => confirmAndSave(true)}
              tone="success"
              active={saving && saveOperation === 'commit'}
              aria-busy={saving && saveOperation === 'commit'}
              className={saving && saveOperation === 'commit' ? 'is-busy' : ''}
              disabled={saving || hasBlockingIssues || hasIncompleteInputs || !canCommitSwarm}
              data-help="Save, commit, and push swarm.json. Use Fleet Ops if drones need to pull the latest commit."
            >
              {saving && saveOperation === 'commit' ? 'Publishing' : 'Publish'}
            </ActionIconButton>,
          ]}
          secondary={[
            <label
              key="import"
              className="operator-action-icon-button operator-action-icon-button--neutral operator-action-icon-button--md swarm-action-file-button"
              aria-label="Import Smart Swarm assignments from JSON or CSV"
              role="button"
              tabIndex={0}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault();
                  event.currentTarget.querySelector('input[type="file"]')?.click();
                }
              }}
            >
              <span className="operator-action-icon-button__icon" aria-hidden="true"><FaUpload /></span>
              <span className="operator-action-icon-button__text">Import</span>
              <input type="file" accept=".json,.csv" onChange={handleImport} />
            </label>,
            <ActionIconButton
              key="json"
              icon={<FaDownload />}
              label="Export Smart Swarm assignments as JSON"
              onClick={handleJsonExport}
              disabled={workingAssignments.length === 0}
            >
              JSON
            </ActionIconButton>,
            <ActionIconButton
              key="csv"
              icon={<FaDownload />}
              label="Export Smart Swarm assignments as CSV"
              onClick={handleCsvExport}
              disabled={workingAssignments.length === 0}
            >
              CSV
            </ActionIconButton>,
            <ActionIconButton
              key="revert"
              icon={<FaUndo />}
              label="Revert local Smart Swarm edits"
              onClick={handleRevert}
              disabled={!hasStagedChanges}
              tone="warning"
            >
              Revert
            </ActionIconButton>,
          ]}
          overflowLabel="Files"
        />
      )}
    >

      <IdentityDoctrineStrip surface="swarm-design" className="identity-doctrine-strip--compact" />

      <MetricStrip label="Smart Swarm topology summary" items={summaryItems} />

      <SwarmSaveProgress progress={saveProgress} />

      <section className="swarm-status-strip">
        {hasPendingSync && (
          <OperatorNotice tone="warning" title="Fleet sync pending" className="swarm-status-card sync">
            <span
              data-help={`${syncChanges.addedIds.length > 0 ? `Add default assignments for drones ${syncChanges.addedIds.join(', ')}. ` : ''}${syncChanges.removedIds.length > 0 ? `Prune legacy assignments for drones ${syncChanges.removedIds.join(', ')}.` : ''}`.trim()}
            >
              {pendingSyncIds.length} fleet assignment update{pendingSyncIds.length === 1 ? '' : 's'}
            </span>
          </OperatorNotice>
        )}

        {viewModel.summary.roleSwapCount > 0 && (
          <OperatorNotice tone="info" title="Slot reassignments active" className="swarm-status-card note">
            <span data-help="One or more drones are assigned to a show slot that differs from their hardware ID.">
              {viewModel.summary.roleSwapCount} slot swap{viewModel.summary.roleSwapCount === 1 ? '' : 's'}
            </span>
          </OperatorNotice>
        )}

        {(hasBlockingIssues || hasIncompleteInputs) && (
          <OperatorNotice tone="danger" title="Save blocked" className="swarm-status-card attention">
            <span>
              {hasBlockingIssues ? 'Resolve self-follow, missing leader, or cycle issues.' : ''}
              {hasBlockingIssues && hasIncompleteInputs ? ' ' : ''}
              {hasIncompleteInputs ? 'Complete partial offset values before update or commit.' : ''}
            </span>
          </OperatorNotice>
        )}

        {(saveReport || gitStatusLoading || hasCommitPending) && (
          <OperatorNotice
            tone={saveReport?.tone || (hasCommitPending ? 'warning' : 'info')}
            title={saveReport?.title || (gitStatusLoading ? 'Checking git status' : 'Commit pending')}
            className="swarm-status-card git"
          >
            <span>
              {saveReport?.message
                || (gitStatusLoading
                  ? 'Reading GCS repository status.'
                  : localSwarmCommitPending
                    ? 'Draft saved on this GCS. Publish is available now.'
                    : 'swarm.json is saved on this GCS and still needs to be published to the repo.')}
            </span>
          </OperatorNotice>
        )}
      </section>

      <SwarmRuntimeControls
        viewModel={viewModel}
        selectedDroneId={selectedDroneId}
        selectedClusterId={selectedClusterId}
        dirtyIds={dirtyIds}
        pendingSyncIds={pendingSyncIds}
        telemetryById={telemetryById}
        onReviewSelection={(droneId) => handleSelectDrone(droneId)}
        onOpenMissionConfig={(droneId) => navigate(`/mission-config?drone=${droneId}&edit=1`)}
      />

      <div className="swarm-operations-layout">
        <section className="swarm-panel swarm-panel--assignments">
          <div className="swarm-panel__header">
            <div>
              <h2>Assignments</h2>
            </div>

            <label className="swarm-search-field">
              <FaSearch />
              <input
                type="search"
                placeholder={DRONE_SEARCH_PLACEHOLDER}
                value={searchTerm}
                onChange={(event) => setSearchTerm(event.target.value)}
              />
            </label>
          </div>

          <div className="swarm-panel__subheader">
            <span>{visibleDroneCount} of {viewModel.summary.totalDrones} drones visible</span>
            <span>{dirtyIds.length} staged</span>
          </div>

          {clusterScopeOptions.length > 1 && (
            <ClusterScopeBar
              label="Cluster scope"
              options={clusterScopeOptions}
              selectedId={clusterScope}
              onSelect={setClusterScope}
              summary="Top-leader scopes keep large swarm audits readable without changing saved topology."
            />
          )}

          <div className="swarm-cluster-stack">
            {filteredClusters.length === 0 && (
              <EmptyState
                title="No matching drones"
                detail={`Try a different term or a scoped query like pos 1-5, hw 2,4, or a callsign. ${DRONE_SEARCH_HELP_TEXT}`}
                className="swarm-empty-state"
              />
            )}

            {filteredClusters.map((cluster) => (
              <section
                key={cluster.id}
                className={`swarm-cluster-section ${cluster.type === 'attention' ? 'attention' : ''}`}
              >
                <header className="swarm-cluster-section__header">
                  <div>
                    <h3>{cluster.title}</h3>
                    <p>{cluster.subtitle}</p>
                  </div>

                  <div className="swarm-cluster-section__stats">
                    <span>{cluster.counts.total} drones</span>
                    <span>{cluster.counts.relayLeaders} relay</span>
                    <span>{cluster.counts.followers} followers</span>
                    {cluster.warningCount > 0 && <span>{cluster.warningCount} attention</span>}
                  </div>
                </header>

                <div className="swarm-card-list">
                  {cluster.drones.map((drone) => {
                    const rawAssignment = workingAssignments.find((assignment) => String(assignment.hw_id) === drone.hw_id) || drone;

                    return (
                      <DroneCard
                        key={drone.hw_id}
                        ref={(node) => {
                          if (node) {
                            cardRefs.current[drone.hw_id] = node;
                          } else {
                            delete cardRefs.current[drone.hw_id];
                          }
                        }}
                        drone={drone}
                        draftAssignment={rawAssignment}
                        followOptions={viewModel.followOptions}
                        onSelect={(droneId) => handleSelectDrone(droneId)}
                        onToggleExpand={handleToggleExpand}
                        onAssignmentChange={handleAssignmentChange}
                        isSelected={selectedDroneId === drone.hw_id}
                        isExpanded={expandedDroneId === drone.hw_id}
                        isDirty={dirtyIdSet.has(drone.hw_id)}
                      />
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </section>

        <section className="swarm-panel swarm-panel--graph">
          <div className="swarm-panel__header">
            <div>
              <h2>Topology</h2>
            </div>
          </div>

          <div className="swarm-graph-panel">
            <div className="swarm-graph-stage">
              <DroneGraph
                swarmData={viewModel.drones}
                selectedDroneId={selectedDroneId}
                onSelectDrone={(droneId) => handleSelectDrone(droneId, { fromGraph: true })}
              />
            </div>

            <div className="swarm-graph-legend">
              <span className="legend-item leader">Top leader</span>
              <span className="legend-item relay">Relay leader</span>
              <span className="legend-item follower">Follower</span>
              <span className="legend-item arrow-flow">Leader to follower</span>
              <span className="legend-item line-solid">Geographic offset</span>
              <span className="legend-item line-dashed">Body-relative offset</span>
            </div>

            <div className="swarm-selection-panel">
              {selectedDrone ? (
                <>
                  <div className="swarm-selection-panel__header">
                    <div>
                      <span className="swarm-selection-panel__eyebrow">Selected Drone</span>
                      <h3>{selectedDrone.title}</h3>
                      {selectedDrone.alias && <p className="swarm-selection-panel__alias">{selectedDrone.aliasLabel || 'Alias'}: {selectedDrone.alias}</p>}
                    </div>
                    <span className={`swarm-role-badge ${selectedDrone.role}`}>{selectedDrone.roleLabel}</span>
                  </div>

                  <dl className="swarm-selection-panel__details">
                    <div>
                      <dt>Show Slot</dt>
                      <dd>{selectedDrone.pos_id}</dd>
                    </div>
                    <div>
                      <dt>Follow Target</dt>
                      <dd>{selectedDrone.follow === '0' ? 'Independent leader' : formatDroneLabel(selectedDrone.follow)}</dd>
                    </div>
                    <div>
                      <dt>Offset Frame</dt>
                      <dd>{selectedDrone.frameLabel}</dd>
                    </div>
                    <div>
                      <dt>Relative Offset</dt>
                      <dd>{selectedDrone.offsetSummary}</dd>
                    </div>
                    <div>
                      <dt>Direct Followers</dt>
                      <dd>{selectedDrone.directFollowerCount}</dd>
                    </div>
                  </dl>

                  {selectedDrone.warnings.length > 0 && (
                    <div className="swarm-selection-panel__warnings">
                      {selectedDrone.warnings.map((warning) => (
                        <div key={`${selectedDrone.hw_id}-${warning.code}`} className={`selection-warning ${warning.severity}`}>
                          <FaExclamationTriangle />
                          <span>{warning.message}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <EmptyState
                  title="No drone selected"
                  detail="Select a graph node or assignment card to inspect its details."
                  className="swarm-empty-state compact"
                />
              )}
            </div>
          </div>
        </section>
      </div>

      <section className="swarm-panel swarm-panel--plots">
        <div className="swarm-panel__header">
          <div>
            <h2>Formation Preview</h2>
          </div>
        </div>

        <SwarmPlots
          swarmData={workingAssignments}
          configData={configData}
          selectedClusterId={selectedClusterId}
          onSelectedClusterChange={setSelectedClusterId}
        />
      </section>

      <ConfirmDialog
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm Smart Swarm action'}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        busy={saving}
        onConfirm={() => confirmDialog?.onConfirm?.()}
        onCancel={() => setConfirmDialog(null)}
      />
    </PageShell>
  );
}

export default SwarmDesign;
