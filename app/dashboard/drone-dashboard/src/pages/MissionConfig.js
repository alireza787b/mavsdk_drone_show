// src/pages/MissionConfig.js

import React, { useState, useEffect, useMemo, useRef } from 'react';
import '../styles/MissionConfig.css';
import { useSearchParams } from 'react-router-dom';

// Components
import PositionTabs from '../components/PositionTabs';
import DroneConfigCard from '../components/DroneConfigCard';
import ControlButtons from '../components/ControlButtons';
import MissionLayout from '../components/MissionLayout';
import OriginModal from '../components/OriginModal';
import GcsConfigModal from '../components/GcsConfigModal';
import DronePositionMap from '../components/DronePositionMap';
import SaveReviewDialog from '../components/SaveReviewDialog';
import ReplaceDroneWizard from '../components/ReplaceDroneWizard';
import ClusterScopeBar from '../components/ClusterScopeBar';

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
  DRONE_SEARCH_HELP_TEXT,
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
  saveGcsConfigResponse,
  setOriginResponse,
} from '../services/gcsApiService';

// Icons
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faExclamationTriangle, faExchangeAlt } from '@fortawesome/free-solid-svg-icons';

const MissionConfig = () => {
  const [searchParams] = useSearchParams();
  const cardRefs = useRef({});
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

  // GCS Configuration
  const [showGcsConfigModal, setShowGcsConfigModal] = useState(false);
  const [gcsConfig, setGcsConfig] = useState({ gcs_ip: null });

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

  // Replace Drone Wizard
  const [replaceDroneModalOpen, setReplaceDroneModalOpen] = useState(false);
  const [replaceDroneTarget, setReplaceDroneTarget] = useState(null);
  const [trajectoryPositionsByPosId, setTrajectoryPositionsByPosId] = useState({});
  const [missionConfigSearch, setMissionConfigSearch] = useState('');
  const [clusterScope, setClusterScope] = useState('all');
  const requestedDroneId = normalizeComparableId(searchParams.get('drone'));
  const requestedEditMode = searchParams.get('edit') === '1';

  const applyNormalizedConfigData = (nextConfig) => {
    setConfigData(normalizeDroneConfigData(nextConfig));
  };

  // -----------------------------------------------------
  // Data Fetching using custom hooks
  // -----------------------------------------------------
  const { data: configDataFetched } = useFetch(GCS_ROUTE_KEYS.fleetConfig);
  const { data: originDataFetched } = useFetch(GCS_ROUTE_KEYS.origin);
  const { data: gcsConfigFetched } = useFetch(GCS_ROUTE_KEYS.gcsConfig, null);
  const { data: deviationDataFetched } = useFetch(
    GCS_ROUTE_KEYS.positionDeviations,
    originAvailable ? 5000 : null
  );
  const { data: telemetryDataFetched } = useFetch(GCS_ROUTE_KEYS.fleetTelemetry, 2000);
  const { data: gitStatusDataFetched } = useNormalizedTelemetry(GCS_ROUTE_KEYS.gitStatus, 20000);
  const { data: networkInfoFetched } = useFetch(GCS_ROUTE_KEYS.networkInfo, 10000);
  const { data: heartbeatsFetched } = useFetch(GCS_ROUTE_KEYS.fleetHeartbeats, 5000);
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
  const swarmViewModel = useMemo(
    () => (Array.isArray(swarmDataFetched) ? buildSwarmViewModel(swarmDataFetched, configData) : null),
    [configData, swarmDataFetched]
  );
  const clusterScopeOptions = useMemo(
    () => buildClusterScopeOptions(swarmViewModel?.clusters || [], configData.length),
    [configData.length, swarmViewModel?.clusters]
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
      // GCS status is included in the unified /git-status response
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
    if (gcsConfigFetched?.data?.gcs_ip) {
      setGcsConfig(gcsConfigFetched.data);
    }
  }, [gcsConfigFetched]);

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

          const north = Number(response.data?.north);
          const east = Number(response.data?.east);
          if (!Number.isFinite(north) || !Number.isFinite(east)) {
            return [posId, null];
          }

          return [posId, { pos_id: posId, x: north, y: east }];
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
  // Detect & add "new" drones by heartbeat
  // -----------------------------------------------------
  useEffect(() => {
    const heartbeatHwIds = Object.keys(heartbeats);
    const configuredHwIds = new Set(
      configData.map((drone) => normalizeComparableId(drone.hw_id)).filter(Boolean)
    );

    const newDrones = [];
    for (const hbHwId of heartbeatHwIds) {
      const normalizedHwId = normalizeComparableId(hbHwId);
      if (!normalizedHwId || configuredHwIds.has(normalizedHwId)) {
        continue;
      }

      const hb = heartbeats[hbHwId];
      const normalizedDrone = normalizeDroneConfigEntry({
        hw_id: normalizedHwId,
        pos_id: hb.pos_id || normalizedHwId,
        ip: hb.ip || '',
        x: '0',
        y: '0',
        mavlink_port: String(14550 + parseInt(normalizedHwId, 10)),
        serial_port: '/dev/ttyS0',  // Default for Raspberry Pi 4
        baudrate: '57600',           // Standard baudrate
        isNew: true,
      });

      if (normalizedDrone) {
        newDrones.push(normalizedDrone);
        configuredHwIds.add(normalizedHwId);
      }
    }

    if (newDrones.length > 0) {
      setConfigData((prev) => [...prev, ...newDrones]);
      toast.info(`${newDrones.length} new drone(s) detected and added.`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [heartbeats, configData]);

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
          ? { ...normalizedUpdatedDrone, isNew: false }
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
    toast.success(`New ${formatDroneLabel(newHwId)} added.`);
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
  // GCS Configuration Modal submission
  // -----------------------------------------------------
  const handleGcsConfigSubmit = async (newGcsConfig) => {
    try {
      const response = await saveGcsConfigResponse(newGcsConfig);

      if (response.data.success) {
        setGcsConfig(newGcsConfig);
        setShowGcsConfigModal(false);

        // Show success message with warnings
        toast.success(response.data.message || 'GCS IP updated successfully');

        if (response.data.warnings && response.data.warnings.length > 0) {
          response.data.warnings.forEach(warning => {
            toast.warning(warning, { autoClose: 8000 });
          });
        }

        if (response.data.git_status) {
          // Handle both string and object git_status formats
          if (typeof response.data.git_status === 'string') {
            toast.info(`Git: ${response.data.git_status}`, { autoClose: 5000 });
          } else if (typeof response.data.git_status === 'object') {
            // Format git status object properly to avoid "[object Object]" display
            const gitStatus = response.data.git_status;
            const branch = gitStatus.branch || gitStatus.current_branch || 'unknown';
            const commit = gitStatus.commit || gitStatus.latest_commit || 'unknown';
            const shortCommit = typeof commit === 'string' ? commit.slice(0, 7) : commit;
            toast.info(`Git: ${branch} @ ${shortCommit}`, { autoClose: 5000 });
          }
        }
      } else {
        toast.error(response.data.message || 'Failed to update GCS IP');
      }
    } catch (error) {
      console.error('Error saving GCS configuration:', error);
      toast.error(
        error.response?.data?.message ||
        'Failed to save GCS configuration to server.'
      );
    }
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
  const filteredConfigData = useMemo(() => (
    sortedConfigData.filter((drone) => {
      const hwId = normalizeComparableId(drone.hw_id);
      if (visibleClusterHwIds && !visibleClusterHwIds.has(hwId)) {
        return false;
      }

      return matchesDroneSearchQuery(drone, missionConfigSearch);
    })
  ), [missionConfigSearch, sortedConfigData, visibleClusterHwIds]);

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

    targetNode.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });
  }, [configData, requestedDroneId, requestedEditMode]);

  // -----------------------------------------------------
  // Render
  // -----------------------------------------------------
  return (
    <div className="mission-config-container">
      <header className="mission-config-page-header">
        <div className="mission-config-page-header__content">
          <h2 className="mission-config-title">Mission Configuration</h2>
          <p className="mission-config-subtitle">
            Assign airframes to slots and keep operator identity current.
          </p>
          <div className="mission-config-header-chips" aria-label="Mission configuration focus areas">
            <span className="mission-config-header-chip">Identity</span>
            <span className="mission-config-header-chip">Launch slot</span>
            <span className="mission-config-header-chip">Metadata</span>
          </div>
        </div>
      </header>

      <section className="mission-identity-brief" aria-label="Hardware and position ID guidance">
        <div className="mission-identity-brief__summary">
          <div className="identity-brief-card">
            <span className="identity-brief-label">Hardware ID</span>
            <strong>Airframe identity</strong>
            <p>Labeled airframe and runtime identity.</p>
          </div>
          <div className="identity-brief-card">
            <span className="identity-brief-label">Position ID</span>
            <strong>Mission slot</strong>
            <p>Assigned show or route slot.</p>
          </div>
          <div className="identity-brief-card">
            <span className="identity-brief-label">Role swaps</span>
            <strong>Allowed, but explicit</strong>
            <p>Use only for deliberate spare takeover.</p>
          </div>
        </div>

        <details className="mission-identity-guide">
          <summary>
            <span>Identity guide</span>
            <small>Slot ownership, role swaps, optional metadata</small>
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
              <p>Role swaps change slot ownership only. Smart Swarm follow-chains still reference physical leader hardware IDs.</p>
            </div>
            <div className="identity-brief-card">
              <span className="identity-brief-label">Additional fields</span>
              <strong>Optional metadata stays secondary</strong>
              <p>Add JSON-backed fields like <code>callsign</code>, <code>notes</code>, or maintenance tags without changing the core identity model.</p>
            </div>
          </div>
        </details>
      </section>

      {/* Top Control Buttons */}
      <ControlButtons
        addNewDrone={addNewDrone}
        handleSaveChangesToServer={handleSaveChangesToServerWrapper}
        handleRevertChanges={handleRevertChangesWrapper}
        handleFileChange={handleFileChangeWrapper}
        exportConfig={handleExportConfigWrapper}
        exportConfigCSV={handleExportConfigCSVWrapper}
        openOriginModal={() => setShowOriginModal(true)}
        openGcsConfigModal={() => setShowGcsConfigModal(true)}
        handleResetToDefault={handleResetToDefault}
        configData={configData}
        setConfigData={setConfigData}
        loading={loading}
      />

      {(duplicateHwIds.length > 0 || duplicatePosIds.length > 0 || roleSwaps.length > 0) && (
        <div className="config-warning-banner">
          {duplicateHwIds.length > 0 && (
            <div className="warning-section collision-warning">
              <FontAwesomeIcon icon={faExclamationTriangle} />
              <strong> Invalid Hardware IDs:</strong>
              {duplicateHwIds.map((duplicate) => (
                <span key={duplicate.hw_id} className="duplicate-detail">
                  {' '}{formatDroneLabel(duplicate.hw_id)} appears multiple times
                </span>
              ))}
            </div>
          )}
          {duplicatePosIds.length > 0 && (
            <div className="warning-section collision-warning">
              <FontAwesomeIcon icon={faExclamationTriangle} />
              <strong> Collision Risk:</strong>
              {duplicatePosIds.map((duplicate) => (
                <span key={duplicate.pos_id} className="duplicate-detail">
                  {' '}{formatShowSlotLabel(duplicate.pos_id)} → Drones {duplicate.hw_ids.map((hwId) => formatDroneLabel(hwId)).join(', ')}
                </span>
              ))}
            </div>
          )}
          {roleSwaps.length > 0 && (
            <div className="warning-section role-swap-info">
              <FontAwesomeIcon icon={faExchangeAlt} />
              <strong> {roleSwaps.length} Active Role Swap(s):</strong>
              {roleSwaps.slice(0, 3).map((drone) => (
                <span key={drone.hw_id} className="role-swap-detail">
                  {' '}{formatDroneLabel(drone.hw_id)} → {formatShowSlotLabel(drone.pos_id)}
                </span>
              ))}
              {roleSwaps.length > 3 && (
                <button
                  type="button"
                  className="role-swap-more-link"
                  onClick={() => {
                    setRoleSwapData(roleSwaps);
                    setShowRoleSwapModal(true);
                  }}
                >
                  and {roleSwaps.length - 3} more
                </button>
              )}
            </div>
          )}
        </div>
      )}

      {!originAvailable && (
        <div className="origin-warning">
          <p>
            <strong>Note:</strong> Origin coordinates are not set. Please set the origin
            to display position deviation data.
          </p>
        </div>
      )}

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

      {/* GCS Configuration Modal */}
      {showGcsConfigModal && (
        <GcsConfigModal
          isOpen={showGcsConfigModal}
          onClose={() => setShowGcsConfigModal(false)}
          onSubmit={handleGcsConfigSubmit}
          currentGcsIp={gcsConfig.gcs_ip}
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
          >
            <h3>
              <FontAwesomeIcon icon={faExchangeAlt} style={{ marginRight: '10px' }} />
              All Active Role Swaps ({roleSwapData.length})
            </h3>
            <p style={{ marginBottom: '16px' }}>
              These drones are assigned to a different show slot than their own:
            </p>
            <table>
              <thead>
                <tr>
                  <th>Drone</th>
                  <th style={{ textAlign: 'center' }}>→</th>
                  <th>Show Slot</th>
                </tr>
              </thead>
              <tbody>
                {roleSwapData.map((drone) => (
                  <tr key={drone.hw_id}>
                    <td>
                      <strong>{formatDroneLabel(drone.hw_id)}</strong>
                    </td>
                    <td style={{ textAlign: 'center' }}>→</td>
                    <td>
                      <strong>{formatShowSlotLabel(drone.pos_id)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ marginTop: '20px', textAlign: 'right' }}>
              <button onClick={() => setShowRoleSwapModal(false)}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <MissionLayout
        configData={configData}
        origin={origin}
        openOriginModal={() => setShowOriginModal(true)}
      />

      <section className="mission-config-ops-toolbar" aria-label="Mission configuration filters">
        <label className="mission-config-search">
          <span>Search assignments</span>
          <input
            type="search"
            value={missionConfigSearch}
            onChange={(event) => setMissionConfigSearch(event.target.value)}
            placeholder={DRONE_SEARCH_PLACEHOLDER}
            aria-label="Search assignments by position, hardware ID, or callsign"
          />
        </label>
        <p className="mission-config-ops-note">
          {filteredConfigData.length}/{sortedConfigData.length} assignment card{sortedConfigData.length === 1 ? '' : 's'} visible. {DRONE_SEARCH_HELP_TEXT}
        </p>
      </section>

      {clusterScopeOptions.length > 1 && (
        <ClusterScopeBar
          label="Cluster scope"
          options={clusterScopeOptions}
          selectedId={clusterScope}
          onSelect={setClusterScope}
          summary="Detected from the current saved swarm topology."
        />
      )}

      {/* Drone Stats Summary */}
      {configData.length > 0 && (
        <div className="drone-stats-summary">
          <div className="stat-item">
            <span className="stat-number">{configData.length}</span>
            <span className="stat-label">Drones</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{onlineDroneCount}</span>
            <span className="stat-label">Online</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{roleSwaps.length}</span>
            <span className="stat-label">Role Swaps</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{duplicatePosIds.length}</span>
            <span className="stat-label">Duplicate Slots</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">{configData.filter((drone) => drone.isNew).length}</span>
            <span className="stat-label">New Drones</span>
          </div>
          <div className="stat-item">
            <span className="stat-number">
              {originAvailable ? '✓' : '✗'}
            </span>
            <span className="stat-label">Origin Set</span>
          </div>
        </div>
      )}

      {/* TODO: Persist mission-wide forward heading once the backend contract is finalized. */}
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

      {/* Main content: Drone Cards & Plots */}
      <div className="content-flex">
        <div className="drone-cards slide-in-left">
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
                  onReplace={(hwId) => {
                    setReplaceDroneTarget(normalizeComparableId(hwId));
                    setReplaceDroneModalOpen(true);
                  }}
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
            <p>No assignment cards match the current search or cluster scope.</p>
          )}
        </div>

        <div className="initial-launch-plot slide-in-right">
          <PositionTabs
            drones={configData}
            deviationData={deviationData}
            trajectoryPositionsByPosId={trajectoryPositionsByPosId}
            origin={origin}
            forwardHeading={forwardHeading}
            onDroneClick={(hwId) => setEditingDroneId(normalizeComparableId(hwId))}
            onRefresh={handleManualRefresh}
          />

          <DronePositionMap
            originLat={origin.lat}
            originLon={origin.lon}
            drones={configData}
            trajectoryPositionsByPosId={trajectoryPositionsByPosId}
            forwardHeading={forwardHeading}
          />
        </div>
      </div>

      {/* Replace Drone Wizard */}
      <ReplaceDroneWizard
        isOpen={replaceDroneModalOpen}
        onClose={() => {
          setReplaceDroneModalOpen(false);
          setReplaceDroneTarget(null);
        }}
        configData={configData}
        heartbeats={heartbeats}
        preselectedHwId={replaceDroneTarget}
        onSave={(updatedConfig) => {
          applyNormalizedConfigData(updatedConfig);
          toast.success('Drone replacement applied. Remember to save your changes.');
        }}
      />

      {/* Save Review Dialog */}
      <SaveReviewDialog
        isOpen={showSaveReviewDialog}
        validationReport={validationReport}
        onConfirm={handleConfirmSave}
        onCancel={handleCancelSave}
      />
    </div>
  );
};

export default MissionConfig;
