// src/pages/Overview.js
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import { FaChevronDown } from 'react-icons/fa';
import CommandSender from '../components/CommandSender';
import ClusterScopeBar from '../components/ClusterScopeBar';
import DroneWidget from '../components/DroneWidget';
import ExpandedDronePortal from '../components/ExpandedDronePortal';
import useFetch from '../hooks/useFetch';
import {
  DRONE_RUNTIME_CLOCK_PROP,
  FIELD_NAMES,
  attachDroneRuntimeClock,
  normalizeTelemetryResponse,
} from '../constants/fieldMappings';
import { normalizeComparableId } from '../utilities/missionIdentityUtils';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import {
  DRONE_SEARCH_PLACEHOLDER,
  matchesDroneSearchQuery,
} from '../utilities/dronePresentation';
import {
  buildClusterScopeOptions,
  buildSwarmViewModel,
  filterClustersByScope,
} from '../utilities/swarmDesignUtils';
import {
  GCS_ROUTE_KEYS,
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
  unwrapSwarmConfigPayload,
} from '../services/gcsApiService';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [configByHwId, setConfigByHwId] = useState({});
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [droneQuery, setDroneQuery] = useState('');
  const [cardFilter, setCardFilter] = useState('active');
  const [clusterScope, setClusterScope] = useState('all');
  const [commandTargetMode, setCommandTargetMode] = useState('all');
  const [commandSelectedDrones, setCommandSelectedDrones] = useState([]);
  const [commandClusterScope, setCommandClusterScope] = useState('');
  const [fleetPanelExpanded, setFleetPanelExpanded] = useState(false);
  const [originRect, setOriginRect] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);
  const droneRefs = useRef({});
  const commandDispatchRef = useRef(null);
  const { data: swarmDataFetched } = useFetch(GCS_ROUTE_KEYS.swarmConfig);

  useEffect(() => {
    let active = true;

    const loadConfig = async () => {
      try {
        const response = await getFleetConfigResponse();
        if (!active || !Array.isArray(response.data)) {
          return;
        }

        const nextConfigByHwId = response.data.reduce((accumulator, entry) => {
          const hwId = normalizeComparableId(entry?.hw_id);
          if (hwId) {
            accumulator[hwId] = entry;
          }
          return accumulator;
        }, {});

        setConfigByHwId(nextConfigByHwId);
      } catch (loadError) {
        console.warn('Failed to load config metadata for overview cards:', loadError);
      }
    };

    loadConfig();
    const interval = setInterval(loadConfig, 30000);

    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await getFleetTelemetryResponse();
        const clockMeta = {
          receivedAtMs: Date.now(),
          serverNowMs: response.headers?.['x-mds-server-time'] ?? response.headers?.date ?? null,
        };
        const normalizedTelemetry = normalizeTelemetryResponse(
          unwrapFleetTelemetryPayload(response.data),
          clockMeta
        );
        const dronesArray = Object.keys(normalizedTelemetry).map((hw_ID) => {
          const mergedDrone = {
            ...(configByHwId[normalizeComparableId(hw_ID)] || {}),
            hw_ID,
            [FIELD_NAMES.HW_ID]: hw_ID,
            ...normalizedTelemetry[hw_ID],
          };
          const runtimeClock = normalizedTelemetry[hw_ID]?.[DRONE_RUNTIME_CLOCK_PROP];
          if (runtimeClock) {
            Object.defineProperty(mergedDrone, DRONE_RUNTIME_CLOCK_PROP, {
              value: runtimeClock,
              configurable: true,
              writable: true,
              enumerable: false,
            });
            return mergedDrone;
          }
          return attachDroneRuntimeClock(mergedDrone, clockMeta);
        });

        const validDrones = dronesArray.filter(
          (drone) =>
            drone.position_lat !== undefined &&
            drone.position_long !== undefined &&
            drone.position_alt !== undefined &&
            drone.battery_voltage !== undefined
        );

        const invalidDrones = dronesArray.filter(
          (drone) => !validDrones.includes(drone)
        );

        setDrones(validDrones);
        setError(null);
        setNotification(null);

        if (invalidDrones.length > 0) {
          setNotification(`${invalidDrones.length} drones have incomplete data.`);
        }
      } catch (error) {
        setError('Failed to fetch data from the backend.');
        setNotification('Network issue, retrying...');
      }
    };

    fetchData();
    const pollingInterval = setInterval(fetchData, 1000);

    return () => {
      clearInterval(pollingInterval);
    };
  }, [configByHwId]);

  const toggleDroneDetails = (drone) => {
    if (expandedDrone && expandedDrone.hw_ID === drone.hw_ID) {
      setExpandedDrone(null);
      setOriginRect(null);
    } else {
      // Get the position of the clicked drone widget for animation
      const droneElement = droneRefs.current[drone.hw_ID];
      if (droneElement) {
        const rect = droneElement.getBoundingClientRect();
        setOriginRect(rect);
      }
      setExpandedDrone(drone);
    }
  };

  const closeExpandedDrone = () => {
    setExpandedDrone(null);
    setOriginRect(null);
  };

  const fleetSummary = React.useMemo(() => {
    const summary = {
      total: drones.length,
      online: 0,
      degraded: 0,
      unavailable: 0,
      ready: 0,
      armed: 0,
    };

    drones.forEach((drone) => {
      const runtimeStatus = getDroneRuntimeStatus(drone, Date.now());
      const readiness = getDroneReadinessModel(drone, runtimeStatus);

      if (runtimeStatus.level === 'online') {
        summary.online += 1;
      } else if (runtimeStatus.level === 'degraded') {
        summary.degraded += 1;
      } else {
        summary.unavailable += 1;
      }

      if (readiness.isReady) {
        summary.ready += 1;
      }

      if (drone?.[FIELD_NAMES.IS_ARMED]) {
        summary.armed += 1;
      }
    });

    return summary;
  }, [drones]);

  const swarmAssignments = React.useMemo(
    () => unwrapSwarmConfigPayload(swarmDataFetched),
    [swarmDataFetched]
  );

  const swarmViewModel = React.useMemo(
    () => buildSwarmViewModel(swarmAssignments, drones),
    [drones, swarmAssignments]
  );
  const clusterScopeOptions = React.useMemo(
    () => buildClusterScopeOptions(swarmViewModel?.clusters || [], drones.length),
    [drones.length, swarmViewModel?.clusters]
  );
  const visibleClusters = React.useMemo(
    () => filterClustersByScope(swarmViewModel?.clusters || [], clusterScope),
    [clusterScope, swarmViewModel?.clusters]
  );
  const visibleClusterHwIds = React.useMemo(() => {
    if (clusterScope === 'all') {
      return null;
    }

    return new Set(
      visibleClusters.flatMap((cluster) => cluster.drones.map((drone) => normalizeComparableId(drone.hw_id)))
    );
  }, [clusterScope, visibleClusters]);

  const filteredDrones = React.useMemo(() => {
    const nowMs = Date.now();

    return drones.filter((drone) => {
      const hwId = normalizeComparableId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID);
      if (visibleClusterHwIds && !visibleClusterHwIds.has(hwId)) {
        return false;
      }

      if (!matchesDroneSearchQuery(drone, droneQuery)) {
        return false;
      }

      const runtimeStatus = getDroneRuntimeStatus(drone, nowMs);
      const readiness = getDroneReadinessModel(drone, runtimeStatus);

      switch (cardFilter) {
        case 'active':
          return runtimeStatus.level === 'online'
            || runtimeStatus.level === 'degraded'
            || runtimeStatus.indicatorClass === 'lost';
        case 'attention':
          return runtimeStatus.level !== 'online' || !readiness.isReady;
        case 'ready':
          return readiness.isReady;
        case 'armed':
          return Boolean(drone?.[FIELD_NAMES.IS_ARMED]);
        case 'online':
          return runtimeStatus.level === 'online';
        default:
          return true;
      }
    });
  }, [cardFilter, droneQuery, drones, visibleClusterHwIds]);
  const filteredDroneIds = React.useMemo(
    () => filteredDrones
      .map((drone) => normalizeComparableId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID))
      .filter(Boolean),
    [filteredDrones],
  );
  const commandClusterTargetIds = React.useMemo(() => {
    if (!swarmViewModel || !commandClusterScope) {
      return [];
    }

    return Array.from(
      new Set(
        filterClustersByScope(swarmViewModel.clusters, commandClusterScope)
          .flatMap((cluster) => cluster.drones.map((drone) => normalizeComparableId(drone.hw_id)))
          .filter(Boolean),
      ),
    );
  }, [commandClusterScope, swarmViewModel]);
  const commandScopeIds = React.useMemo(() => {
    if (commandTargetMode === 'selected') {
      return commandSelectedDrones.map((value) => String(value));
    }

    if (commandTargetMode === 'cluster') {
      return commandClusterTargetIds;
    }

    return [];
  }, [commandClusterTargetIds, commandSelectedDrones, commandTargetMode]);
  const commandScopeSet = React.useMemo(
    () => new Set(commandScopeIds.map((value) => String(value))),
    [commandScopeIds],
  );
  const visibleScopeMatchesSelection = React.useMemo(() => {
    if (commandTargetMode !== 'selected' || filteredDroneIds.length !== commandSelectedDrones.length) {
      return false;
    }

    const selectedSet = new Set(commandSelectedDrones.map((value) => String(value)));
    return filteredDroneIds.every((value) => selectedSet.has(String(value)));
  }, [commandSelectedDrones, commandTargetMode, filteredDroneIds]);
  const commandScopeSummary = React.useMemo(() => {
    if (commandTargetMode === 'selected') {
      return `Dispatch · ${commandSelectedDrones.length} selected`;
    }

    if (commandTargetMode === 'cluster') {
      const activeCluster = clusterScopeOptions.find((option) => String(option.id) === String(commandClusterScope));
      if (activeCluster) {
        return `Dispatch · ${activeCluster.label}`;
      }

      return `Dispatch · Cluster`;
    }

    return `Dispatch · All ${drones.length}`;
  }, [clusterScopeOptions, commandClusterScope, commandSelectedDrones.length, commandTargetMode, drones.length]);
  const applyVisibleCardsToCommandScope = React.useCallback(() => {
    if (filteredDroneIds.length === 0) {
      return;
    }

    setCommandTargetMode('selected');
    setCommandSelectedDrones(filteredDroneIds);
  }, [filteredDroneIds]);
  const focusCommandDispatch = React.useCallback(() => {
    commandDispatchRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    });
  }, []);
  const toggleDroneCommandScope = React.useCallback((droneId) => {
    const normalizedDroneId = normalizeComparableId(droneId);
    if (!normalizedDroneId) {
      return;
    }

    const allDroneIds = drones
      .map((drone) => normalizeComparableId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID))
      .filter(Boolean);
    const baseScopeIds = commandTargetMode === 'selected'
      ? commandSelectedDrones.map((value) => String(value))
      : commandTargetMode === 'cluster'
        ? commandClusterTargetIds
        : allDroneIds;
    const baseScopeSet = new Set(baseScopeIds.map((value) => String(value)));

    if (baseScopeSet.has(normalizedDroneId)) {
      baseScopeSet.delete(normalizedDroneId);
    } else {
      baseScopeSet.add(normalizedDroneId);
    }

    const orderedNextScope = allDroneIds.filter((value) => baseScopeSet.has(value));
    setCommandTargetMode('selected');
    setCommandSelectedDrones(orderedNextScope);
  }, [commandClusterTargetIds, commandSelectedDrones, commandTargetMode, drones]);

  React.useEffect(() => {
    if (commandTargetMode !== 'selected') {
      return;
    }

    const validDroneIds = new Set(
      drones
        .map((drone) => normalizeComparableId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID))
        .filter(Boolean),
    );

    setCommandSelectedDrones((prev) => prev.filter((value) => validDroneIds.has(String(value))));
  }, [commandTargetMode, drones]);
  React.useEffect(() => {
    if (commandTargetMode !== 'cluster') {
      return;
    }

    if (!clusterScopeOptions.some((option) => String(option.id) === String(commandClusterScope))) {
      const fallbackCluster = clusterScopeOptions.find((option) => option.id !== 'all' && option.id !== 'attention');
      setCommandClusterScope(fallbackCluster ? String(fallbackCluster.id) : '');
    }
  }, [clusterScopeOptions, commandClusterScope, commandTargetMode]);

  const toggleFleetPanel = () => {
    setFleetPanelExpanded((current) => !current);
  };

  const handleFleetPanelKeyDown = (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') {
      return;
    }

    event.preventDefault();
    toggleFleetPanel();
  };

  return (
    <div className="overview-container">
      <header className="overview-header">
        <div className="overview-header__copy">
          <p className="overview-eyebrow">Operations dashboard</p>
          <h1>Fleet Command Overview</h1>
          <p className="overview-description">
            Live status, command scope, and launch readiness for the active fleet.
          </p>
        </div>
        <div
          className={`overview-summary-panel ${fleetPanelExpanded ? 'is-open' : ''}`}
          role="button"
          tabIndex={0}
          onClick={toggleFleetPanel}
          onKeyDown={handleFleetPanelKeyDown}
          aria-expanded={fleetPanelExpanded}
          aria-label={fleetPanelExpanded ? 'Hide fleet details' : 'Show fleet details'}
        >
          <div className="overview-summary-strip" role="list" aria-label="Fleet overview">
            <article className="overview-summary-pill" role="listitem">
              <span className="overview-summary-pill__label">Fleet</span>
              <strong>{fleetSummary.total}</strong>
            </article>
            <article className="overview-summary-pill" role="listitem">
              <span className="overview-summary-pill__label">Online</span>
              <strong>{fleetSummary.online}</strong>
            </article>
            <article className="overview-summary-pill" role="listitem">
              <span className="overview-summary-pill__label">Ready</span>
              <strong>{fleetSummary.ready}</strong>
            </article>
            <article className="overview-summary-pill" role="listitem">
              <span className="overview-summary-pill__label">Armed</span>
              <strong>{fleetSummary.armed}</strong>
            </article>
          </div>
          <div className={`overview-summary-toggle ${fleetPanelExpanded ? 'is-open' : ''}`} aria-hidden="true">
            <span>{fleetPanelExpanded ? 'Details' : 'Summary'}</span>
            <FaChevronDown className="overview-summary-toggle-icon" />
          </div>
          {fleetPanelExpanded && (
            <div className="overview-summary-grid" role="list" aria-label="Expanded fleet overview">
              <article className="overview-summary-card" role="listitem">
                <span className="overview-summary-card__label">Visible drones</span>
                <strong>{fleetSummary.total}</strong>
                <small>Card wall</small>
              </article>
              <article className="overview-summary-card" role="listitem">
                <span className="overview-summary-card__label">Online link</span>
                <strong>{fleetSummary.online}</strong>
                <small>{fleetSummary.degraded} delayed · {fleetSummary.unavailable} unavailable</small>
              </article>
              <article className="overview-summary-card" role="listitem">
                <span className="overview-summary-card__label">Ready status</span>
                <strong>{fleetSummary.ready}</strong>
                <small>{fleetSummary.total - fleetSummary.ready} need review</small>
              </article>
              <article className="overview-summary-card" role="listitem">
                <span className="overview-summary-card__label">Armed aircraft</span>
                <strong>{fleetSummary.armed}</strong>
                <small>{Math.max(fleetSummary.total - fleetSummary.armed, 0)} disarmed</small>
              </article>
            </div>
          )}
        </div>
      </header>

      <div
        className="mission-trigger-section"
        ref={commandDispatchRef}
        id="command-dispatch"
      >
        <CommandSender
          drones={drones}
          swarmData={swarmAssignments}
          targetMode={commandTargetMode}
          onTargetModeChange={setCommandTargetMode}
          selectedDrones={commandSelectedDrones}
          onSelectedDronesChange={setCommandSelectedDrones}
          selectedClusterScope={commandClusterScope}
          onSelectedClusterScopeChange={setCommandClusterScope}
        />
      </div>

      <div className="connected-drones-header">
        <div>
          <h2>Fleet</h2>
          <p>Filter the card wall, then apply the visible subset to dispatch when needed.</p>
        </div>
        <div className="connected-drones-header__actions">
          <span className="connected-drones-count">
            {filteredDrones.length}/{fleetSummary.total} card{fleetSummary.total === 1 ? '' : 's'} visible
          </span>
          <button
            type="button"
            className="connected-drones-scope"
            title="Jump to command dispatch scope controls"
            onClick={focusCommandDispatch}
            aria-controls="command-dispatch"
          >
            {commandScopeSummary}
          </button>
          <button
            type="button"
            className="connected-drones-action"
            onClick={applyVisibleCardsToCommandScope}
            disabled={filteredDroneIds.length === 0 || visibleScopeMatchesSelection}
            title={visibleScopeMatchesSelection
              ? 'The currently visible fleet already matches the manual dispatch scope.'
              : 'Copy the currently visible fleet cards into the manual dispatch scope.'}
          >
            {visibleScopeMatchesSelection ? 'Visible in dispatch' : 'Use visible'}
          </button>
        </div>
      </div>

      <div className="overview-fleet-toolbar">
        <label className="overview-fleet-toolbar__search">
          <span>Search fleet</span>
          <input
            type="search"
            value={droneQuery}
            onChange={(event) => setDroneQuery(event.target.value)}
            placeholder={DRONE_SEARCH_PLACEHOLDER}
            aria-label="Search fleet cards by position, hardware ID, or callsign"
          />
        </label>
        <div className="overview-fleet-toolbar__filters" role="tablist" aria-label="Fleet card filters">
          {[
            ['active', 'Active'],
            ['attention', 'Attention'],
            ['ready', 'Ready'],
            ['online', 'Online'],
            ['armed', 'Armed'],
            ['all', 'All'],
          ].map(([value, label]) => (
            <button
              key={value}
              type="button"
              className={`overview-fleet-toolbar__filter ${cardFilter === value ? 'active' : ''}`}
              onClick={() => setCardFilter(value)}
            >
              {label}
            </button>
          ))}
        </div>
        {clusterScopeOptions.length > 1 && (
          <ClusterScopeBar
            label="Visible clusters"
            options={clusterScopeOptions}
            selectedId={clusterScope}
            onSelect={setClusterScope}
            summary="Top-leader scopes keep large fleets readable."
          />
        )}
      </div>

      {notification && <div className="notification">{notification}</div>}
      {error && <div className="error-message">{error}</div>}

      <div className="drone-list">
        {drones.length === 0 && !error && (
          <div className="overview-empty-state">
            <strong>No valid drone data is available.</strong>
            <span>When telemetry resumes, aircraft cards will populate here automatically.</span>
          </div>
        )}
        {drones.length > 0 && filteredDrones.length === 0 && !error && (
          <div className="overview-empty-state">
            <strong>No drones match the current filters.</strong>
            <span>Search supports free text and scoped queries like pos 1-5 or hw 2,4.</span>
          </div>
        )}
        {filteredDrones.map((drone) => (
          <div
            key={drone.hw_ID}
            className="drone-list__item"
            ref={(el) => droneRefs.current[drone.hw_ID] = el}
          >
            <DroneWidget
              drone={drone}
              isExpanded={expandedDrone && expandedDrone.hw_ID === drone.hw_ID}
              toggleDroneDetails={toggleDroneDetails}
              setSelectedDrone={setSelectedDrone}
              commandScopeState={
                commandTargetMode === 'all'
                  ? 'all'
                  : commandScopeSet.has(normalizeComparableId(drone?.[FIELD_NAMES.HW_ID] || drone?.hw_ID))
                    ? (commandTargetMode === 'cluster' ? 'cluster' : 'selected')
                    : 'out'
              }
              onToggleCommandScope={toggleDroneCommandScope}
            />
          </div>
        ))}
      </div>

      {/* Expanded Drone Portal */}
      <ExpandedDronePortal
        drone={expandedDrone}
        isOpen={!!expandedDrone}
        onClose={closeExpandedDrone}
        originRect={originRect}
      />
    </div>
  );
};

Overview.propTypes = {
  setSelectedDrone: PropTypes.func.isRequired,
};

export default Overview;
