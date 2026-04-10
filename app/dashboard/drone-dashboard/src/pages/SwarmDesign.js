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
import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';
import '../styles/SwarmDesign.css';
import {
  GCS_ROUTE_KEYS,
  getFleetConfigResponse,
  getSwarmConfigResponse,
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
  const requestedDroneId = String(searchParams.get('drone') || '').trim();
  const { data: telemetryById = {} } = useNormalizedTelemetry(GCS_ROUTE_KEYS.fleetTelemetry, 2000);

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

        const normalizedConfig = configResponse.data
          .map((entry) => normalizeConfigDrone(entry))
          .filter(Boolean);
        const normalizedSwarm = unwrapSwarmConfigPayload(swarmResponse.data)
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

    const normalizedConfig = configResponse.data
      .map((entry) => normalizeConfigDrone(entry))
      .filter(Boolean);
    const normalizedSwarm = unwrapSwarmConfigPayload(swarmResponse.data)
      .map((entry) => normalizeSwarmAssignment(entry))
      .filter(Boolean);
    const { assignments } = buildWorkingSwarmAssignments(normalizedConfig, normalizedSwarm);

    setConfigData(normalizedConfig);
    setServerSwarmData(normalizedSwarm);
    setBaselineAssignments(assignments);
    setWorkingAssignments(assignments);
  };

  const handleAssignmentChange = (hwId, patch) => {
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

    if (!window.confirm('Revert all staged Smart Swarm changes back to the last loaded configuration?')) {
      return;
    }

    setWorkingAssignments(baselineAssignments);
    toast.info('Reverted local Smart Swarm changes.');
  };

  const saveSwarmData = async (withCommit) => {
    setSaving(true);

    try {
      const response = await saveSwarmConfigResponse(
        toSwarmApiPayload(workingAssignments),
        { commit: withCommit }
      );

      toast.success(response.data.message || 'Smart Swarm configuration saved successfully.');
      await refreshFromServer();
    } catch (error) {
      console.error('Failed to save Smart Swarm configuration:', error);
      toast.error('Failed to save Smart Swarm configuration.');
    } finally {
      setSaving(false);
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

    if (!hasStagedChanges && !hasPendingSync) {
      toast.info('No Smart Swarm changes are staged for update.');
      return;
    }

    const summaryLines = [
      `${viewModel.summary.totalDrones} drones across ${viewModel.summary.clusterCount} cluster${viewModel.summary.clusterCount === 1 ? '' : 's'}`,
      `${viewModel.summary.topLeaderCount} top leaders, ${viewModel.summary.relayLeaderCount} relay leaders, ${viewModel.summary.followerCount} followers`,
      `${dirtyIds.length} staged assignment change${dirtyIds.length === 1 ? '' : 's'}`,
      `${syncChanges.addedIds.length + syncChanges.removedIds.length} fleet sync update${syncChanges.addedIds.length + syncChanges.removedIds.length === 1 ? '' : 's'}`,
      `${viewModel.summary.attentionCount} drone${viewModel.summary.attentionCount === 1 ? '' : 's'} flagged for operator attention`,
    ];

    if (!window.confirm(
      `${withCommit ? 'Commit' : 'Update'} Smart Swarm assignments?\n\n${summaryLines.map((line) => `- ${line}`).join('\n')}`
    )) {
      return;
    }

    saveSwarmData(withCommit);
  };

  const summaryCards = [
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

  return (
    <div className="swarm-design-page">
      <header className="swarm-design-hero">
        <div className="swarm-design-hero__copy">
          <span className="swarm-design-hero__eyebrow">Smart Swarm Control Surface</span>
          <h1>Operational Swarm Design</h1>
          <p>
            Review live follow ownership cluster by cluster, then commit only when the hardware graph is clean.
          </p>
        </div>

        <div className="swarm-design-hero__actions">
          <button
            type="button"
            className="swarm-action-button update"
            onClick={() => confirmAndSave(false)}
            disabled={saving || hasBlockingIssues || hasIncompleteInputs || (!hasStagedChanges && !hasPendingSync)}
          >
            <FaSyncAlt />
            Update Swarm
          </button>
          <button
            type="button"
            className="swarm-action-button commit"
            onClick={() => confirmAndSave(true)}
            disabled={saving || hasBlockingIssues || hasIncompleteInputs || (!hasStagedChanges && !hasPendingSync)}
          >
            <FaCloudUploadAlt />
            Commit Changes
          </button>
          <label className="swarm-action-button import">
            <FaUpload />
            Import JSON / CSV
            <input type="file" accept=".json,.csv" onChange={handleImport} />
          </label>
          <button type="button" className="swarm-action-button secondary" onClick={handleJsonExport} disabled={workingAssignments.length === 0}>
            <FaDownload />
            Export JSON
          </button>
          <button type="button" className="swarm-action-button secondary" onClick={handleCsvExport} disabled={workingAssignments.length === 0}>
            <FaDownload />
            Export CSV
          </button>
          <button type="button" className="swarm-action-button ghost" onClick={handleRevert} disabled={!hasStagedChanges}>
            <FaUndo />
            Revert Local
          </button>
        </div>
      </header>

      <IdentityDoctrineStrip surface="swarm-design" />

      <section className="swarm-summary-grid">
        {summaryCards.map((card) => (
          <div key={card.label} className={`swarm-summary-card ${card.tone}`}>
            <span className="swarm-summary-card__icon">{card.icon}</span>
            <span className="swarm-summary-card__value">{card.value}</span>
            <span className="swarm-summary-card__label">{card.label}</span>
          </div>
        ))}
      </section>

      <section className="swarm-status-strip">
        <div className="swarm-status-card identity">
          <strong>Identity model</strong>
          <span>Slot reassignments change show-slot assignment, not follow-chain targeting.</span>
        </div>

        {hasPendingSync && (
          <div className="swarm-status-card sync">
            <strong>Fleet sync pending</strong>
            <span>
              {syncChanges.addedIds.length > 0 && `Add default assignments for drones ${syncChanges.addedIds.join(', ')}. `}
              {syncChanges.removedIds.length > 0 && `Prune legacy assignments for drones ${syncChanges.removedIds.join(', ')}.`}
            </span>
          </div>
        )}

        {viewModel.summary.roleSwapCount > 0 && (
          <div className="swarm-status-card note">
            <strong>Slot reassignments active</strong>
            <span>{viewModel.summary.roleSwapCount} drone{viewModel.summary.roleSwapCount === 1 ? '' : 's'} are flying a different show slot than their hardware ID.</span>
          </div>
        )}

        {(hasBlockingIssues || hasIncompleteInputs) && (
          <div className="swarm-status-card attention">
            <strong>Save blocked</strong>
            <span>
              {hasBlockingIssues ? 'Resolve self-follow, missing leader, or cycle issues.' : ''}
              {hasBlockingIssues && hasIncompleteInputs ? ' ' : ''}
              {hasIncompleteInputs ? 'Complete partial offset values before update or commit.' : ''}
            </span>
          </div>
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
              <h2>Assignment Cards</h2>
              <p>Grouped by top leader so operators can audit follow chains cluster by cluster.</p>
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
              <div className="swarm-empty-state">
                <strong>No matching drones</strong>
                <span>Try a different term or a scoped query like pos 1-5, hw 2,4, or a callsign. {DRONE_SEARCH_HELP_TEXT}</span>
              </div>
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
              <h2>Follow Chain Graph</h2>
              <p>Arrows flow leader to follower. Click any node to inspect its upstream and downstream chain.</p>
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
                <div className="swarm-empty-state compact">
                  <strong>No drone selected</strong>
                  <span>Select a graph node or assignment card to inspect its details.</span>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>

      <section className="swarm-panel swarm-panel--plots">
        <div className="swarm-panel__header">
          <div>
            <h2>Formation Analysis</h2>
            <p>
              Cluster plots are relative previews for design review. They are not live telemetry views. Selecting a
              specific cluster here also sets the cluster-scoped runtime target. &quot;All executable clusters&quot; remains
              analysis-only.
            </p>
          </div>
        </div>

        <SwarmPlots
          swarmData={workingAssignments}
          configData={configData}
          selectedClusterId={selectedClusterId}
          onSelectedClusterChange={setSelectedClusterId}
        />
      </section>
    </div>
  );
}

export default SwarmDesign;
