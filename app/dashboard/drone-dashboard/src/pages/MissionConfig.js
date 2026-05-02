// src/pages/MissionConfig.js

import React, { useState, useEffect, useMemo, useRef } from 'react';
import '../styles/MissionConfig.css';
import { useNavigate, useSearchParams } from 'react-router-dom';

// Components
import PositionTabs from '../components/PositionTabs';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import MissionLayout from '../components/MissionLayout';
import OriginModal from '../components/OriginModal';
import DronePositionMap from '../components/DronePositionMap';
import SaveReviewDialog from '../components/SaveReviewDialog';
import MissionConfigAlertStack from '../components/missionConfig/MissionConfigAlertStack';
import PendingEnrollmentPanel from '../components/missionConfig/PendingEnrollmentPanel';
import MissionConfigToolbar from '../components/missionConfig/MissionConfigToolbar';

// Hooks
import useFetch from '../hooks/useFetch';
import { useNormalizedTelemetry } from '../hooks/useNormalizedTelemetry';

// Utilities
import {
  handleSaveChangesToServer,
  handleRevertChanges,
  handleFileChange,
  exportConfigJSON,
  exportConfigCSV,
  validateConfigWithBackend,
} from '../utilities/missionConfigUtilities';
import {
  DRONE_SEARCH_PLACEHOLDER,
  matchesDroneSearchQuery,
} from '../utilities/dronePresentation';
import {
  buildSuggestedHwIds,
  compareMissionIds,
  formatDroneLabel,
  formatShowSlotLabel,
  getDuplicateAssignments,
  getOnlineDroneCount,
  getRoleSwaps,
  normalizeComparableId,
  normalizeDroneConfigData,
  normalizeDroneConfigEntry,
} from '../utilities/missionIdentityUtils';
import { buildMissionSlotStatusPresentation } from '../utilities/missionSlotStatus';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  filterClustersByScope,
} from '../utilities/swarmDesignUtils';
import { toast } from 'react-toastify';
import {
  GCS_ROUTE_KEYS,
  getPositionDeviationsResponse,
  getTrajectoryFirstRowResponse,
  setOriginResponse,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import { FaClipboardList, FaExchangeAlt } from 'react-icons/fa';
import {
  EmptyState,
  PageShell,
  StatusBadge,
} from '../components/ui';

const MissionConfig = () => {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const cardRefs = useRef({});
  const assignmentWallRef = useRef(null);
  const missionPreviewPanelRef = useRef(null);
  const pendingEnrollmentPanelRef = useRef(null);
  const handledRouteDroneRef = useRef('');

  // -----------------------------------------------------
  // Heading slider: single source of truth
  // -----------------------------------------------------
  const [forwardHeading, setForwardHeading] = useState(0);

  // -----------------------------------------------------
  // State variables
  // -----------------------------------------------------
  const [configData, setConfigData] = useState([]);
  const [editingDroneId, setEditingDroneId] = useState(null);

  // Origin
  const [origin, setOrigin] = useState({ lat: null, lon: null });
  const [originAvailable, setOriginAvailable] = useState(false);
  const [showOriginModal, setShowOriginModal] = useState(false);

  // Role Swap Details Modal
  const [showRoleSwapModal, setShowRoleSwapModal] = useState(false);
  const [roleSwapData, setRoleSwapData] = useState([]);

  // Deviations
  const [deviationData, setDeviationData] = useState({});

  // Git & Network
  const [networkInfo, setNetworkInfo] = useState([]);
  const [gitStatusData, setGitStatusData] = useState({});
  const [gcsGitStatus, setGcsGitStatus] = useState(null);

  // Heartbeat
  const [heartbeats, setHeartbeats] = useState({});

  // UI & Loading
  const [loading, setLoading] = useState(false);

  // Save Review Dialog
  const [showSaveReviewDialog, setShowSaveReviewDialog] = useState(false);
  const [validationReport, setValidationReport] = useState(null);

  const [trajectoryPositionsByPosId, setTrajectoryPositionsByPosId] = useState({});
  const [missionConfigSearch, setMissionConfigSearch] = useState('');
  const [clusterScope, setClusterScope] = useState('all');
  const [assignmentFilter, setAssignmentFilter] = useState('all');
  const [launchLayoutView, setLaunchLayoutView] = useState('plot');
  const [pendingFocusDroneId, setPendingFocusDroneId] = useState(null);
  const requestedDroneId = normalizeComparableId(searchParams.get('drone'));
  const requestedEditMode = searchParams.get('edit') === '1';

  const applyNormalizedConfigData = (nextConfig) => {
    setConfigData(normalizeDroneConfigData(nextConfig));
  };

  const openFleetEnrollment = ({ candidateId = null, replaceTargetHwId = null } = {}) => {
    const nextParams = new URLSearchParams();
    if (candidateId) {
      nextParams.set('candidate', candidateId);
    }
    if (replaceTargetHwId) {
      nextParams.set('replace', normalizeComparableId(replaceTargetHwId));
    }
    navigate(`/fleet-enrollment${nextParams.toString() ? `?${nextParams.toString()}` : ''}`);
  };

  // -----------------------------------------------------
  // Data Fetching using custom hooks
  // -----------------------------------------------------
  const { data: configDataFetched } = useFetch(GCS_ROUTE_KEYS.fleetConfig);
  const { data: originDataFetched, loading: originLoading, error: originError } = useFetch(GCS_ROUTE_KEYS.origin);
  const { data: deviationDataFetched } = useFetch(
    GCS_ROUTE_KEYS.positionDeviations,
    originAvailable ? 5000 : null
  );
  const { data: telemetryDataFetched } = useFetch(GCS_ROUTE_KEYS.fleetTelemetry, 2000);
  const { data: gitStatusDataFetched } = useNormalizedTelemetry(GCS_ROUTE_KEYS.gitStatus, 20000);
  const { data: networkInfoFetched } = useFetch(GCS_ROUTE_KEYS.networkInfo, 10000);
  const { data: heartbeatsFetched } = useFetch(GCS_ROUTE_KEYS.fleetHeartbeats, 5000);
  const { data: fleetCandidatesFetched } = useFetch(`${GCS_ROUTE_KEYS.fleetCandidates}?runtime_mode=current`, 5000);
  const { data: savedDronePositionsFetched } = useFetch(GCS_ROUTE_KEYS.dronePositions, 10000);
  const { data: swarmDataFetched } = useFetch(GCS_ROUTE_KEYS.swarmConfig);

  // -----------------------------------------------------
  // Derived Data & Helpers
  // -----------------------------------------------------
  // Note: x,y positions come from trajectory files, not config.json
  const availableHwIds = buildSuggestedHwIds(configData);
  const roleSwaps = getRoleSwaps(configData);
  const { duplicateHwIds, duplicatePosIds } = getDuplicateAssignments(configData);
  const onlineDroneCount = getOnlineDroneCount(heartbeats);
  const originStatus = useMemo(() => {
    if (originLoading) {
      return 'checking';
    }
    if (originAvailable) {
      return 'ready';
    }
    if (originError) {
      return 'unavailable';
    }
    return 'needed';
  }, [originAvailable, originError, originLoading]);
  const swarmViewModel = useMemo(
    () => buildSwarmViewModel(unwrapSwarmConfigPayload(swarmDataFetched), configData),
    [configData, swarmDataFetched]
  );
  const clusterScopeOptions = useMemo(
    () => buildClusterScopeOptions(swarmViewModel?.clusters || [], configData.length),
    [configData.length, swarmViewModel?.clusters]
  );
  const duplicateHwIdSet = useMemo(
    () => new Set(duplicateHwIds.map((entry) => normalizeComparableId(entry.hw_id)).filter(Boolean)),
    [duplicateHwIds]
  );
  const duplicatePosIdSet = useMemo(
    () => new Set(duplicatePosIds.map((entry) => normalizeComparableId(entry.pos_id)).filter(Boolean)),
    [duplicatePosIds]
  );

  // -----------------------------------------------------
  // Effects: Update local state when data is fetched
  // -----------------------------------------------------
  useEffect(() => {
    if (configDataFetched) {
      applyNormalizedConfigData(configDataFetched);
    }
  }, [configDataFetched]);

  useEffect(() => {
    if (
      originDataFetched &&
      originDataFetched.lat !== undefined &&
      originDataFetched.lon !== undefined
    ) {
      setOrigin({
        lat: Number(originDataFetched.lat),
        lon: Number(originDataFetched.lon),
      });
      setOriginAvailable(true);
    } else {
      setOrigin({ lat: null, lon: null });
      setOriginAvailable(false);
    }
  }, [originDataFetched]);

  useEffect(() => {
    if (deviationDataFetched) {
      setDeviationData(deviationDataFetched);
    }
  }, [deviationDataFetched]);

  useEffect(() => {
    if (gitStatusDataFetched) {
      if (gitStatusDataFetched.git_status) {
        setGitStatusData(gitStatusDataFetched.git_status);
      }
      // GCS status is included in the canonical /api/v1/git/status response
      if (gitStatusDataFetched.gcs_status) {
        setGcsGitStatus(gitStatusDataFetched.gcs_status);
      }
    }
  }, [gitStatusDataFetched]);

  useEffect(() => {
    if (networkInfoFetched) {
      setNetworkInfo(networkInfoFetched);
    }
  }, [networkInfoFetched]);

  useEffect(() => {
    if (heartbeatsFetched && heartbeatsFetched.heartbeats) {
      // Convert heartbeats array to dict keyed by hw_id for easy lookup
      const heartbeatsDict = {};
      heartbeatsFetched.heartbeats.forEach((hb) => {
        const normalizedHwId = normalizeComparableId(hb.hw_id);
        if (normalizedHwId) {
          heartbeatsDict[normalizedHwId] = hb;
        }
      });
      setHeartbeats(heartbeatsDict);
    }
  }, [heartbeatsFetched]);

  useEffect(() => {
    if (!Array.isArray(savedDronePositionsFetched)) {
      return;
    }

    setTrajectoryPositionsByPosId((prev) => {
      const next = { ...prev };
      savedDronePositionsFetched.forEach((position) => {
        const posId = normalizeComparableId(position?.pos_id);
        const north = Number(position?.x);
        const east = Number(position?.y);

        if (!posId || !Number.isFinite(north) || !Number.isFinite(east)) {
          return;
        }

        next[posId] = {
          pos_id: posId,
          x: north,
          y: east,
        };
      });
      return next;
    });
  }, [savedDronePositionsFetched]);

  useEffect(() => {
    const missingPosIds = Array.from(
      new Set(
        configData
          .map((drone) => normalizeComparableId(drone.pos_id, drone.hw_id))
          .filter(Boolean)
      )
    ).filter((posId) => trajectoryPositionsByPosId[posId] === undefined);

    if (missingPosIds.length === 0) {
      return undefined;
    }

    let cancelled = false;
    Promise.all(
      missingPosIds.map(async (posId) => {
        try {
          const response = await getTrajectoryFirstRowResponse(posId);

          const x = Number(response.data?.x ?? response.data?.north);
          const y = Number(response.data?.y ?? response.data?.east);
          if (!Number.isFinite(x) || !Number.isFinite(y)) {
            return [posId, null];
          }

          return [posId, { pos_id: posId, x, y }];
        } catch (error) {
          return [posId, null];
        }
      })
    ).then((results) => {
      if (cancelled) {
        return;
      }

      setTrajectoryPositionsByPosId((prev) => {
        const next = { ...prev };
        results.forEach(([posId, position]) => {
          if (position) {
            next[posId] = position;
          }
        });
        return next;
      });
    });

    return () => {
      cancelled = true;
    };
  }, [configData, trajectoryPositionsByPosId]);

  // -----------------------------------------------------
  // CRUD operations
  // -----------------------------------------------------
  const saveChanges = (originalHwId, updatedData) => {
    const normalizedOriginalHwId = normalizeComparableId(originalHwId);
    const normalizedUpdatedDrone = normalizeDroneConfigEntry(updatedData);

    if (!normalizedUpdatedDrone) {
      toast.error('Invalid drone configuration. Hardware ID is required.');
      return;
    }

    if (
      configData.some(
        (drone) =>
          normalizeComparableId(drone.hw_id) === normalizedUpdatedDrone.hw_id &&
          normalizeComparableId(drone.hw_id) !== normalizedOriginalHwId
      )
    ) {
      alert('The selected Hardware ID is already in use. Please choose another one.');
      return;
    }

    setConfigData((prevConfig) =>
      prevConfig.map((drone) =>
        normalizeComparableId(drone.hw_id) === normalizedOriginalHwId
          ? { ...normalizedUpdatedDrone, isNew: Boolean(drone.isNew) }
          : drone
      )
    );
    setEditingDroneId(null);
    toast.success(`${formatDroneLabel(normalizedOriginalHwId)} updated successfully.`);
  };

  const addNewDrone = () => {
    const newHwId = availableHwIds[0]?.toString() || '1';
    if (!newHwId) return;

    const commonSubnet = configData.length > 0
      ? configData[0].ip.split('.').slice(0, -1).join('.') + '.'
      : '';

    const newDrone = normalizeDroneConfigEntry({
      hw_id: newHwId,
      ip: commonSubnet,
      mavlink_port: (14550 + parseInt(newHwId, 10)).toString(),
      x: '0',
      y: '0',
      pos_id: newHwId,
      serial_port: '/dev/ttyS0',  // Default for Raspberry Pi 4
      baudrate: '57600',           // Standard baudrate
      isNew: true,
    });

    if (!newDrone) {
      return;
    }

    setConfigData((prevConfig) => [...prevConfig, newDrone]);
    toast.success(`Draft ${formatDroneLabel(newHwId)} added.`);
  };

  const removeDrone = (hw_id) => {
    const normalizedHwId = normalizeComparableId(hw_id);
    if (window.confirm(`Are you sure you want to remove ${formatDroneLabel(normalizedHwId)}?`)) {
      setConfigData((prevConfig) =>
        prevConfig.filter((drone) => normalizeComparableId(drone.hw_id) !== normalizedHwId)
      );
      toast.success(`${formatDroneLabel(normalizedHwId)} removed.`);
    }
  };

  // -----------------------------------------------------
  // Origin Modal submission
  // -----------------------------------------------------
  const handleOriginSubmit = (newOrigin) => {
    setOrigin(newOrigin);
    setShowOriginModal(false);
    setOriginAvailable(true);
    toast.success('Origin set successfully.');

    setOriginResponse(newOrigin)
      .then(() => {
        toast.success('Origin saved to server.');
      })
      .catch((error) => {
        console.error('Error saving origin to backend:', error);
        toast.error('Failed to save origin to server.');
      });
  };

  // -----------------------------------------------------
  // Manual refresh for position deviations
  // -----------------------------------------------------
  const handleManualRefresh = () => {
    if (!originAvailable) {
      toast.warning('Origin must be set before fetching position deviations.');
      return;
    }

    getPositionDeviationsResponse()
      .then((response) => {
        setDeviationData(response.data);
      })
      .catch((error) => {
        console.error('Error fetching position deviations:', error);
        toast.error('Failed to refresh position data.');
      });
  };

  // -----------------------------------------------------
  // File ops & config save
  // -----------------------------------------------------
  const handleFileChangeWrapper = (e) => {
    handleFileChange(e, applyNormalizedConfigData);
  };

  const handleRevertChangesWrapper = () => {
    handleRevertChanges(applyNormalizedConfigData);
    toast.info('All unsaved changes have been reverted.');
  };

  const handleSaveChangesToServerWrapper = async () => {
    try {
      // Step 1: Validate configuration and get report
      const report = await validateConfigWithBackend(configData, setLoading);

      // Step 2: Show review dialog with validation report
      setValidationReport(report);
      setShowSaveReviewDialog(true);

    } catch (error) {
      // Validation failed - error already shown by validateConfigWithBackend
      console.error('Validation failed:', error);
    }
  };

  const handleConfirmSave = async () => {
    // User confirmed - proceed with actual save
    setShowSaveReviewDialog(false);
    await handleSaveChangesToServer(configData, applyNormalizedConfigData, setLoading);
  };

  const handleCancelSave = () => {
    // User cancelled - close dialog
    setShowSaveReviewDialog(false);
    setValidationReport(null);
    toast.info('Save cancelled');
  };

  const handleExportConfigWrapper = () => {
    exportConfigJSON(configData);
    toast.success('Configuration exported as JSON.');
  };

  const handleExportConfigCSVWrapper = () => {
    exportConfigCSV(configData);
    toast.success('Configuration exported as CSV.');
  };

  const handleResetToDefault = () => {
    // Find drones that need to be reset (hw_id !== pos_id)
    const dronesNeedingReset = configData.filter(
      (drone) => normalizeComparableId(drone.hw_id) !== normalizeComparableId(drone.pos_id, drone.hw_id)
    );

    if (dronesNeedingReset.length === 0) {
      toast.info('All drones already fly their own assigned show slot.');
      return;
    }

    // Show confirmation dialog with preview
    const message = `Reset ${dronesNeedingReset.length} drone(s) so each drone flies its own show slot?\n\nThis will set Show Slot = Hardware ID for:\n${dronesNeedingReset.map((drone) => `${formatDroneLabel(drone.hw_id)}: ${formatShowSlotLabel(drone.pos_id)} → ${formatShowSlotLabel(drone.hw_id)}`).join('\n')}\n\nNote: Changes will NOT be saved until you click "Save & Commit to Git".`;

    if (window.confirm(message)) {
      // Reset pos_id to hw_id for all drones
      const updatedConfig = configData.map((drone) => ({
        ...drone,
        pos_id: drone.hw_id
      }));

      setConfigData(updatedConfig);
      toast.success(`Reset ${dronesNeedingReset.length} drone assignment(s). Remember to save your changes.`);
    }
  };

  // Sort config data by pos_id (show position order)
  const sortedConfigData = [...configData].sort(
    (left, right) => compareMissionIds(left.pos_id, right.pos_id)
  );
  const visibleClusters = useMemo(
    () => filterClustersByScope(swarmViewModel?.clusters || [], clusterScope),
    [clusterScope, swarmViewModel?.clusters]
  );
  const visibleClusterHwIds = useMemo(() => {
    if (clusterScope === 'all') {
      return null;
    }

    return new Set(
      visibleClusters.flatMap((cluster) => cluster.drones.map((drone) => normalizeComparableId(drone.hw_id)))
    );
  }, [clusterScope, visibleClusters]);
  const pendingEnrollmentDrones = useMemo(() => {
    const candidates = Array.isArray(fleetCandidatesFetched?.candidates)
      ? fleetCandidatesFetched.candidates
      : [];

    return candidates.map((candidate) => {
      const heartbeatStatus = String(candidate.heartbeat_status || 'unknown');
      const registrationState = String(candidate.registration_state || 'pending_operator_review');
      const heartbeatTone = registrationState === 'conflict'
        ? 'warning'
        : heartbeatStatus === 'online'
          ? 'good'
          : heartbeatStatus === 'stale'
            ? 'warning'
            : heartbeatStatus === 'offline'
              ? 'danger'
              : 'neutral';
      const readableHeartbeatStatus = registrationState === 'conflict'
        ? 'Needs review'
        : heartbeatStatus === 'online'
          ? 'Online'
          : heartbeatStatus === 'stale'
            ? 'Stale'
            : heartbeatStatus === 'offline'
              ? 'Offline'
              : 'Unknown';

      return {
        candidate_id: candidate.candidate_id,
        hw_id: normalizeComparableId(candidate.hw_id),
        pos_id: normalizeComparableId(candidate.reported_pos_id),
        detected_pos_id: normalizeComparableId(candidate.detected_pos_id),
        ip: candidate.primary_control_ip || candidate.ip_addresses?.[0] || '',
        mavlink_port: '',
        heartbeatAgeSec: Number.isFinite(candidate.heartbeat_age_sec) ? candidate.heartbeat_age_sec : null,
        heartbeatStatus: readableHeartbeatStatus,
        heartbeatTone,
        conflict_reasons: Array.isArray(candidate.conflict_reasons) ? candidate.conflict_reasons : [],
        registration_state: registrationState,
      };
    });
  }, [fleetCandidatesFetched]);
  const getHeartbeatAgeSec = (heartbeatData) => {
    const timestamp = Number(heartbeatData?.timestamp);
    if (!Number.isFinite(timestamp)) {
      return null;
    }

    return Math.floor((Date.now() - timestamp) / 1000);
  };
  const getAssignmentSignals = (drone) => {
    const hwId = normalizeComparableId(drone.hw_id);
    const configPosId = normalizeComparableId(drone.pos_id, drone.hw_id);
    const heartbeatData = heartbeats[hwId] || null;
    const heartbeatAgeSec = getHeartbeatAgeSec(heartbeatData);
    const presenceState = String(heartbeatData?.presence?.state || heartbeatData?.presence_state || '').trim().toLowerCase();
    const assignedPosId = normalizeComparableId(heartbeatData?.pos_id);
    const autoPosId = normalizeComparableId(heartbeatData?.detected_pos_id);
    const slotPresentation = buildMissionSlotStatusPresentation(configPosId, assignedPosId, autoPosId);
    const isRoleSwap = Boolean(hwId && configPosId && hwId !== configPosId);
    const isOffline = ['offline', 'never_seen'].includes(presenceState)
      || (!presenceState && heartbeatAgeSec !== null && heartbeatAgeSec >= 60);
    const linkNeedsReview = ['blocked', 'recently_lost', 'stale'].includes(presenceState);
    const isDraft = Boolean(drone.isNew);
    const needsAttention = (
      duplicateHwIdSet.has(hwId)
      || duplicatePosIdSet.has(configPosId)
      || isRoleSwap
      || isDraft
      || isOffline
      || linkNeedsReview
      || slotPresentation.tone === 'review'
    );

    return {
      isDraft,
      isRoleSwap,
      isOffline,
      linkNeedsReview,
      needsAttention,
    };
  };
  const assignmentFilterOptions = useMemo(() => {
    const counts = {
      all: sortedConfigData.length,
      attention: 0,
      roleSwaps: 0,
      offline: 0,
      draft: 0,
    };

    sortedConfigData.forEach((drone) => {
      const signals = getAssignmentSignals(drone);
      if (signals.needsAttention) {
        counts.attention += 1;
      }
      if (signals.isRoleSwap) {
        counts.roleSwaps += 1;
      }
      if (signals.isOffline) {
        counts.offline += 1;
      }
      if (signals.isDraft) {
        counts.draft += 1;
      }
    });

    return [
      {
        id: 'all',
        label: 'All assignments',
        count: counts.all,
        description: 'Show every assignment card.',
      },
      counts.attention > 0
        ? {
            id: 'attention',
            label: 'Needs review',
            count: counts.attention,
            description: 'Show cards that need operator attention first.',
          }
        : null,
      counts.roleSwaps > 0
        ? {
            id: 'roleSwaps',
            label: 'Slot reassignments',
            count: counts.roleSwaps,
            description: 'Show assignments where hardware identity and slot ownership differ.',
          }
        : null,
      counts.offline > 0
        ? {
            id: 'offline',
            label: 'Offline',
            count: counts.offline,
            description: 'Show drones that have gone offline.',
          }
        : null,
      counts.draft > 0
        ? {
            id: 'draft',
            label: 'Draft',
            count: counts.draft,
            description: 'Show unsaved draft assignments.',
          }
        : null,
    ].filter(Boolean);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sortedConfigData, heartbeats, duplicateHwIdSet, duplicatePosIdSet]);
  useEffect(() => {
    if (!assignmentFilterOptions.some((option) => option.id === assignmentFilter)) {
      setAssignmentFilter('all');
    }
  }, [assignmentFilter, assignmentFilterOptions]);
  const filteredConfigData = useMemo(() => (
    sortedConfigData.filter((drone) => {
      const hwId = normalizeComparableId(drone.hw_id);
      if (visibleClusterHwIds && !visibleClusterHwIds.has(hwId)) {
        return false;
      }

      if (!matchesDroneSearchQuery(drone, missionConfigSearch)) {
        return false;
      }

      if (assignmentFilter === 'all') {
        return true;
      }

      const signals = getAssignmentSignals(drone);
      switch (assignmentFilter) {
        case 'attention':
          return signals.needsAttention;
        case 'roleSwaps':
          return signals.isRoleSwap;
        case 'offline':
          return signals.isOffline;
        case 'draft':
          return signals.isDraft;
        default:
          return true;
      }
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  ), [assignmentFilter, missionConfigSearch, sortedConfigData, visibleClusterHwIds, heartbeats, duplicateHwIdSet, duplicatePosIdSet]);
  const draftAssignmentCount = configData.filter((drone) => drone.isNew).length;
  const missionWorkspaceStats = useMemo(
    () => [
      { label: 'Visible', value: filteredConfigData.length },
      { label: 'Online', value: onlineDroneCount },
      { label: 'Role swaps', value: roleSwaps.length },
      { label: 'Duplicate slots', value: duplicatePosIds.length },
      { label: 'Draft', value: draftAssignmentCount },
      { label: 'Pending', value: pendingEnrollmentDrones.length },
      {
        label: 'Origin',
        value: originStatus === 'ready'
          ? 'Ready'
          : originStatus === 'checking'
            ? 'Checking'
            : originStatus === 'unavailable'
              ? 'Check failed'
              : 'Needed',
        tone: originStatus === 'ready' ? 'good' : originStatus === 'checking' ? null : 'warning',
        actionLabel: originStatus === 'ready' ? 'Review' : 'Open',
      },
    ],
    [draftAssignmentCount, duplicatePosIds.length, filteredConfigData.length, onlineDroneCount, originStatus, pendingEnrollmentDrones.length, roleSwaps.length]
  );
  const missionAttentionCount = duplicateHwIds.length
    + duplicatePosIds.length
    + roleSwaps.length
    + draftAssignmentCount
    + pendingEnrollmentDrones.length
    + (originStatus === 'ready' || originStatus === 'checking' ? 0 : 1);
  const missionWorkspaceHeadline = missionAttentionCount > 0
    ? `${missionAttentionCount} active review item${missionAttentionCount === 1 ? '' : 's'}`
    : 'Assignment wall is clear for save review';
  const missionSearchSummary = `${filteredConfigData.length}/${sortedConfigData.length} assignment card${sortedConfigData.length === 1 ? '' : 's'} visible`;
  const originStatusLabel = originStatus === 'ready'
    ? 'Origin ready'
    : originStatus === 'checking'
      ? 'Origin checking'
      : originStatus === 'unavailable'
        ? 'Origin check failed'
        : 'Origin needed';

  const scrollNodeIntoView = (node, block = 'center') => {
    if (!node) {
      return;
    }

    node.scrollIntoView({
      behavior: 'smooth',
      block,
    });
  };

  const reviewOriginWorkflow = () => {
    if (missionPreviewPanelRef.current) {
      missionPreviewPanelRef.current.open = true;
      scrollNodeIntoView(missionPreviewPanelRef.current, 'start');
    }

    setShowOriginModal(true);
  };

  const reviewAssignmentCard = (hwId, filterId = 'attention') => {
    const normalizedHwId = normalizeComparableId(hwId);
    setClusterScope('all');
    setMissionConfigSearch('');
    setAssignmentFilter(filterId);

    if (!normalizedHwId) {
      scrollNodeIntoView(assignmentWallRef.current, 'start');
      return;
    }

    setPendingFocusDroneId(normalizedHwId);
  };

  const reviewDuplicateHardwareIds = () => {
    reviewAssignmentCard(duplicateHwIds[0]?.hw_id, 'attention');
  };

  const reviewDuplicateSlots = () => {
    reviewAssignmentCard(duplicatePosIds[0]?.hw_ids?.[0], 'attention');
  };

  const reviewRoleSwapAssignments = () => {
    setClusterScope('all');
    setMissionConfigSearch('');
    setAssignmentFilter('roleSwaps');

    const firstRoleSwapHwId = normalizeComparableId(roleSwaps[0]?.hw_id);
    if (firstRoleSwapHwId) {
      setPendingFocusDroneId(firstRoleSwapHwId);
    } else {
      scrollNodeIntoView(assignmentWallRef.current, 'start');
    }

    if (roleSwaps.length > 3) {
      setRoleSwapData(roleSwaps);
      setShowRoleSwapModal(true);
    }
  };

  const reviewPendingEnrollmentCandidates = () => {
    scrollNodeIntoView(pendingEnrollmentPanelRef.current, 'start');
  };

  useEffect(() => {
    if (!requestedDroneId) {
      handledRouteDroneRef.current = '';
      return;
    }

    const matchingDrone = configData.find(
      (drone) => normalizeComparableId(drone.hw_id) === requestedDroneId
    );

    if (!matchingDrone || handledRouteDroneRef.current === requestedDroneId) {
      return;
    }

    handledRouteDroneRef.current = requestedDroneId;
    if (requestedEditMode) {
      setEditingDroneId(requestedDroneId);
    }

    const targetNode = cardRefs.current[requestedDroneId];
    if (!targetNode) {
      return;
    }

    scrollNodeIntoView(targetNode);
  }, [configData, requestedDroneId, requestedEditMode]);

  useEffect(() => {
    if (!pendingFocusDroneId) {
      return;
    }

    const targetNode = cardRefs.current[pendingFocusDroneId];
    if (!targetNode) {
      return;
    }

    scrollNodeIntoView(targetNode);
    setPendingFocusDroneId(null);
  }, [filteredConfigData, pendingFocusDroneId]);

  // -----------------------------------------------------
  // Render
  // -----------------------------------------------------
  return (
    <PageShell
      className="mission-config-container"
      eyebrow="Configuration"
      title="Mission Config"
      subtitle="Assignment wall for slot ownership, identity, and launch readiness."
      icon={<FaClipboardList />}
      docsRoute="/mission-config"
      docsOptions={{
        repoUrl: gcsGitStatus?.remote_url || '',
        branch: gcsGitStatus?.branch || '',
      }}
      status={(
        <div className="mission-config-page-status">
          <StatusBadge tone={missionAttentionCount > 0 ? 'warning' : 'success'}>
            {missionAttentionCount} review
          </StatusBadge>
          <StatusBadge tone="muted">
            {filteredConfigData.length}/{sortedConfigData.length} visible
          </StatusBadge>
          <StatusBadge tone={originStatus === 'ready' ? 'success' : originStatus === 'checking' ? 'muted' : 'warning'}>
            {originStatusLabel}
          </StatusBadge>
        </div>
      )}
    >

      <MissionConfigToolbar
        headline={missionWorkspaceHeadline}
        loading={loading}
        onSave={handleSaveChangesToServerWrapper}
        onAddDrone={addNewDrone}
        searchValue={missionConfigSearch}
        onSearchChange={setMissionConfigSearch}
        searchPlaceholder={DRONE_SEARCH_PLACEHOLDER}
        searchSummary={missionSearchSummary}
        stats={missionWorkspaceStats}
        onReviewOrigin={reviewOriginWorkflow}
        assignmentFilterOptions={assignmentFilterOptions}
        assignmentFilter={assignmentFilter}
        onAssignmentFilterChange={setAssignmentFilter}
        clusterScopeOptions={clusterScopeOptions}
        clusterScope={clusterScope}
        onClusterScopeChange={setClusterScope}
      />

      <MissionConfigAlertStack
        pendingEnrollmentDrones={pendingEnrollmentDrones}
        duplicateHwIds={duplicateHwIds}
        duplicatePosIds={duplicatePosIds}
        roleSwaps={roleSwaps}
        originStatus={originStatus}
        onReviewPendingEnrollment={reviewPendingEnrollmentCandidates}
        onReviewDuplicateHardwareIds={reviewDuplicateHardwareIds}
        onReviewDuplicateSlots={reviewDuplicateSlots}
        onReviewRoleSwaps={reviewRoleSwapAssignments}
        onReviewOrigin={reviewOriginWorkflow}
      />

      <PendingEnrollmentPanel
        candidates={pendingEnrollmentDrones}
        panelRef={pendingEnrollmentPanelRef}
        onOpenQueue={() => openFleetEnrollment()}
        onReviewCandidate={(candidateId) => openFleetEnrollment({ candidateId })}
      />

      {/* Origin Modal */}
      {showOriginModal && (
        <OriginModal
          isOpen={showOriginModal}
          onClose={() => setShowOriginModal(false)}
          onSubmit={handleOriginSubmit}
          telemetryData={telemetryDataFetched || {}}
          configData={configData}
          currentOrigin={origin}
        />
      )}

      {/* Role Swap Details Modal */}
      {showRoleSwapModal && (
        <div
          className="modal-overlay"
          onClick={() => setShowRoleSwapModal(false)}
        >
          <div
            className="role-swap-modal"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="role-swap-modal-title"
          >
            <h3 id="role-swap-modal-title">
              <FaExchangeAlt className="role-swap-modal__title-icon" />
              All Active Role Swaps ({roleSwapData.length})
            </h3>
            <p className="role-swap-modal__intro">
              These drones are assigned to a different show slot than their own:
            </p>
            <table>
              <thead>
                <tr>
                  <th>Drone</th>
                  <th className="role-swap-modal__arrow">→</th>
                  <th>Show Slot</th>
                </tr>
              </thead>
              <tbody>
                {roleSwapData.map((drone) => (
                  <tr key={drone.hw_id}>
                    <td>
                      <strong>{formatDroneLabel(drone.hw_id)}</strong>
                    </td>
                    <td className="role-swap-modal__arrow">→</td>
                    <td>
                      <strong>{formatShowSlotLabel(drone.pos_id)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="role-swap-modal__actions">
              <button type="button" onClick={() => setShowRoleSwapModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Main content: Drone Cards & Plots */}
      <div className="content-flex">
        <div className="drone-cards slide-in-left" ref={assignmentWallRef}>
          <div className="mission-config-card-panel-header">
            <h3>Assignment wall</h3>
            <span className="mission-config-card-panel-meta">
              {filteredConfigData.length} visible
            </span>
          </div>
          {filteredConfigData.length > 0 ? (
            filteredConfigData.map((drone, index) => (
              <div
                key={drone.hw_id}
                id={`mission-config-drone-${drone.hw_id}`}
                ref={(node) => {
                  const normalizedHwId = normalizeComparableId(drone.hw_id);
                  if (!normalizedHwId) {
                    return;
                  }

                  if (node) {
                    cardRefs.current[normalizedHwId] = node;
                  } else {
                    delete cardRefs.current[normalizedHwId];
                  }
                }}
              >
                <DroneConfigCard
                  drone={drone}
                  gitStatus={gitStatusData[drone.hw_id] || null}
                  gcsGitStatus={gcsGitStatus}
                  configData={configData}
                  availableHwIds={availableHwIds}
                  editingDroneId={editingDroneId}
                  setEditingDroneId={setEditingDroneId}
                  saveChanges={saveChanges}
                  removeDrone={removeDrone}
                  onReplace={(hwId) => openFleetEnrollment({ replaceTargetHwId: hwId })}
                  networkInfo={
                    networkInfo.find(
                      (info) => normalizeComparableId(info.hw_id) === normalizeComparableId(drone.hw_id)
                    )
                  }
                  heartbeatData={heartbeats[drone.hw_id] || null}
                  style={{ animationDelay: `${index * 0.1}s` }}
                />
              </div>
            ))
          ) : (
            <EmptyState
              title="No matching assignments"
              detail="Clear search, issue focus, or cluster scope to widen the assignment wall."
            />
          )}
        </div>

        <div className="initial-launch-plot slide-in-right">
          <div className="mission-config-layout-switcher" role="tablist" aria-label="Launch layout view">
            <button
              type="button"
              className={`mission-config-layout-switcher__button ${launchLayoutView === 'plot' ? 'active' : ''}`}
              onClick={() => setLaunchLayoutView('plot')}
              aria-pressed={launchLayoutView === 'plot'}
            >
              Plot
            </button>
            <button
              type="button"
              className={`mission-config-layout-switcher__button ${launchLayoutView === 'map' ? 'active' : ''}`}
              onClick={() => setLaunchLayoutView('map')}
              aria-pressed={launchLayoutView === 'map'}
            >
              Map
            </button>
          </div>

          {launchLayoutView === 'plot' ? (
            <PositionTabs
              drones={configData}
              deviationData={deviationData}
              trajectoryPositionsByPosId={trajectoryPositionsByPosId}
              origin={origin}
              forwardHeading={forwardHeading}
              onDroneClick={(hwId) => setEditingDroneId(normalizeComparableId(hwId))}
              onRefresh={handleManualRefresh}
            />
          ) : (
            <DronePositionMap
              originLat={origin.lat}
              originLon={origin.lon}
              drones={configData}
              deviationData={deviationData}
              trajectoryPositionsByPosId={trajectoryPositionsByPosId}
              forwardHeading={forwardHeading}
              onDroneClick={(hwId) => setEditingDroneId(normalizeComparableId(hwId))}
            />
          )}
        </div>
      </div>

      <section className="mission-config-secondary-panels" aria-label="Mission configuration secondary tools">
        <details className="mission-config-secondary-panel">
          <summary>
            <span>Mission tools</span>
            <small>Sync, import/export, origin, revert, and reset actions</small>
          </summary>
          <ControlButtons
            addNewDrone={addNewDrone}
            handleSaveChangesToServer={handleSaveChangesToServerWrapper}
            handleRevertChanges={handleRevertChangesWrapper}
            handleFileChange={handleFileChangeWrapper}
            exportConfig={handleExportConfigWrapper}
            exportConfigCSV={handleExportConfigCSVWrapper}
            openOriginModal={() => setShowOriginModal(true)}
            handleResetToDefault={handleResetToDefault}
            configData={configData}
            setConfigData={setConfigData}
            loading={loading}
            mode="secondary"
          />
        </details>

        <details className="mission-config-secondary-panel">
          <summary>
            <span>Identity guide</span>
            <small>Slot ownership, slot reassignment, optional metadata</small>
          </summary>
          <div className="mission-identity-guide__grid">
            <div className="identity-brief-card">
              <span className="identity-brief-label">Hardware ID</span>
              <strong>Physical drone identity</strong>
              <p>Matches the labeled drone and the companion-computer identity used at runtime.</p>
            </div>
            <div className="identity-brief-card">
              <span className="identity-brief-label">Position ID</span>
              <strong>Show slot / trajectory slot</strong>
              <p>Selects which <code>Drone {'{pos_id}'}.csv</code> path that airframe will fly.</p>
            </div>
            <div className="identity-brief-card identity-brief-card-wide">
              <span className="identity-brief-label">Operational rule</span>
              <strong>Follow-links still use Hardware ID.</strong>
              <p>
                Slot reassignment in Mission Config changes show-slot ownership only. Physical replacement uses
                Fleet Enrollment so the slot stays intact and Smart Swarm follow references move to the new hardware.
              </p>
            </div>
            <div className="identity-brief-card">
              <span className="identity-brief-label">Additional fields</span>
              <strong>Optional metadata stays secondary</strong>
              <p>Add guided fields like <code>callsign</code>, <code>marker_color</code>, <code>notes</code>, or custom metadata without changing the core identity model.</p>
            </div>
          </div>
        </details>

        <details className="mission-config-secondary-panel" ref={missionPreviewPanelRef}>
          <summary>
            <span>Mission preview tools</span>
            <small>KML export, print, origin state, and forward-heading preview</small>
          </summary>
          <MissionLayout
            configData={configData}
            origin={origin}
            openOriginModal={() => setShowOriginModal(true)}
          />

          <div className="heading-controls heading-controls-preview">
            <div className="heading-controls-header">
              <div>
                <div className="heading-kicker">Preview Only</div>
                <label htmlFor="headingSlider">
                  Forward Heading: {forwardHeading}°
                </label>
                <p className="heading-controls-copy">
                  Updates the mission preview only. Server-backed forward heading workflow is still under development.
                </p>
              </div>
              <span className="heading-status-badge">Under development</span>
            </div>
            <input
              id="headingSlider"
              type="range"
              min={0}
              max={359}
              value={forwardHeading}
              onChange={(e) => setForwardHeading(parseInt(e.target.value, 10))}
            />
            <div className="heading-preview-note">
              Coming soon: mission-wide save/apply behavior after the operator workflow is finalized.
            </div>
          </div>
        </details>
      </section>

      {/* Save Review Dialog */}
      <SaveReviewDialog
        isOpen={showSaveReviewDialog}
        validationReport={validationReport}
        onConfirm={handleConfirmSave}
        onCancel={handleCancelSave}
      />
    </PageShell>
  );
};

export default MissionConfig;
