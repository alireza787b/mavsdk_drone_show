import React, { useEffect, useMemo, useRef, useState } from 'react';
import Papa from 'papaparse';
import { useSearchParams } from 'react-router-dom';
import {
  FaCloudUploadAlt,
  FaDownload,
  FaProjectDiagram,
  FaSave,
  FaUndo,
  FaUpload,
} from 'react-icons/fa';
import { toast } from 'react-toastify';
import SwarmRuntimeControls from '../components/SwarmRuntimeControls';
import SwarmDesignWorkspace from '../components/SwarmDesignWorkspace';
import { preservePositionPatch } from '../utilities/swarmFormationGeometry';
import { getBackendURL } from '../config/apiConfig';
import useSwarmDesignDraft from '../hooks/useSwarmDesignDraft';
import {
  ActionIconButton,
  ConfirmDialog,
  OperatorNotice,
  PageActionBar,
  PageShell,
  StatusBadge,
} from '../components/ui/OperatorPrimitives';
import '../styles/SwarmDesign.css';
import {
  getFleetConfigResponse,
  getSwarmConfigResponse,
  getUnifiedGitStatusResponse,
  saveSwarmConfigResponse,
  getSwarmDesignStatusResponse,
  publishSwarmConfigResponse,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import {
  buildSwarmViewModel,
  buildWorkingSwarmAssignments,
  getDirtyAssignmentIds,
  normalizeConfigDrone,
  normalizeSwarmAssignment,
  toSwarmApiPayload,
} from '../utilities/swarmDesignUtils';

const CSV_HEADERS = ['hw_id', 'follow', 'offset_x', 'offset_y', 'offset_z', 'frame'];
const DRAFT_KEY = `mds.swarmDesign.draft.v2:${getBackendURL()}`;

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
      title: 'Applied on GCS',
      message: 'The formation is active on this GCS. Publish is optional repository persistence.',
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
  const labels = ['Apply', 'Commit', 'Push'];
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
  const [searchParams] = useSearchParams();
  const [tab, setTab] = useState(searchParams.get('tab') === 'formation' || searchParams.get('tab') === 'design' || searchParams.get('drone') ? 'formation' : 'operate');
  const [previewHeadings, setPreviewHeadings] = useState({});
  const draftHistory = useSwarmDesignDraft();
  const { assignments: workingAssignments, assignmentsRef: workingRef,
    reset: setWorkingAssignments, begin: beginEdit, end: endEdit,
    undo: undoEdit, redo: redoEdit } = draftHistory;
  const handledRouteDroneRef = useRef('');

  const [configData, setConfigData] = useState([]);
  const [serverSwarmData, setServerSwarmData] = useState([]);
  const [serverSwarmRevision, setServerSwarmRevision] = useState('');
  const [applicationStatus, setApplicationStatus] = useState(null);
  const [recoverableDraft, setRecoverableDraft] = useState(null);
  const [draftStorageError, setDraftStorageError] = useState(false);
  const [baselineAssignments, setBaselineAssignments] = useState([]);
  const [selectedDroneId, setSelectedDroneId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveOperation, setSaveOperation] = useState(null);
  const [gitStatus, setGitStatus] = useState(null);
  const [gitStatusLoading, setGitStatusLoading] = useState(false);
  const [saveReport, setSaveReport] = useState(null);
  const [saveProgress, setSaveProgress] = useState(null);
  const [localSwarmCommitPending, setLocalSwarmCommitPending] = useState(false);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const requestedDroneId = String(searchParams.get('drone') || '').trim();

  const viewModel = useMemo(
    () => buildSwarmViewModel(workingAssignments, configData),
    [configData, workingAssignments]
  );
  const dirtyIds = useMemo(
    () => getDirtyAssignmentIds(workingAssignments, baselineAssignments),
    [baselineAssignments, workingAssignments]
  );
  const syncChanges = useMemo(
    () => buildWorkingSwarmAssignments(configData, serverSwarmData).syncChanges,
    [configData, serverSwarmData]
  );
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
    ['offset_x', 'offset_y', 'offset_z'].some((field) => hasIncompleteNumericValue(assignment[field]) || !Number.isFinite(Number(assignment[field])))
  );
  const pendingSyncIds = useMemo(
    () => [...new Set([...syncChanges.addedIds, ...syncChanges.removedIds].map((value) => String(value)))],
    [syncChanges.addedIds, syncChanges.removedIds]
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
        let initialAssignments = assignments;
        try {
          const savedDraft = JSON.parse(window.localStorage.getItem(DRAFT_KEY) || 'null');
          const draftAssignments = Array.isArray(savedDraft) ? savedDraft : savedDraft?.assignments;
          const draftBase = Array.isArray(savedDraft) ? null : savedDraft?.base;
          const sameBase = draftBase && JSON.stringify(draftBase) === JSON.stringify(assignments);
          if (sameBase && Array.isArray(draftAssignments) && draftAssignments.length === assignments.length
            && draftAssignments.every((entry) => assignments.some((assignment) => String(assignment.hw_id) === String(entry.hw_id)))) {
            initialAssignments = buildWorkingSwarmAssignments(normalizedConfig, draftAssignments).assignments;
            if (savedDraft.previewHeadings && typeof savedDraft.previewHeadings === 'object') setPreviewHeadings(savedDraft.previewHeadings);
          } else if (Array.isArray(draftAssignments)) {
            setRecoverableDraft(savedDraft);
          }
        } catch {
          // A corrupt browser draft must never block loading the server plan.
        }
        const firstDroneId = assignments[0]?.hw_id || null;

        setConfigData(normalizedConfig);
        setServerSwarmData(normalizedSwarm);
        setServerSwarmRevision(String(swarmResponse?.data?.revision || ''));
        setBaselineAssignments(assignments);
        setWorkingAssignments(initialAssignments);
        setSelectedDroneId((currentId) => assignments.some((assignment) => assignment.hw_id === currentId) ? currentId : firstDroneId);
      } catch (error) {
        console.error('Error fetching Smart Swarm data:', error);
        toast.error('Failed to load Smart Swarm configuration.');
      }
    }

    loadSwarmDesignData();

    return () => {
      isActive = false;
    };
  }, [setWorkingAssignments]);

  useEffect(() => {
    if (workingAssignments.length > 0 && !recoverableDraft) {
      try { window.localStorage.setItem(DRAFT_KEY, JSON.stringify({
        base: baselineAssignments,
        assignments: workingAssignments,
        previewHeadings,
      })); } catch { setDraftStorageError(true); }
    }
  }, [baselineAssignments, workingAssignments, recoverableDraft, previewHeadings]);

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
    if (tab !== 'formation' || !serverSwarmRevision) return undefined;
    let cancelled = false;
    let timer;
    const poll = async () => {
      try {
        const response = await getSwarmDesignStatusResponse({ timeout: 4000 });
        if (!cancelled) setApplicationStatus(response.data);
      } catch {
        if (!cancelled) setApplicationStatus(null);
      }
      if (!cancelled) timer = setTimeout(poll, 3000);
    };
    poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [tab, serverSwarmRevision]);

  useEffect(() => {
    if (requestedDroneId && viewModel.dronesById[requestedDroneId] && handledRouteDroneRef.current !== requestedDroneId) {
      handledRouteDroneRef.current = requestedDroneId;
      setSelectedDroneId(requestedDroneId);
    } else if (!viewModel.dronesById[selectedDroneId]) {
      setSelectedDroneId(viewModel.drones[0]?.hw_id || null);
    }
  }, [requestedDroneId, selectedDroneId, viewModel.drones, viewModel.dronesById]);

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
    setServerSwarmRevision(String(swarmResponse?.data?.revision || ''));
    setBaselineAssignments(assignments);
    setWorkingAssignments(assignments);
  };

  const handleAssignmentChange = (hwId, patch) => {
    setSaveReport(null);
    setSaveProgress(null);
    const current = workingRef.current;
    let actualPatch = patch;
    try {
      if ('follow' in patch || 'frame' in patch) actualPatch = preservePositionPatch(current, String(hwId), patch, previewHeadings);
    } catch (error) {
      if (error.message.startsWith('Independent clusters')) {
        setConfirmDialog({ title: 'Join this formation?', confirmLabel: 'Join formation',
          message: <p>These leaders have no shared position reference. Keep this aircraft’s existing spacing relative to the new leader, then adjust it in the canvas.</p>,
          onConfirm: () => {
            setConfirmDialog(null);
            draftHistory.edit(hwId, patch);
          } });
        return;
      }
      toast.warning(error.message);
      return;
    }
    draftHistory.edit(hwId, actualPatch);
  };


  const handleSelectDrone = (droneId) => setSelectedDroneId(String(droneId));


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

        draftHistory.replace(importedResult.assignments);
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
        try { window.localStorage.removeItem(DRAFT_KEY); } catch { setDraftStorageError(true); }
        setSaveReport(null);
        setSaveProgress(null);
        toast.info('Reverted local Smart Swarm changes.');
      },
    });
  };

  const saveSwarmData = async (withCommit, acknowledgedUnavailableIds = []) => {
    const operation = withCommit ? 'commit' : 'update';
    setSaveOperation(operation);
    setSaving(true);
    setSaveProgress(buildSwarmSaveProgress({
      title: withCommit ? 'Publishing Smart Swarm' : 'Applying Smart Swarm plan',
      message: withCommit
        ? 'Saving swarm.json, committing it, then pushing it to the repo.'
        : 'Applying the validated formation revision on this GCS.',
      tone: 'info',
      withCommit,
      stepStates: withCommit ? ['active', 'pending', 'pending'] : ['active', 'skipped', 'skipped'],
    }));

    try {
      toast.info(withCommit ? 'Publishing Smart Swarm assignments...' : 'Applying Smart Swarm plan...');
      const saveOptions = { commit: false, acknowledgedUnavailableIds };
      if (serverSwarmRevision) saveOptions.revision = serverSwarmRevision;
      const response = withCommit
        ? await publishSwarmConfigResponse(serverSwarmRevision)
        : await saveSwarmConfigResponse(toSwarmApiPayload(workingAssignments), saveOptions);

      const responseData = response?.data || {};
      setApplicationStatus(responseData.application || null);
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
      const detail = error?.response?.data?.detail;
      if (detail?.code === 'unavailable_confirmation_required') {
        const ids = detail.unavailable_hw_ids || [];
        setConfirmDialog({
          title: 'Some aircraft are unreachable', confirmLabel: 'Apply anyway',
          message: <p>{ids.map((id) => viewModel.dronesById[id]?.callsign || viewModel.dronesById[id]?.title || `Aircraft ${id}`).join(', ')}. Reachable aircraft may change first; others can pick up this plan when they reconnect.</p>,
          onConfirm: () => { setConfirmDialog(null); saveSwarmData(false, ids); },
        });
        setSaveProgress(null);
        return;
      }
      const errorMessage = typeof detail === 'string' ? detail : detail?.message || error?.message || 'The formation could not be applied.';
      console.error('Failed to save Smart Swarm configuration:', error);
      setSaveReport({
        tone: 'danger',
        title: withCommit ? 'Commit failed' : 'Update failed',
        message: errorMessage,
      });
      setSaveProgress(buildSwarmSaveProgress({
        title: withCommit ? 'Commit failed' : 'Update failed',
        message: errorMessage,
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
    if (withCommit && (hasStagedChanges || hasPendingSync)) {
      toast.info('Apply the draft first, then publish the applied plan.');
      return;
    }
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

    const summaryLines = [withCommit ? 'Publish the applied plan to the repository.' : `${dirtyIds.length} aircraft changed. Running swarm aircraft will adopt this plan through configuration updates.`];
    setConfirmDialog({
      title: `${withCommit ? 'Publish' : 'Apply'} Smart Swarm assignments?`,
      confirmLabel: withCommit ? 'Publish' : 'Apply',
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
      subtitle={tab === 'operate' ? 'Live formation control.' : 'Set who follows whom and where.'}
      icon={<FaProjectDiagram />}
      docsRoute="/swarm-design"
      status={tab === 'formation' ? <StatusBadge tone={pageStatusTone}>{pageStatusLabel}</StatusBadge> : null}
      actions={tab === 'formation' && (
        <PageActionBar
          className="swarm-design-actions"
          primary={[
            <ActionIconButton
              key="update"
              icon={<FaSave />}
              label="Apply Smart Swarm plan on this GCS"
              onClick={() => confirmAndSave(false)}
              tone="info"
              active={saving && saveOperation === 'update'}
              aria-busy={saving && saveOperation === 'update'}
              className={saving && saveOperation === 'update' ? 'is-busy' : ''}
              disabled={saving || hasBlockingIssues || hasIncompleteInputs || !canUpdateSwarm}
              data-help="Apply the validated formation on this GCS. Running swarm nodes may observe it through normal configuration polling."
            >
              {saving && saveOperation === 'update' ? 'Applying' : 'Apply'}
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
              key="commit"
              icon={<FaCloudUploadAlt />}
              label="Publish Smart Swarm assignment changes"
              onClick={() => confirmAndSave(true)}
              tone="success"
              active={saving && saveOperation === 'commit'}
              aria-busy={saving && saveOperation === 'commit'}
              className={saving && saveOperation === 'commit' ? 'is-busy' : ''}
              disabled={saving || hasStagedChanges || hasPendingSync || !canCommitSwarm}
              data-help="Publish the applied GCS plan to the repository. Does not send flight commands."
            >
              {saving && saveOperation === 'commit' ? 'Publishing' : 'Publish'}
            </ActionIconButton>,
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

      <div role="tablist" aria-label="Swarm workspace" className="swarm-workspace-tabs">
        <button type="button" role="tab" aria-selected={tab === 'operate'} onClick={() => setTab('operate')}>Operate</button>
        <button type="button" role="tab" aria-selected={tab === 'formation'} onClick={() => setTab('formation')}>Design Swarm{hasStagedChanges ? ' •' : ''}</button>
      </div>
      {tab === 'operate' && <section role="tabpanel" aria-label="Operate">
        <SwarmRuntimeControls />
      </section>}
      <section role="tabpanel" aria-label="Design Swarm" hidden={tab !== 'formation'} className="swarm-design-workspace operator-console">
      <div className="swarm-design-summary">
        <span>{viewModel.summary.totalDrones} aircraft</span>
        <span>{viewModel.summary.clusterCount} cluster{viewModel.summary.clusterCount === 1 ? '' : 's'}</span>
        <span>{dirtyIds.length ? `${dirtyIds.length} unsaved` : 'Plan saved'}</span>
      </div>
      <SwarmSaveProgress progress={saveProgress} />
      {draftStorageError && <p role="status">Draft recovery unavailable in this browser. Export before closing.</p>}
      {recoverableDraft && <div className="swarm-draft-recovery" role="status">
        <span>A previous draft differs from the current GCS plan.</span>
        <button type="button" onClick={() => {
          setWorkingAssignments(buildWorkingSwarmAssignments(configData, recoverableDraft.assignments).assignments);
          setRecoverableDraft(null);
        }}>Restore draft</button>
        <button type="button" onClick={() => setRecoverableDraft(null)}>Use GCS plan</button>
      </div>}
      {applicationStatus && <div className="swarm-apply-status" aria-label="Aircraft formation acknowledgement" role="status">
        {applicationStatus.nodes?.map((node) => <span key={node.hw_id} className={`is-${node.status}`}>
          {viewModel.dronesById[node.hw_id]?.callsign || viewModel.dronesById[node.hw_id]?.title || `Aircraft ${node.hw_id}`} · {({ applied: 'Applied', pending: 'Pending', not_reachable: 'Unreachable', inactive: 'Next start' })[node.status] || 'Unknown'}
        </span>)}
      </div>}

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

        {saveReport && !saveProgress && (
          <OperatorNotice
            tone={saveReport?.tone || (hasCommitPending ? 'warning' : 'info')}
            title={saveReport.title}
            className="swarm-status-card git"
          >
            <span>
              {saveReport?.message
                || (gitStatusLoading
                  ? 'Reading GCS repository status.'
                  : localSwarmCommitPending
                    ? 'Applied on this GCS; applied formation is ready to publish.'
                    : 'The applied formation is current on this GCS.')}
            </span>
          </OperatorNotice>
        )}
      </section>

      <SwarmDesignWorkspace assignments={workingAssignments} configData={configData}
        selectedId={selectedDroneId} onSelect={handleSelectDrone}
        onChange={handleAssignmentChange} onEditBegin={beginEdit} onEditEnd={endEdit}
        onUndo={undoEdit} onRedo={redoEdit} canUndo={draftHistory.canUndo} canRedo={draftHistory.canRedo}
        previewHeadings={previewHeadings} onHeadingChange={(id, value) => setPreviewHeadings((current) => ({ ...current, [id]: value }))}
        disabled={saving} />

      </section>
      <ConfirmDialog
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm Smart Swarm action'}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        busy={saving}
        onConfirm={() => confirmDialog?.onConfirm?.()}
        appearance="console"
        onCancel={() => setConfirmDialog(null)}
      />
    </PageShell>
  );
}

export default SwarmDesign;
