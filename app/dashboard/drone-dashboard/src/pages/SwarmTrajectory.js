import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  FaCheckCircle,
  FaArrowDown,
  FaArrowUp,
  FaExclamationTriangle,
  FaGlobeAmericas,
  FaHourglassHalf,
  FaPlus,
  FaRobot,
  FaSearchPlus,
  FaTimes,
  FaTrashAlt,
  FaUpload,
} from 'react-icons/fa';
import { toast } from 'react-toastify';

import { ConfirmDialog, DocsLink, MetricStrip, OperatorNotice, StatusBadge } from '../components/ui';
import { MissionAltitudeControl, MissionJobProgressDialog } from '../components/mission-planning';
import RouteSketch, { ROUTE_SKETCH_COLORS } from '../components/trajectory/RouteSketch';
import SwarmRouteMapEditor from '../components/trajectory/SwarmRouteMapEditor';
import SwarmTrajectoryWorkspaceSummary from '../components/trajectory/SwarmTrajectoryWorkspaceSummary';
import useFetch from '../hooks/useFetch';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import {
  buildSwarmTrajectoryPlotUrl,
  cancelSwarmTrajectoryProcessJob,
  clearAllSwarmTrajectories,
  clearSwarmTrajectoryDrone,
  clearSwarmTrajectoryLeader,
  clearProcessedData,
  commitSwarmTrajectoryOutputs,
  createSwarmTrajectoryProcessJob,
  downloadSwarmClusterKml,
  downloadSwarmTrajectoryCsv,
  downloadSwarmTrajectoryKml,
  getSwarmLeaders,
  getSwarmTrajectoryElevationBatch,
  getSwarmTrajectoryPreview,
  getSwarmTrajectoryProcessJob,
  getSwarmTrajectoryStatus,
  getSwarmTrajectoryValidation,
  removeSwarmTrajectoryUpload,
  uploadSwarmTrajectory,
} from '../services/droneApiService';
import {
  SWARM_TRAJECTORY_ALTITUDE_MODES,
  buildSwarmLeaderCsv,
  buildTerrainStatusFromResults,
  normalizeDraftWaypoint,
  toFiniteNumber,
  validateDraftWaypoint,
  validateDraftWaypoints,
} from '../utilities/swarmTrajectoryDraft';
import {
  buildSwarmTrajectoryViewModel,
  getClusterStateMeta,
} from '../utilities/swarmTrajectoryViewModel';
import {
  buildSwarmTrajectoryStages,
  buildSwarmTrajectoryWorkspaceStatus,
} from '../utilities/swarmTrajectoryWorkspaceModel';
import { uploadLeaderTrajectoryCsv } from '../utilities/swarmTrajectoryAssignment';
import '../styles/SwarmTrajectory.css';

const buildListLabel = (values = []) => (values.length > 0 ? values.join(', ') : 'None');

const buildConfirmMessage = ({ summary, details = [], warning = '' }) => (
  <div className="swarm-trajectory-confirm">
    <p>{summary}</p>
    {details.length > 0 ? (
      <ul className="swarm-trajectory-confirm__list">
        {details.map((detail) => (
          <li key={detail}>{detail}</li>
        ))}
      </ul>
    ) : null}
    {warning ? <p className="swarm-trajectory-confirm__warning">{warning}</p> : null}
  </div>
);

const formatRecommendationTone = (action = '') => action.replace(/_/g, '-');

const normalizeNoticeTone = (tone = 'info') => {
  if (tone === 'error') return 'danger';
  if (['info', 'success', 'warning', 'danger', 'neutral'].includes(tone)) return tone;
  return 'info';
};

const triggerBlobDownload = (blob, filename) => {
  const url = window.URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.URL.revokeObjectURL(url);
};

const DEFAULT_WAYPOINT_FORM = {
  latitude: '',
  longitude: '',
  altitude: 100,
  timeFromStart: 0,
  estimatedSpeed: 8,
  heading: 0,
};

const issueMessages = (issues = []) => (issues || []).map((issue) => issue.message || issue.code || String(issue));

const normalizeJobForDialog = (job = {}) => {
  const safeJob = job || {};
  return {
    status: safeJob.status || 'running',
    phase: safeJob.phase || 'processing',
    progressPercent: Number(safeJob.progress_percent ?? safeJob.progressPercent ?? 0),
    message: safeJob.message,
    error: safeJob.error_message || safeJob.error,
  };
};

const createWaypointId = () => `wp-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

const SwarmTrajectory = () => {
  const [leaders, setLeaders] = useState([]);
  const [hierarchies, setHierarchies] = useState({});
  const [followerDetails, setFollowerDetails] = useState({});
  const [uploadedLeaders, setUploadedLeaders] = useState(new Set());
  const [processing, setProcessing] = useState(false);
  const [results, setResults] = useState(null);
  const [status, setStatus] = useState(null);
  const [validation, setValidation] = useState(null);
  const [preview, setPreview] = useState(null);
  const [simulationMode, setSimulationMode] = useState(false);
  const [lightboxImage, setLightboxImage] = useState(null);
  const [committing, setCommitting] = useState(false);
  const [commitProgress, setCommitProgress] = useState(null);
  const [downloadingKML, setDownloadingKML] = useState(false);
  const [kmlProgress, setKmlProgress] = useState(null);
  const [recommendation, setRecommendation] = useState(null);
  const [clearingData, setClearingData] = useState(false);
  const [pageError, setPageError] = useState('');
  const [operatorNotice, setOperatorNotice] = useState(null);
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [processJob, setProcessJob] = useState(null);
  const [processDialogOpen, setProcessDialogOpen] = useState(false);
  const [selectedLeaderId, setSelectedLeaderId] = useState('');
  const [draftWaypoints, setDraftWaypoints] = useState([]);
  const [waypointForm, setWaypointForm] = useState(DEFAULT_WAYPOINT_FORM);
  const [editingWaypointId, setEditingWaypointId] = useState('');
  const [activePanel, setActivePanel] = useState('route');
  const [altitudeMode, setAltitudeMode] = useState(SWARM_TRAJECTORY_ALTITUDE_MODES.MSL);
  const [terrainStatus, setTerrainStatus] = useState({
    status: 'neutral',
    label: 'MSL',
    detail: 'Fixed MSL route authoring.',
  });
  const [uploadingDraft, setUploadingDraft] = useState(false);
  const { data: gcsConfig } = useFetch(GCS_ROUTE_KEYS.gcsConfig);

  useEffect(() => {
    // This screen intentionally boots once, then refreshes from explicit operator actions.
    initializeComponent();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const viewModel = useMemo(
    () => buildSwarmTrajectoryViewModel({
      leaders,
      hierarchies,
      followerDetails,
      uploadedLeaders: Array.from(uploadedLeaders),
      status,
      results,
    }),
    [leaders, hierarchies, followerDetails, uploadedLeaders, status, results],
  );

  const clusterByLeader = useMemo(
    () => new Map(viewModel.clusters.map((cluster) => [Number(cluster.leader_id), cluster])),
    [viewModel.clusters],
  );
  const processedDroneSet = useMemo(() => new Set(viewModel.processedDroneList), [viewModel.processedDroneList]);
  const hasProcessedOutputs = Boolean(status?.has_results || results?.success || viewModel.processedDroneCount > 0);
  const workspaceStatus = useMemo(
    () => buildSwarmTrajectoryWorkspaceStatus({ viewModel, recommendation, hasProcessedOutputs }),
    [viewModel, recommendation, hasProcessedOutputs],
  );
  const workflowStages = useMemo(
    () => buildSwarmTrajectoryStages({ viewModel, recommendation, hasProcessedOutputs }),
    [viewModel, recommendation, hasProcessedOutputs],
  );
  const commitMode = gcsConfig == null
    ? 'unknown'
    : gcsConfig.git_auto_push
      ? 'commit_and_push'
      : 'local_commit';
  const isPartialPackage = viewModel.currentOutcome === 'partial';
  const validationBlockers = issueMessages(validation?.blockers);
  const validationWarnings = issueMessages(validation?.warnings);
  const validationAdvisories = issueMessages(validation?.advisories);
  const validationReady = validation ? Boolean(validation.ready) : hasProcessedOutputs && !isPartialPackage;
  const previewSeries = useMemo(() => (
    (preview?.drones || [])
      .filter((drone) => drone.global_coordinates_available && drone.points?.length)
      .map((drone, index) => ({
        id: drone.drone_id,
        label: `Drone ${drone.drone_id}`,
        role: drone.role,
        color: ROUTE_SKETCH_COLORS[index % ROUTE_SKETCH_COLORS.length],
        points: drone.points,
      }))
  ), [preview]);
  const draftSeries = useMemo(() => [{
    id: 'draft',
    label: 'Draft leader route',
    role: 'leader',
    color: ROUTE_SKETCH_COLORS[0],
    points: draftWaypoints,
  }], [draftWaypoints]);
  const draftRouteErrors = useMemo(() => validateDraftWaypoints(draftWaypoints), [draftWaypoints]);
  const workspaceMetricItems = useMemo(() => [
    {
      key: 'clusters',
      label: 'Clusters',
      value: viewModel.clusterSummary.cluster_count || leaders.length,
      tone: 'info',
    },
    {
      key: 'leader-csvs',
      label: 'Leader CSVs',
      value: viewModel.uploadedLeaderIds.length,
      tone: viewModel.uploadedLeaderIds.length > 0 ? 'success' : 'neutral',
    },
    {
      key: 'ready-clusters',
      label: 'Ready Clusters',
      value: viewModel.clusterSummary.ready_cluster_count,
      tone: viewModel.clusterSummary.ready_cluster_count > 0 ? 'success' : 'neutral',
    },
    {
      key: 'processed-drones',
      label: 'Processed Drones',
      value: viewModel.processedDroneCount,
      tone: viewModel.processedDroneCount > 0 ? 'success' : 'neutral',
    },
  ], [
    leaders.length,
    viewModel.clusterSummary.cluster_count,
    viewModel.clusterSummary.ready_cluster_count,
    viewModel.processedDroneCount,
    viewModel.uploadedLeaderIds.length,
  ]);
  const workflowTabs = useMemo(() => [
    {
      id: 'route',
      label: 'Route',
      meta: `${draftWaypoints.length} WP`,
      Icon: FaPlus,
    },
    {
      id: 'leaders',
      label: 'Leaders',
      meta: `${viewModel.uploadedLeaderIds.length}/${viewModel.expectedLeaderIds.length || leaders.length}`,
      Icon: FaUpload,
    },
    {
      id: 'process',
      label: 'Process',
      meta: `${viewModel.clusterSummary.ready_cluster_count}/${viewModel.clusterSummary.cluster_count || leaders.length}`,
      Icon: FaHourglassHalf,
    },
    {
      id: 'review',
      label: 'Review',
      meta: hasProcessedOutputs ? `${viewModel.processedDroneCount} out` : 'None',
      Icon: FaCheckCircle,
    },
  ], [
    draftWaypoints.length,
    hasProcessedOutputs,
    leaders.length,
    viewModel.clusterSummary.cluster_count,
    viewModel.clusterSummary.ready_cluster_count,
    viewModel.expectedLeaderIds.length,
    viewModel.processedDroneCount,
    viewModel.uploadedLeaderIds.length,
  ]);
  const notify = (tone, title, message = '') => {
    const method = toast[tone] || toast.info;
    method(message ? `${title} — ${message}` : title);
  };

  const showNotice = (tone, title, message, details = []) => {
    setOperatorNotice({ tone, title, message, details });
    notify(tone, title, message);
  };

  const openConfirmDialog = ({
    title,
    summary,
    details = [],
    warning = '',
    confirmLabel = 'Confirm',
    cancelLabel = 'Cancel',
    isDanger = false,
    onConfirm,
  }) => {
    setConfirmDialog({
      title,
      message: buildConfirmMessage({ summary, details, warning }),
      confirmLabel,
      cancelLabel,
      isDanger,
      onConfirm,
    });
  };

  const closeConfirmDialog = () => {
    setConfirmDialog(null);
  };

  const handleConfirmDialog = async () => {
    const action = confirmDialog?.onConfirm;
    closeConfirmDialog();
    if (action) {
      await action();
    }
  };

  const fetchLeaders = async () => {
    try {
      const data = await getSwarmLeaders();

      if (!data.success) {
        throw new Error(data.error || 'Failed to load swarm configuration');
      }

      setLeaders(data.leaders || []);
      setHierarchies(data.hierarchies || {});
      setFollowerDetails(data.follower_details || {});
      setSimulationMode(Boolean(data.simulation_mode));
      setSelectedLeaderId((current) => current || String((data.leaders || [])[0] || ''));
      setPageError('');
    } catch (error) {
      console.error('Error fetching leaders:', error);
      setPageError(error.message || 'Unable to load swarm configuration');
    }
  };

  const fetchStatus = async () => {
    try {
      const data = await getSwarmTrajectoryStatus();

      if (!data.success) {
        throw new Error(data.error || 'Failed to load processing status');
      }

      const nextStatus = data.status;
      const inferredOutcome = nextStatus.cluster_summary?.overall_state === 'partial' ? 'partial' : 'success';

      setStatus(nextStatus);
      setRecommendation(nextStatus.processing_recommendation || null);
      setUploadedLeaders(new Set((nextStatus.uploaded_leaders || []).map(Number)));
      setPageError('');

      setResults((prev) => {
        if (!nextStatus.has_results) {
          return null;
        }

        return {
          success: true,
          outcome: inferredOutcome,
          message: prev?.message
            || (inferredOutcome === 'partial'
              ? 'Some clusters still need attention before launch.'
              : 'All processed swarm trajectory outputs are ready for launch preflight.'),
          processed_drones: nextStatus.processed_trajectories || 0,
          processed_drone_list: nextStatus.processed_drones || [],
          processed_leaders: nextStatus.processed_leaders || [],
          statistics: {
            leaders: nextStatus.leader_count || 0,
            followers: nextStatus.follower_count || 0,
            errors: prev?.statistics?.errors || 0,
          },
          session_id: nextStatus.session?.session_id || prev?.session_id || null,
          missing_leaders: prev?.missing_leaders || [],
          skipped_drone_ids: prev?.skipped_drone_ids || [],
          auto_reloaded: prev?.auto_reloaded || [],
        };
      });

      return nextStatus;
    } catch (error) {
      console.error('Error fetching status:', error);
      setPageError(error.message || 'Unable to load swarm trajectory status');
      return null;
    }
  };

  const fetchValidation = async () => {
    try {
      const data = await getSwarmTrajectoryValidation();
      if (!data.success) {
        throw new Error(data.error || 'Failed to validate trajectory package');
      }
      setValidation(data);
      return data;
    } catch (error) {
      console.error('Validation error:', error);
      setValidation(null);
      return null;
    }
  };

  const fetchPreview = async () => {
    try {
      const data = await getSwarmTrajectoryPreview({ maxPointsPerDrone: 300 });
      if (!data.success) {
        throw new Error(data.error || 'Failed to load trajectory preview');
      }
      setPreview(data);
      return data;
    } catch (error) {
      console.error('Preview error:', error);
      setPreview(null);
      return null;
    }
  };

  const refreshOperationalState = async ({ reloadStructure = false } = {}) => {
    const tasks = [fetchStatus(), fetchValidation(), fetchPreview()];
    if (reloadStructure) {
      tasks.unshift(fetchLeaders());
    }
    await Promise.all(tasks);
  };

  const initializeComponent = async () => {
    await Promise.all([fetchLeaders(), fetchStatus(), fetchValidation(), fetchPreview()]);
  };

  const handleFileUpload = async (leaderId, file) => {
    if (!file) {
      return;
    }

    try {
      const result = await uploadSwarmTrajectory(leaderId, file, file.name);

      if (!result.success) {
        throw new Error(result.error || 'Upload failed');
      }

      setOperatorNotice(null);
      await refreshOperationalState();
      setActivePanel('process');
      showNotice(
        'success',
        `Leader ${leaderId} CSV uploaded`,
        'Review the processing recommendation before launch.',
      );
    } catch (error) {
      console.error('Upload error:', error);
      showNotice('error', `Leader ${leaderId} upload failed`, error.message || 'Upload failed');
    }
  };

  const resetWaypointForm = (nextIndex = draftWaypoints.length) => {
    setWaypointForm({
      ...DEFAULT_WAYPOINT_FORM,
      altitude: altitudeMode === SWARM_TRAJECTORY_ALTITUDE_MODES.AGL ? 100 : 100,
      timeFromStart: nextIndex * 30,
    });
    setEditingWaypointId('');
  };

  const handleWaypointFormChange = (field, value) => {
    setWaypointForm((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const resolveWaypointAltitude = async (waypoint) => {
    if (altitudeMode !== SWARM_TRAJECTORY_ALTITUDE_MODES.AGL) {
      setTerrainStatus({
        status: 'neutral',
        label: 'MSL',
        detail: 'Fixed MSL route authoring.',
      });
      return {
        ...waypoint,
        altitudeReference: 'MSL',
        targetAgl: 0,
        groundElevation: 0,
        terrainAccurate: true,
      };
    }

    const lookup = await getSwarmTrajectoryElevationBatch([{
      id: waypoint.id,
      lat: waypoint.latitude,
      lng: waypoint.longitude,
    }]);
    const results = lookup.results || [];
    setTerrainStatus(buildTerrainStatusFromResults(results));
    const result = results[0];
    if (!result || result.status !== 'ok' || !Number.isFinite(Number(result.elevation_m))) {
      throw new Error(result?.message || 'Terrain elevation is unavailable. Switch to fixed MSL or retry.');
    }

    const targetAgl = Math.max(0, Number(waypoint.altitude) || 0);
    return {
      ...waypoint,
      altitude: Number(result.elevation_m) + targetAgl,
      altitudeReference: 'AGL',
      targetAgl,
      groundElevation: Number(result.elevation_m),
      terrainAccurate: true,
      terrainSource: result.provider || result.source || 'backend',
      terrainConfidence: result.confidence || 'reported',
      terrainSampleTime: result.sample_time || null,
    };
  };

  const saveDraftWaypoint = async () => {
    try {
      const existingIndex = draftWaypoints.findIndex((waypoint) => waypoint.id === editingWaypointId);
      const waypointIndex = existingIndex >= 0 ? existingIndex : draftWaypoints.length;
      const rawWaypoint = {
        id: editingWaypointId || createWaypointId(),
        latitude: toFiniteNumber(waypointForm.latitude),
        longitude: toFiniteNumber(waypointForm.longitude),
        altitude: toFiniteNumber(waypointForm.altitude),
        timeFromStart: toFiniteNumber(waypointForm.timeFromStart, waypointIndex * 30),
        estimatedSpeed: toFiniteNumber(waypointForm.estimatedSpeed, 8),
        preferredSpeed: toFiniteNumber(waypointForm.estimatedSpeed, 8),
        heading: toFiniteNumber(waypointForm.heading, 0),
        calculatedHeading: toFiniteNumber(waypointForm.heading, 0),
      };
      const altitudeResolved = await resolveWaypointAltitude(rawWaypoint);
      const nextWaypoint = normalizeDraftWaypoint(altitudeResolved, waypointIndex);
      const waypointErrors = validateDraftWaypoint(nextWaypoint);
      if (waypointErrors.length) {
        throw new Error(waypointErrors.join(' '));
      }

      setDraftWaypoints((prev) => {
        if (existingIndex >= 0) {
          return prev.map((waypoint) => (waypoint.id === editingWaypointId ? nextWaypoint : waypoint));
        }
        return [...prev, nextWaypoint];
      });
      resetWaypointForm(waypointIndex + 1);
    } catch (error) {
      showNotice('error', 'Waypoint not saved', error.message || 'Check the waypoint fields and terrain state.');
    }
  };

  const addDraftWaypointFromMap = async ({ latitude, longitude }) => {
    try {
      const waypointIndex = draftWaypoints.length;
      const rawWaypoint = {
        id: createWaypointId(),
        latitude: toFiniteNumber(latitude),
        longitude: toFiniteNumber(longitude),
        altitude: toFiniteNumber(waypointForm.altitude, DEFAULT_WAYPOINT_FORM.altitude),
        timeFromStart: waypointIndex * 30,
        estimatedSpeed: toFiniteNumber(waypointForm.estimatedSpeed, DEFAULT_WAYPOINT_FORM.estimatedSpeed),
        heading: toFiniteNumber(waypointForm.heading, DEFAULT_WAYPOINT_FORM.heading),
        headingMode: 'auto',
      };
      const normalized = normalizeDraftWaypoint(rawWaypoint, waypointIndex);
      const errors = validateDraftWaypoint(normalized);
      if (errors.length) {
        throw new Error(errors.join(' '));
      }
      const resolved = await resolveWaypointAltitude(normalized);
      setDraftWaypoints((prev) => [...prev, normalizeDraftWaypoint(resolved, waypointIndex)]);
      setWaypointForm((prev) => ({
        ...prev,
        latitude: '',
        longitude: '',
        timeFromStart: (waypointIndex + 1) * 30,
      }));
      setEditingWaypointId('');
      setOperatorNotice(null);
    } catch (error) {
      showNotice('error', 'Map waypoint not saved', error.message || 'Check terrain state and waypoint policy.');
    }
  };

  const editDraftWaypoint = (waypoint) => {
    setEditingWaypointId(waypoint.id);
    setWaypointForm({
      latitude: waypoint.latitude,
      longitude: waypoint.longitude,
      altitude: waypoint.altitudeReference === 'AGL' ? waypoint.targetAgl : waypoint.altitude,
      timeFromStart: waypoint.timeFromStart,
      estimatedSpeed: waypoint.estimatedSpeed,
      heading: waypoint.heading,
    });
    setAltitudeMode(
      waypoint.altitudeReference === 'AGL'
        ? SWARM_TRAJECTORY_ALTITUDE_MODES.AGL
        : SWARM_TRAJECTORY_ALTITUDE_MODES.MSL
    );
  };

  const deleteDraftWaypoint = (waypointId) => {
    setDraftWaypoints((prev) => prev.filter((waypoint) => waypoint.id !== waypointId));
    if (editingWaypointId === waypointId) {
      resetWaypointForm();
    }
  };

  const moveDraftWaypoint = (waypointId, direction) => {
    setDraftWaypoints((prev) => {
      const index = prev.findIndex((waypoint) => waypoint.id === waypointId);
      const targetIndex = index + direction;
      if (index < 0 || targetIndex < 0 || targetIndex >= prev.length) {
        return prev;
      }
      const next = [...prev];
      const [item] = next.splice(index, 1);
      next.splice(targetIndex, 0, item);
      return next.map((waypoint, waypointIndex) => ({
        ...waypoint,
        name: `WP${waypointIndex + 1}`,
      }));
    });
  };

  const uploadDraftToLeader = async () => {
    if (!selectedLeaderId) {
      showNotice('error', 'Leader not selected', 'Choose a top-level leader before assigning a route.');
      return;
    }
    const errors = validateDraftWaypoints(draftWaypoints);
    if (errors.length) {
      showNotice('error', 'Draft route blocked', errors[0], errors.slice(1));
      return;
    }

    setUploadingDraft(true);
    try {
      await uploadLeaderTrajectoryCsv({
        leaderId: selectedLeaderId,
        waypoints: draftWaypoints,
        buildCsv: buildSwarmLeaderCsv,
        uploadFn: uploadSwarmTrajectory,
      });
      await refreshOperationalState();
      setActivePanel('process');
      showNotice(
        'success',
        `Leader ${selectedLeaderId} route assigned`,
        'Run processing to generate follower paths and validation preview.',
      );
    } catch (error) {
      showNotice('error', 'Route upload failed', error.message || 'Unable to assign leader route');
    } finally {
      setUploadingDraft(false);
    }
  };

  const pollProcessingJob = async (jobId) => {
    const startedAt = Date.now();
    let latestJob = await getSwarmTrajectoryProcessJob(jobId);
    setProcessJob(latestJob);

    while (!['succeeded', 'failed', 'canceled'].includes(latestJob.status)) {
      if (Date.now() - startedAt > 120000) {
        throw new Error('Processing timed out while waiting for job completion. Check backend logs and retry.');
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
      latestJob = await getSwarmTrajectoryProcessJob(jobId);
      setProcessJob(latestJob);
    }

    return latestJob;
  };

  const executeProcessing = async (processingOptions) => {
    setProcessing(true);
    setResults(null);
    setOperatorNotice(null);
    setProcessDialogOpen(true);

    try {
      const createdJob = await createSwarmTrajectoryProcessJob(processingOptions);
      setProcessJob(createdJob);
      const completedJob = await pollProcessingJob(createdJob.job_id);

      if (completedJob.status !== 'succeeded') {
        throw new Error(completedJob.error_message || completedJob.message || 'Processing did not complete.');
      }

      const result = completedJob.result;
      if (!result?.success) {
        throw new Error(completedJob.error_message || completedJob.message || 'Processing finished without a result payload.');
      }

      setResults(result);
      await refreshOperationalState();
      setActivePanel('review');

      if (result.success) {
        const detailLines = [];
        if (result.auto_reloaded?.length) {
          detailLines.push(`Auto-reloaded leaders: ${buildListLabel(result.auto_reloaded)}`);
        }
        if (result.missing_leaders?.length) {
          detailLines.push(`Missing leaders: ${buildListLabel(result.missing_leaders)}`);
        }
        if (result.skipped_drone_ids?.length) {
          detailLines.push(`Missing outputs: ${buildListLabel(result.skipped_drone_ids)}`);
        }

        showNotice(
          result.outcome === 'partial' ? 'warning' : 'success',
          result.outcome === 'partial' ? 'Processing finished with attention items' : 'Formation outputs ready',
          result.message,
          detailLines,
        );
        return;
      }

      showNotice(
        'error',
        'Processing failed',
        result.error || 'Unable to generate swarm trajectory outputs.',
        result.recommendation?.message ? [result.recommendation.message] : [],
      );
    } catch (error) {
      console.error('Processing error:', error);
      showNotice('error', 'Processing failed', error.message || 'Unable to process trajectories');
    } finally {
      setProcessing(false);
    }
  };

  const requestProcessing = async (forceRestart = false) => {
    if (viewModel.uploadedLeaderIds.length === 0) {
      notify('info', 'Upload at least one leader CSV before processing');
      return;
    }

    const latestStatus = await fetchStatus();
    const latestRecommendation = latestStatus?.processing_recommendation || recommendation;
    const processingOptions = {
      auto_reload: true,
      force_clear: Boolean(forceRestart),
    };

    if (forceRestart) {
      openConfirmDialog({
        title: 'Rebuild all cluster outputs?',
        summary: 'This will clear processed outputs and regenerate the entire swarm trajectory package from the current leader uploads.',
        details: [
          `Uploaded leaders: ${buildListLabel(viewModel.uploadedLeaderIds)}`,
          `Expected leaders: ${buildListLabel(viewModel.expectedLeaderIds)}`,
        ],
        warning: 'Use this when cluster assignments changed or when you want a clean processing baseline.',
        confirmLabel: 'Start Fresh',
        isDanger: false,
        onConfirm: () => executeProcessing(processingOptions),
      });
      return;
    }

    if (latestRecommendation?.requires_confirmation) {
      openConfirmDialog({
        title: 'Review processing change set',
        summary: latestRecommendation.message,
        details: latestRecommendation.details || [],
        warning: 'This decision affects the generated follower outputs and readiness state shown to operators.',
        confirmLabel: latestRecommendation.action === 'safe_incremental' ? 'Process' : 'Continue',
        onConfirm: () => executeProcessing(processingOptions),
      });
      return;
    }

    await executeProcessing(processingOptions);
  };

  const cancelProcessing = async () => {
    if (!processJob?.job_id) {
      return;
    }
    try {
      const nextJob = await cancelSwarmTrajectoryProcessJob(processJob.job_id);
      setProcessJob(nextJob);
      showNotice(
        'warning',
        'Processing cancel requested',
        nextJob.message || 'The active processor may finish before cancellation can take effect.',
      );
    } catch (error) {
      showNotice('error', 'Cancel failed', error.message || 'Unable to cancel processing job');
    }
  };

  const handleExplicitClear = async () => {
    openConfirmDialog({
      title: 'Clear processed outputs only?',
      summary: 'This removes generated follower CSVs, plots, and the current processing session, but keeps uploaded leader CSVs.',
      details: [
        `Uploaded leaders stay available: ${buildListLabel(viewModel.uploadedLeaderIds)}`,
        'Use this when you want to keep source leader paths but force a clean reprocess.',
      ],
      warning: 'Processed outputs will disappear from launch preflight until you run processing again.',
      confirmLabel: 'Clear Processed Outputs',
      isDanger: true,
      onConfirm: async () => {
        setClearingData(true);
        try {
          const result = await clearProcessedData();

          if (!result.success) {
            throw new Error(result.error || 'Clear failed');
          }

          setResults(null);
          await refreshOperationalState();
          setActivePanel('process');
          showNotice('success', 'Processed outputs cleared', result.message || 'Processed outputs removed.');
        } catch (error) {
          console.error('Clear error:', error);
          showNotice('error', 'Clear failed', error.message || 'Unable to clear processed outputs');
        } finally {
          setClearingData(false);
        }
      },
    });
  };

  const removeTrajectoryFile = async (leaderId) => {
    const cluster = clusterByLeader.get(Number(leaderId));

    openConfirmDialog({
      title: `Remove leader ${leaderId} upload?`,
      summary: 'This deletes the raw leader CSV and all generated outputs for the cluster tied to this leader.',
      details: [
        `Follower IDs: ${buildListLabel(cluster?.follower_ids || [])}`,
        `Current cluster state: ${getClusterStateMeta(cluster).label}`,
      ],
      warning: 'This action removes both source and processed artifacts for this cluster.',
      confirmLabel: 'Remove Leader CSV',
      isDanger: true,
      onConfirm: async () => {
        try {
          const result = await removeSwarmTrajectoryUpload(leaderId);

          if (!result.success) {
            throw new Error(result.error || 'Remove failed');
          }

          await refreshOperationalState();
          setActivePanel('leaders');
          showNotice('success', `Leader ${leaderId} removed`, result.message || 'Leader CSV removed.');
        } catch (error) {
          console.error('Remove error:', error);
          showNotice('error', `Leader ${leaderId} remove failed`, error.message || 'Unable to remove leader CSV');
        }
      },
    });
  };

  const clearAll = async () => {
    openConfirmDialog({
      title: 'Clear all swarm trajectory artifacts?',
      summary: 'This removes all uploaded leader CSVs, processed follower outputs, plots, and the current processing session.',
      details: [
        `Uploaded leaders: ${buildListLabel(viewModel.uploadedLeaderIds)}`,
        `Processed drones: ${viewModel.processedDroneCount}`,
      ],
      warning: 'Use this only when resetting the entire Swarm Trajectory workspace.',
      confirmLabel: 'Clear Everything',
      isDanger: true,
      onConfirm: async () => {
        try {
          const result = await clearAllSwarmTrajectories();

          if (!result.success) {
            throw new Error(result.error || 'Clear failed');
          }

          setResults(null);
          await refreshOperationalState({ reloadStructure: true });
          setActivePanel('route');
          showNotice('success', 'Swarm trajectory workspace cleared', result.message || 'All files cleared.');
        } catch (error) {
          console.error('Clear error:', error);
          showNotice('error', 'Workspace clear failed', error.message || 'Unable to clear files');
        }
      },
    });
  };

  const downloadDroneTrajectory = async (droneId) => {
    try {
      const blob = await downloadSwarmTrajectoryCsv(droneId);
      triggerBlobDownload(blob, `Drone ${droneId}_trajectory.csv`);
    } catch (error) {
      console.error('Download error:', error);
      notify('error', `Drone ${droneId} CSV download failed`, error.message || 'Unable to download CSV');
    }
  };

  const downloadDroneKML = async (droneId) => {
    try {
      const blob = await downloadSwarmTrajectoryKml(droneId);
      triggerBlobDownload(blob, `Drone ${droneId}_trajectory.kml`);
      notify('success', `Drone ${droneId} KML ready`, 'Open the file in Google Earth or another KML viewer.');
    } catch (error) {
      console.error('KML download error:', error);
      notify('error', `Drone ${droneId} KML download failed`, error.message || 'Unable to download KML');
    }
  };

  const downloadClusterKML = async (leaderId) => {
    try {
      setDownloadingKML(true);
      setKmlProgress({ step: 'Analyzing cluster formation...', progress: 20 });

      const blob = await downloadSwarmClusterKml(leaderId);

      setKmlProgress({ step: 'Generating KML file...', progress: 60 });

      triggerBlobDownload(blob, `Cluster_Leader_${leaderId}.kml`);

      setKmlProgress({ step: 'Download complete', progress: 100 });
      setTimeout(() => {
        setKmlProgress(null);
        notify('success', `Cluster ${leaderId} KML ready`, 'Open the file in Google Earth to review the full cluster path.');
      }, 500);
    } catch (error) {
      console.error('KML download error:', error);
      setKmlProgress(null);
      notify('error', `Cluster ${leaderId} KML download failed`, error.message || 'Unable to download cluster KML');
    } finally {
      setDownloadingKML(false);
    }
  };

  const getFollowersForLeader = (leaderId) => {
    const cluster = clusterByLeader.get(Number(leaderId));
    if (cluster?.follower_ids?.length) {
      return cluster.follower_ids;
    }
    return followerDetails[leaderId] || [];
  };

  const getProcessedFollowersForLeader = (leaderId) => {
    const cluster = clusterByLeader.get(Number(leaderId));
    if (cluster?.processed_follower_ids?.length) {
      return cluster.processed_follower_ids;
    }

    return getFollowersForLeader(leaderId).filter((droneId) => processedDroneSet.has(droneId));
  };

  const clearSingleTrajectory = async (leaderId) => {
    const cluster = clusterByLeader.get(Number(leaderId));

    openConfirmDialog({
      title: `Clear cluster ${leaderId}?`,
      summary: 'This removes the leader CSV and every generated follower output tied to this cluster.',
      details: [
        `Follower IDs: ${buildListLabel(cluster?.follower_ids || [])}`,
        `Processed drones in cluster: ${cluster?.processed_drone_count || 0}`,
      ],
      warning: 'Use this when the cluster assignment or leader path is no longer valid.',
      confirmLabel: 'Clear Cluster',
      isDanger: true,
      onConfirm: async () => {
        try {
          const result = await clearSwarmTrajectoryLeader(leaderId);
          setResults(null);
          await refreshOperationalState();
          showNotice('success', `Cluster ${leaderId} cleared`, result.message || 'Cluster outputs removed.');
        } catch (error) {
          console.error('Clear single trajectory error:', error);
          showNotice('error', `Cluster ${leaderId} clear failed`, error.message || 'Unable to clear cluster');
        }
      },
    });
  };

  const clearIndividualDrone = async (droneId) => {
    openConfirmDialog({
      title: `Remove drone ${droneId} output?`,
      summary: 'This deletes the processed CSV and plot for the selected drone only.',
      details: ['Use this for targeted regeneration when one follower output is known to be invalid.'],
      warning: 'The cluster will remain in a partial-output state until the next processing pass.',
      confirmLabel: 'Remove Output',
      isDanger: true,
      onConfirm: async () => {
        try {
          await clearSwarmTrajectoryDrone(droneId);
          await refreshOperationalState();
          showNotice('success', `Drone ${droneId} output removed`, 'Run processing again to regenerate this output.');
        } catch (error) {
          console.error('Delete drone error:', error);
          showNotice('error', `Drone ${droneId} output removal failed`, error.message || 'Unable to delete output');
        }
      },
    });
  };

  const openLightbox = (imageSrc, title) => {
    setLightboxImage({ src: imageSrc, title });
  };

  const closeLightbox = () => {
    setLightboxImage(null);
  };

  useEffect(() => {
    const handleEscape = (event) => {
      if (event.key === 'Escape' && lightboxImage) {
        closeLightbox();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [lightboxImage]);

  const commitAndPushChanges = async () => {
    if (!hasProcessedOutputs || viewModel.processedDroneCount === 0) {
      notify('info', 'Process the swarm trajectory package before committing');
      return;
    }
    if (!validationReady) {
      showNotice(
        'error',
        'Commit blocked by validation',
        validationBlockers[0] || 'Resolve Swarm Trajectory validation blockers before committing outputs.',
        validationBlockers.slice(1),
      );
      return;
    }

    const isPushMode = commitMode === 'commit_and_push';
    const title = isPushMode ? 'Commit and push mission outputs?' : 'Commit mission outputs locally?';
    const summary = isPushMode
      ? 'This stages the generated cluster outputs, creates a git commit, and pushes the result to the active repository.'
      : 'This stages the generated cluster outputs and creates a local git commit on the GCS. Repository push is disabled for this deployment.';
    const warning = isPushMode
      ? 'Only commit when the plots and readiness summary reflect the exact package you want operators to see in launch preflight.'
      : 'Use this to preserve a traceable local mission package. Launch can still use the current processed outputs even when repository push is disabled.';
    const finalWarning = isPartialPackage
      ? `${warning} Current outputs still have attention items, so do not treat this commit as a full-fleet release package until processing issues are resolved.`
      : warning;
    const confirmLabel = isPushMode ? 'Commit & Push' : 'Commit Locally';

    openConfirmDialog({
      title,
      summary,
      details: [
        `Processed drones: ${viewModel.processedDroneCount}`,
        `Ready clusters: ${viewModel.clusterSummary.ready_cluster_count}/${viewModel.clusterSummary.cluster_count}`,
        `Session: ${viewModel.session.session_id || 'No active processing session'}`,
        validationWarnings.length ? `Warnings: ${validationWarnings.length}` : 'Validation: ready',
      ],
      warning: finalWarning,
      confirmLabel,
      onConfirm: async () => {
        setCommitting(true);
        setCommitProgress({ step: 'Preparing files...', progress: 10 });

        try {
          const progressSteps = isPushMode
            ? [
                { step: 'Staging trajectory outputs...', progress: 25 },
                { step: 'Creating git commit...', progress: 50 },
                { step: 'Pushing to repository...', progress: 75 },
                { step: 'Finalizing...', progress: 90 },
              ]
            : [
                { step: 'Staging trajectory outputs...', progress: 35 },
                { step: 'Creating local git commit...', progress: 70 },
                { step: 'Finalizing...', progress: 90 },
              ];

          for (const progressStep of progressSteps) {
            setCommitProgress(progressStep);
            await new Promise((resolve) => setTimeout(resolve, 500));
          }

          const data = await commitSwarmTrajectoryOutputs(
            `Swarm trajectory update: ${viewModel.processedDroneCount} drones processed - ${new Date().toISOString().split('T')[0]}`
          );

          if (!data.success) {
            throw new Error(data.error || 'Commit failed');
          }

          setCommitProgress({ step: 'Complete', progress: 100 });
          setTimeout(() => {
            setCommitProgress(null);
            showNotice(
              'success',
              isPushMode ? 'Swarm trajectory outputs committed and pushed' : 'Swarm trajectory outputs committed locally',
              data.git_info?.message || data.message || 'Mission outputs were recorded successfully.',
            );
          }, 500);
        } catch (error) {
          console.error('Commit error:', error);
          setCommitProgress(null);
          showNotice('error', 'Commit failed', error.message || 'Unable to commit trajectory outputs');
        } finally {
          setCommitting(false);
        }
      },
    });
  };

  return (
    <div className="swarm-trajectory">
      <div className="swarm-trajectory__header">
        <div className="title-section">
          <h1>Swarm Trajectory Mission</h1>
          <p className="subtitle">
            Leader paths → follower outputs → launch package.
          </p>
        </div>
        <div className="swarm-trajectory__header-tools">
          <StatusBadge tone={simulationMode ? 'info' : 'success'}>
            {simulationMode ? 'SIM' : 'LIVE'}
          </StatusBadge>
          <DocsLink route="/swarm-trajectory" compact />
        </div>
      </div>

      <div className="status-card status-card--compact">
        <MetricStrip
          items={workspaceMetricItems}
          label="Swarm trajectory workspace status"
          className="swarm-trajectory__metric-strip"
        />

        {pageError ? (
          <OperatorNotice tone="danger" title="Status load failed" role="alert" className="swarm-trajectory__notice">
            {pageError}
          </OperatorNotice>
        ) : null}

        {operatorNotice ? (
          <OperatorNotice
            tone={normalizeNoticeTone(operatorNotice.tone)}
            title={operatorNotice.title}
            role={normalizeNoticeTone(operatorNotice.tone) === 'danger' ? 'alert' : 'status'}
            className="swarm-trajectory__notice"
            action={(
              <button
                type="button"
                className="operator-button operator-button--ghost"
                onClick={() => setOperatorNotice(null)}
              >
                Dismiss
              </button>
            )}
          >
            {operatorNotice.message ? <span>{operatorNotice.message}</span> : null}
              {operatorNotice.details?.length ? (
                <ul className="swarm-status-banner__details">
                  {operatorNotice.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              ) : null}
          </OperatorNotice>
        ) : null}

        <details className="swarm-status-details">
          <summary>
            <span>Workspace review & policy</span>
            <small>Status, doctrine, and links</small>
          </summary>
          <SwarmTrajectoryWorkspaceSummary
            workspaceStatus={workspaceStatus}
            stages={workflowStages}
            session={viewModel.session}
            compact={false}
          />
        </details>
      </div>

      {leaders.length > 0 ? (
        <>
          <div className="swarm-workflow-tabs" role="tablist" aria-label="Swarm trajectory workflow">
            {workflowTabs.map(({ id, label, meta, Icon }) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={activePanel === id}
                className={`swarm-workflow-tab ${activePanel === id ? 'is-active' : ''}`}
                onClick={() => setActivePanel(id)}
              >
                <Icon aria-hidden="true" />
                <span>{label}</span>
                <small>{meta}</small>
              </button>
            ))}
          </div>

          <div className={`workflow-step workflow-step--planner swarm-panel ${activePanel === 'route' ? 'is-active' : ''}`} hidden={activePanel !== 'route'}>
            <div className="step-header">
              <h3><span className="step-number">1</span>Route</h3>
            </div>

            <SwarmRouteMapEditor
              waypoints={draftWaypoints}
              onAddWaypoint={addDraftWaypointFromMap}
              altitudeLabel={altitudeMode === SWARM_TRAJECTORY_ALTITUDE_MODES.AGL ? 'AGL terrain' : 'Fixed MSL'}
            />

            <div className="swarm-planner-grid">
              <section className="swarm-planner-card" aria-label="Leader route waypoint editor">
                <div className="swarm-planner-card__header">
                  <div>
                    <strong>Draft leader path</strong>
                    <span>{draftWaypoints.length} waypoint{draftWaypoints.length === 1 ? '' : 's'}</span>
                  </div>
                  <select
                    value={selectedLeaderId}
                    onChange={(event) => setSelectedLeaderId(event.target.value)}
                    aria-label="Leader route assignment"
                  >
                    {leaders.map((leaderId) => (
                      <option key={leaderId} value={leaderId}>Leader {leaderId}</option>
                    ))}
                  </select>
                </div>

                <div className="swarm-waypoint-form">
                  <label>
                    <span>Latitude</span>
                    <input
                      type="number"
                      step="0.000001"
                      value={waypointForm.latitude}
                      onChange={(event) => handleWaypointFormChange('latitude', event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Longitude</span>
                    <input
                      type="number"
                      step="0.000001"
                      value={waypointForm.longitude}
                      onChange={(event) => handleWaypointFormChange('longitude', event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Time</span>
                    <input
                      type="number"
                      min="0"
                      step="1"
                      value={waypointForm.timeFromStart}
                      onChange={(event) => handleWaypointFormChange('timeFromStart', event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Speed</span>
                    <input
                      type="number"
                      min="0.5"
                      step="0.1"
                      value={waypointForm.estimatedSpeed}
                      onChange={(event) => handleWaypointFormChange('estimatedSpeed', event.target.value)}
                    />
                  </label>
                  <label>
                    <span>Heading</span>
                    <input
                      type="number"
                      min="0"
                      max="360"
                      step="1"
                      value={waypointForm.heading}
                      onChange={(event) => handleWaypointFormChange('heading', event.target.value)}
                    />
                  </label>
                </div>

                <MissionAltitudeControl
                  mode={altitudeMode}
                  valueM={waypointForm.altitude}
                  onModeChange={(mode) => setAltitudeMode(
                    mode === SWARM_TRAJECTORY_ALTITUDE_MODES.IMPORTED
                      ? SWARM_TRAJECTORY_ALTITUDE_MODES.MSL
                      : mode
                  )}
                  onValueChange={(value) => handleWaypointFormChange('altitude', value)}
                  terrainStatus={terrainStatus}
                />

                <div className="swarm-planner-actions">
                  <button type="button" className="utility-btn commit" onClick={saveDraftWaypoint}>
                    <FaPlus aria-hidden="true" />
                    {editingWaypointId ? 'Save Waypoint' : 'Add Waypoint'}
                  </button>
                  <button type="button" className="utility-btn" onClick={() => resetWaypointForm()}>
                    Reset Form
                  </button>
                  <button
                    type="button"
                    className="utility-btn"
                    onClick={uploadDraftToLeader}
                    disabled={uploadingDraft || draftRouteErrors.length > 0}
                  >
                    <FaUpload aria-hidden="true" />
                    {uploadingDraft ? 'Assigning...' : 'Assign to Leader'}
                  </button>
                </div>

                {draftWaypoints.length > 0 && draftRouteErrors.length ? (
                  <OperatorNotice tone="warning" title="Draft route needs attention" className="swarm-planner-card__notice">
                    {draftRouteErrors[0]}
                  </OperatorNotice>
                ) : null}
              </section>

              <section className="swarm-planner-card" aria-label="Leader route preview">
                <div className="swarm-planner-card__header">
                  <div>
                    <strong>2D route preview</strong>
                    <span>{altitudeMode === SWARM_TRAJECTORY_ALTITUDE_MODES.AGL ? 'AGL with terrain lookup' : 'Fixed MSL'}</span>
                  </div>
                  <StatusBadge tone={draftRouteErrors.length ? 'warning' : 'success'}>
                    {draftRouteErrors.length ? 'Draft' : 'Ready'}
                  </StatusBadge>
                </div>
                <RouteSketch series={draftSeries} emptyLabel="Add waypoints to preview the leader path" />
                <div className="swarm-waypoint-list" role="list" aria-label="Draft waypoints">
                  {draftWaypoints.map((waypoint, index) => (
                    <div key={waypoint.id} className="swarm-waypoint-row" role="listitem">
                      <button type="button" className="swarm-waypoint-row__main" onClick={() => editDraftWaypoint(waypoint)}>
                        <strong>{index + 1}. {waypoint.name}</strong>
                        <span>
                          {waypoint.latitude.toFixed(5)}, {waypoint.longitude.toFixed(5)} · {waypoint.altitude.toFixed(0)} m MSL
                        </span>
                      </button>
                      <div className="swarm-waypoint-row__actions">
                        <button type="button" onClick={() => moveDraftWaypoint(waypoint.id, -1)} disabled={index === 0} aria-label={`Move waypoint ${index + 1} up`}>
                          <FaArrowUp aria-hidden="true" />
                        </button>
                        <button type="button" onClick={() => moveDraftWaypoint(waypoint.id, 1)} disabled={index === draftWaypoints.length - 1} aria-label={`Move waypoint ${index + 1} down`}>
                          <FaArrowDown aria-hidden="true" />
                        </button>
                        <button type="button" onClick={() => deleteDraftWaypoint(waypoint.id)} aria-label={`Delete waypoint ${index + 1}`}>
                          <FaTrashAlt aria-hidden="true" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </section>
            </div>
          </div>

          <div className={`workflow-step swarm-panel ${activePanel === 'leaders' ? 'is-active' : ''}`} hidden={activePanel !== 'leaders'}>
            <div className="step-header">
              <h3><span className="step-number">2</span>Leaders</h3>
            </div>

            <div className="leaders-grid">
              {viewModel.clusters.map((cluster) => {
                const leaderId = Number(cluster.leader_id);
                const stateMeta = getClusterStateMeta(cluster);
                const followerIds = cluster.follower_ids || getFollowersForLeader(leaderId);
                const stateClass = stateMeta.tone === 'warning' ? 'attention' : stateMeta.tone;

                return (
                  <div
                    key={leaderId}
                    className={`leader-card leader-card--${stateClass} ${cluster.ready ? 'completed' : cluster.leader_uploaded ? 'uploaded' : 'pending'}`}
                  >
                    <div className="leader-header">
                      <div>
                        <h4>Leader {leaderId}</h4>
                        <p className="leader-subtext">
                          Followers: {followerIds.length > 0 ? followerIds.join(', ') : 'None'}
                        </p>
                      </div>
                      <span className={`leader-state-badge ${stateClass}`}>{stateMeta.label}</span>
                    </div>

                    <p className="leader-card__summary">{stateMeta.summary}</p>

                    <div className="leader-metrics">
                      <div className="leader-metric">
                        <strong>{cluster.expected_drone_count || 1 + (cluster.follower_count || 0)}</strong>
                        <span>Expected</span>
                      </div>
                      <div className="leader-metric">
                        <strong>{cluster.processed_drone_count || 0}</strong>
                        <span>Processed</span>
                      </div>
                      <div className="leader-metric">
                        <strong>{cluster.follower_count || followerIds.length}</strong>
                        <span>Followers</span>
                      </div>
                    </div>

                    {(cluster.issues?.length || cluster.advisories?.length) ? (
                      <div className="leader-flags">
                        {(cluster.issues || []).map((issue) => (
                          <span key={issue} className="leader-flag leader-flag--issue">{issue}</span>
                        ))}
                        {(cluster.advisories || []).map((advisory) => (
                          <span key={advisory} className="leader-flag leader-flag--advisory">{advisory}</span>
                        ))}
                      </div>
                    ) : null}

                    <div className="upload-area">
                      <input
                        type="file"
                        accept=".csv"
                        onChange={(event) => {
                          const file = event.target.files?.[0];
                          if (file) {
                            handleFileUpload(leaderId, file);
                          }
                          event.target.value = '';
                        }}
                        id={`file-${leaderId}`}
                        className="swarm-trajectory-file-input"
                      />
                      <div className="upload-controls">
                        <label htmlFor={`file-${leaderId}`} className="upload-btn">
                          {cluster.leader_uploaded ? 'Replace Leader CSV' : 'Upload Leader CSV'}
                        </label>

                        {cluster.leader_uploaded ? (
                          <button
                            className="remove-btn"
                            onClick={() => removeTrajectoryFile(leaderId)}
                            aria-label={`Remove leader ${leaderId} CSV and related outputs`}
                          >
                            Remove Leader CSV
                          </button>
                        ) : null}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className={`workflow-step swarm-panel ${activePanel === 'process' ? 'is-active' : ''}`} hidden={activePanel !== 'process'}>
            <div className="step-header">
              <h3><span className="step-number">3</span>Process</h3>
            </div>

            <div className="process-summary">
              <div className="process-summary__item">
                <strong>{viewModel.clusterSummary.ready_cluster_count}/{viewModel.clusterSummary.cluster_count || leaders.length}</strong>
                <span>Ready clusters</span>
              </div>
              <div className="process-summary__item">
                <strong>{viewModel.clusterSummary.needs_processing_cluster_count}</strong>
                <span>Need processing</span>
              </div>
              <div className="process-summary__item">
                <strong>{viewModel.clusterSummary.partial_output_cluster_count}</strong>
                <span>Partial outputs</span>
              </div>
              <div className="process-summary__item">
                <strong>{viewModel.missingLeaderIds.length}</strong>
                <span>Missing leader CSVs</span>
              </div>
            </div>

            {recommendation ? (
              <div className={`processing-recommendation ${formatRecommendationTone(recommendation.action)}`}>
                <div className="recommendation-header">
                  <span className="recommendation-title">{recommendation.message}</span>
                </div>

                {recommendation.details?.length ? (
                  <div className="recommendation-details">
                    {recommendation.details.map((detail) => (
                      <div key={detail} className="recommendation-detail">• {detail}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}

            <div className="process-controls">
              <button
                className={`process-btn ${processing ? 'processing' : ''} ${viewModel.uploadedLeaderIds.length === 0 ? 'disabled' : ''}`}
                onClick={() => requestProcessing(false)}
                disabled={processing || viewModel.uploadedLeaderIds.length === 0}
              >
                {processing ? (
                  <>
                    <span className="spinner"></span>
                    Processing Cluster Outputs...
                  </>
                ) : (
                  recommendation?.action === 'safe_incremental'
                    ? 'Process Current Uploads'
                    : 'Process Swarm Trajectory Package'
                )}
              </button>

              {viewModel.uploadedLeaderIds.length === 0 ? (
                <p className="requirement-note">Upload at least one leader CSV before processing.</p>
              ) : (
                <p className="requirement-note requirement-note--soft">Ready to process current leader uploads.</p>
              )}

              {viewModel.uploadedLeaderIds.length > 0 ? (
                <details className="swarm-advanced-actions">
                  <summary>Advanced processing</summary>
                  <div className="advanced-processing-options">
                    <button
                      className="process-option-btn secondary"
                      onClick={() => requestProcessing(true)}
                      disabled={processing}
                    >
                      Start Fresh
                    </button>

                    <button
                      className="process-option-btn tertiary"
                      onClick={handleExplicitClear}
                      disabled={clearingData}
                    >
                      {clearingData ? 'Clearing...' : 'Clear Processed Only'}
                    </button>
                  </div>
                </details>
              ) : null}
            </div>
          </div>

          {hasProcessedOutputs ? (
          <div className={`workflow-step swarm-panel ${activePanel === 'review' ? 'is-active' : ''}`} hidden={activePanel !== 'review'}>
            <div className="step-header">
              <h3><span className="step-number">4</span>Review and Prepare Launch</h3>
            </div>

              <div className={`success-card ${viewModel.currentOutcome === 'partial' ? 'success-card--warning' : ''}`}>
                <div className="success-header">
                  <span className="success-icon" aria-hidden="true">
                    {viewModel.currentOutcome === 'partial' ? <FaExclamationTriangle /> : <FaCheckCircle />}
                  </span>
                  <div>
                    <h4>
                      {viewModel.currentOutcome === 'partial'
                        ? 'Outputs generated, review still required'
                        : 'Mission outputs ready for launch preflight'}
                    </h4>
                    <p>
                      {viewModel.processedDroneCount} drone output{viewModel.processedDroneCount === 1 ? '' : 's'} available across{' '}
                      {viewModel.clusterSummary.processed_cluster_count} processed cluster{viewModel.clusterSummary.processed_cluster_count === 1 ? '' : 's'}.
                    </p>
                  </div>
                </div>

                <div className="processing-stats">
                  <div className="stat">
                    <span className="stat-value">{status?.leader_count || results?.statistics?.leaders || 0}</span>
                    <span className="stat-label">Leaders</span>
                  </div>
                  <div className="stat">
                    <span className="stat-value">{status?.follower_count || results?.statistics?.followers || 0}</span>
                    <span className="stat-label">Followers</span>
                  </div>
                  <div className="stat">
                    <span className="stat-value">{viewModel.clusterSummary.ready_cluster_count}</span>
                    <span className="stat-label">Ready Clusters</span>
                  </div>
                  {(viewModel.issueCount > 0 || viewModel.advisoryCount > 0) ? (
                    <div className="stat error">
                      <span className="stat-value">{viewModel.issueCount + viewModel.advisoryCount}</span>
                      <span className="stat-label">Attention Items</span>
                    </div>
                  ) : null}
                </div>

                <div className="swarm-validation-panel">
                  <div className="swarm-validation-panel__header">
                    <strong>Validation</strong>
                    <StatusBadge tone={validationReady ? 'success' : 'danger'}>
                      {validationReady ? 'Ready' : 'Blocked'}
                    </StatusBadge>
                  </div>
                  {validationBlockers.length ? (
                    <OperatorNotice tone="danger" title="Commit/transfer blockers">
                      <ul>
                        {validationBlockers.map((blocker) => <li key={blocker}>{blocker}</li>)}
                      </ul>
                    </OperatorNotice>
                  ) : null}
                  {validationWarnings.length ? (
                    <OperatorNotice tone="warning" title="Operator review">
                      <ul>
                        {validationWarnings.map((warning) => <li key={warning}>{warning}</li>)}
                      </ul>
                    </OperatorNotice>
                  ) : null}
                  {!validationBlockers.length && !validationWarnings.length && validationAdvisories.length ? (
                    <div className="swarm-validation-panel__advisories">
                      {validationAdvisories.map((advisory) => <span key={advisory}>{advisory}</span>)}
                    </div>
                  ) : null}
                </div>

                <div className="swarm-processed-preview">
                  <div className="swarm-processed-preview__header">
                    <strong>Leader/follower preview</strong>
                    <span>{previewSeries.length} path{previewSeries.length === 1 ? '' : 's'} with global coordinates</span>
                  </div>
                  <RouteSketch series={previewSeries} emptyLabel="Processed global preview is unavailable" />
                  <div className="swarm-preview-legend">
                    {(preview?.drones || []).slice(0, 12).map((drone, index) => (
                      <span key={drone.drone_id}>
                        <i style={{ backgroundColor: ROUTE_SKETCH_COLORS[index % ROUTE_SKETCH_COLORS.length] }} />
                        Drone {drone.drone_id} · {drone.role}
                        {drone.direct_leader_id ? ` → ${drone.direct_leader_id}` : ''}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="next-steps">
                  <p>
                    <strong>Next:</strong>{' '}
                    {isPartialPackage
                      ? 'Resolve attention items and reprocess, or launch only an intentional selected subset after Dashboard preflight.'
                      : 'Review preview, optionally commit for traceability, then use Dashboard Mission Type 4 preflight.'}
                  </p>
                </div>

                <div className="review-actions">
                  <button className="utility-btn commit" onClick={commitAndPushChanges} disabled={committing || !validationReady}>
                    {committing
                      ? 'Saving...'
                      : commitMode === 'local_commit'
                        ? 'Commit Outputs Locally'
                        : commitMode === 'commit_and_push'
                          ? 'Commit & Push Outputs'
                          : 'Commit Mission Outputs'}
                  </button>
                  <Link className="utility-btn" to="/">
                    Open Mission Trigger
                  </Link>
                </div>

                <div className="advanced-section">
                  <details className="trajectory-preview">
                    <summary className="preview-toggle">
                      Review processed cluster plots and downloads
                    </summary>

                    <div className="preview-content">
                      {viewModel.clusters
                        .filter((cluster) => viewModel.visibleClusterLeaders.includes(Number(cluster.leader_id)))
                        .map((cluster) => {
                          const leaderId = Number(cluster.leader_id);
                          const stateMeta = getClusterStateMeta(cluster);

                          return (
                            <div key={leaderId} className="cluster-section">
                              <div className="cluster-header">
                                <div>
                                  <h4>Cluster {leaderId}</h4>
                                  <div className="cluster-header__meta">
                                    <span>{cluster.expected_drone_count || 1 + (cluster.follower_count || 0)} drones total</span>
                                    <span className={`leader-state-badge ${stateMeta.tone === 'warning' ? 'attention' : stateMeta.tone}`}>
                                      {stateMeta.label}
                                    </span>
                                  </div>
                                </div>
                                <span className="cluster-stats">
                                  {cluster.processed_drone_count || 0} processed
                                </span>
                              </div>

                              {cluster.missing_follower_ids?.length ? (
                                <div className="cluster-warning">
                                  Missing follower outputs: {cluster.missing_follower_ids.join(', ')}
                                </div>
                              ) : null}

                              <div className="cluster-plot-section">
                                <div className="cluster-plot-card">
                                  <div className="cluster-plot-header">
                                    <div className="plot-header-left">
                                      <h5>Cluster review plot</h5>
                                      <p className="plot-description">Combined leader and follower trajectories for this cluster.</p>
                                    </div>
                                    <div className="plot-header-actions">
                                      <button
                                        className={`cluster-kml-btn ${downloadingKML ? 'loading' : ''}`}
                                        onClick={() => downloadClusterKML(leaderId)}
                                        disabled={downloadingKML}
                                        aria-label={`Download cluster ${leaderId} KML file`}
                                      >
                                        {downloadingKML ? (
                                          <>
                                            <span className="btn-icon spinner" aria-hidden="true"><FaHourglassHalf /></span>
                                            <div className="btn-content">
                                              <span className="btn-text">Generating...</span>
                                              <span className="btn-subtitle">Please wait</span>
                                            </div>
                                          </>
                                        ) : (
                                          <>
                                            <span className="btn-icon" aria-hidden="true"><FaGlobeAmericas /></span>
                                            <div className="btn-content">
                                              <span className="btn-text">Cluster KML</span>
                                              <span className="btn-subtitle">Google Earth</span>
                                            </div>
                                          </>
                                        )}
                                      </button>
                                    </div>
                                  </div>
                                  <div
                                    className="cluster-plot clickable"
                                    onClick={() => openLightbox(buildSwarmTrajectoryPlotUrl(`cluster_leader_${leaderId}.jpg`), `Cluster ${leaderId} Formation`)}
                                  >
                                    <img
                                      src={buildSwarmTrajectoryPlotUrl(`cluster_leader_${leaderId}.jpg`)}
                                      alt={`Cluster ${leaderId} formation trajectories`}
                                      onError={(event) => {
                                        event.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="100%" height="100%" fill="%23f8fafc"/><text x="50%" y="50%" font-family="Arial" font-size="16" fill="%23667eea" text-anchor="middle">Cluster Formation Plot</text></svg>';
                                      }}
                                    />
                                    <div className="zoom-overlay">
                                      <span className="zoom-icon" aria-hidden="true"><FaSearchPlus /></span>
                                      <span>Click to enlarge</span>
                                    </div>
                                  </div>
                                  <div className="cluster-features">
                                    <div className="feature-item">
                                      <span className="feature-text">Combined path review</span>
                                    </div>
                                    <div className="feature-item">
                                      <span className="feature-text">Cluster terrain export</span>
                                    </div>
                                    <div className="feature-item">
                                      <span className="feature-text">Mission validation artifact</span>
                                    </div>
                                  </div>
                                </div>
                              </div>

                              <div className="individual-drones-section">
                                <h5 className="section-title">Individual drone outputs</h5>
                                <div className="drones-grid">
                                  <div className="drone-preview-card">
                                    <div className="preview-header">
                                      <h6>Drone {leaderId}</h6>
                                      <div className="header-actions">
                                        <span className="drone-type-badge leader">LEADER</span>
                                      </div>
                                    </div>

                                    <div
                                      className="preview-plot clickable"
                                      onClick={() => openLightbox(buildSwarmTrajectoryPlotUrl(`drone_${leaderId}_trajectory.jpg`), `Drone ${leaderId} Trajectory`)}
                                    >
                                      <img
                                        src={buildSwarmTrajectoryPlotUrl(`drone_${leaderId}_trajectory.jpg`)}
                                        alt={`Drone ${leaderId} trajectory`}
                                        onError={(event) => {
                                          event.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect width="100%" height="100%" fill="%23f0f0f0"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="%23666" text-anchor="middle">Plot Loading...</text></svg>';
                                        }}
                                      />
                                      <div className="zoom-overlay">
                                        <span className="zoom-icon" aria-hidden="true"><FaSearchPlus /></span>
                                      </div>
                                    </div>

                                    <div className="preview-actions">
                                      <button className="preview-btn download" onClick={() => downloadDroneTrajectory(leaderId)} aria-label={`Download drone ${leaderId} CSV`}>
                                        CSV
                                      </button>
                                      <button className="preview-btn kml" onClick={() => downloadDroneKML(leaderId)} aria-label={`Download drone ${leaderId} KML`}>
                                        KML
                                      </button>
                                      <button className="preview-btn clear-single" onClick={() => clearSingleTrajectory(leaderId)} aria-label={`Clear cluster ${leaderId} outputs`}>
                                        Clear Cluster
                                      </button>
                                    </div>
                                  </div>

                                  {getProcessedFollowersForLeader(leaderId).map((followerId) => (
                                    <div key={followerId} className="drone-preview-card">
                                      <div className="preview-header">
                                        <h6>Drone {followerId}</h6>
                                        <div className="header-actions">
                                          <span className="drone-type-badge follower">FOLLOWER</span>
                                          <button
                                            type="button"
                                            className="delete-drone-btn"
                                            onClick={() => clearIndividualDrone(followerId)}
                                            aria-label={`Delete drone ${followerId} output`}
                                          >
                                            <FaTrashAlt aria-hidden="true" />
                                          </button>
                                        </div>
                                      </div>

                                      <div
                                        className="preview-plot clickable"
                                        onClick={() => openLightbox(buildSwarmTrajectoryPlotUrl(`drone_${followerId}_trajectory.jpg`), `Drone ${followerId} Trajectory`)}
                                      >
                                        <img
                                          src={buildSwarmTrajectoryPlotUrl(`drone_${followerId}_trajectory.jpg`)}
                                          alt={`Drone ${followerId} trajectory`}
                                          onError={(event) => {
                                            event.target.src = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150"><rect width="100%" height="100%" fill="%23f7fafc"/><text x="50%" y="50%" font-family="Arial" font-size="14" fill="%2338a169" text-anchor="middle">Follower Plot</text></svg>';
                                          }}
                                        />
                                        <div className="zoom-overlay">
                                          <span className="zoom-icon" aria-hidden="true"><FaSearchPlus /></span>
                                        </div>
                                      </div>

                                      <div className="preview-actions">
                                        <button className="preview-btn download" onClick={() => downloadDroneTrajectory(followerId)} aria-label={`Download drone ${followerId} CSV`}>
                                          CSV
                                        </button>
                                        <button className="preview-btn kml" onClick={() => downloadDroneKML(followerId)} aria-label={`Download drone ${followerId} KML`}>
                                          KML
                                        </button>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </details>
                </div>
              </div>
            </div>
          ) : null}

          {!hasProcessedOutputs && activePanel === 'review' ? (
            <div className="workflow-step swarm-panel is-active">
              <div className="step-header">
                <h3><span className="step-number">4</span>Review</h3>
              </div>
              <div className="swarm-empty-panel">
                <FaCheckCircle aria-hidden="true" />
                <strong>No package yet</strong>
                <span>Assign a leader route, process outputs, then review the launch package.</span>
              </div>
            </div>
          ) : null}

          <div className="utility-actions">
            <button className="utility-btn" onClick={() => refreshOperationalState({ reloadStructure: true })}>
              Refresh Status
            </button>

            <details className="swarm-advanced-actions swarm-advanced-actions--inline">
              <summary>Advanced</summary>
              <button className="utility-btn danger" onClick={clearAll}>
                Clear Workspace
              </button>
            </details>
          </div>
        </>
      ) : (
        <div className="empty-state">
          <div className="empty-icon" aria-hidden="true"><FaRobot /></div>
          <h3>No clusters found</h3>
          <p>
            Configure top leaders in <Link to="/swarm-design" className="guide-link">Swarm Design</Link> before using this workflow.
          </p>
          <button className="utility-btn" onClick={() => refreshOperationalState({ reloadStructure: true })}>
            Reload Configuration
          </button>
        </div>
      )}

      {lightboxImage ? (
        <div className="lightbox-overlay" onClick={closeLightbox}>
          <div className="lightbox-container" onClick={(event) => event.stopPropagation()}>
            <div className="lightbox-header">
              <h3>{lightboxImage.title}</h3>
              <button className="lightbox-close" onClick={closeLightbox} aria-label="Close plot preview">
                <FaTimes aria-hidden="true" />
              </button>
            </div>
            <div className="lightbox-content">
              <img
                src={lightboxImage.src}
                alt={lightboxImage.title}
                className="lightbox-image"
              />
            </div>
            <div className="lightbox-footer">
              <span className="lightbox-hint">Click outside or press ESC to close</span>
            </div>
          </div>
        </div>
      ) : null}

      {commitProgress ? (
        <div className="progress-overlay">
          <div className="progress-modal">
            <div className="progress-header">
              <h3>Committing Changes</h3>
              <div className="progress-subtitle">
                Syncing processed swarm trajectory outputs with the repository
              </div>
            </div>

            <div className="progress-content">
              <div className="progress-bar-container">
                <div
                  className="progress-bar-fill"
                  style={{ '--progress-percent': `${commitProgress.progress}%` }}
                ></div>
              </div>

              <div className="progress-step">
                {commitProgress.step}
              </div>

              <div className="progress-percentage">
                {commitProgress.progress}%
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {kmlProgress ? (
        <div className="progress-overlay">
          <div className="progress-modal">
            <div className="progress-header">
              <h3>Generating KML</h3>
              <div className="progress-subtitle">
                Preparing a 3D review artifact for terrain inspection
              </div>
            </div>

            <div className="progress-content">
              <div className="progress-bar-container">
                <div
                  className="progress-bar-fill"
                  style={{ '--progress-percent': `${kmlProgress.progress}%` }}
                ></div>
              </div>

              <div className="progress-step">
                {kmlProgress.step}
              </div>

              <div className="progress-percentage">
                {kmlProgress.progress}%
              </div>
            </div>
          </div>
        </div>
      ) : null}

      <MissionJobProgressDialog
        open={processDialogOpen}
        title="Processing swarm trajectories"
        job={normalizeJobForDialog(processJob)}
        onCancel={processing ? cancelProcessing : null}
        onRetry={processJob?.status === 'failed' ? () => requestProcessing(false) : null}
        onClose={() => setProcessDialogOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || 'Confirm'}
        message={confirmDialog?.message || ''}
        confirmLabel={confirmDialog?.confirmLabel || 'Confirm'}
        cancelLabel={confirmDialog?.cancelLabel || 'Cancel'}
        tone={confirmDialog?.isDanger ? 'danger' : 'neutral'}
        onConfirm={handleConfirmDialog}
        onCancel={closeConfirmDialog}
      />
    </div>
  );
};

export default SwarmTrajectory;
