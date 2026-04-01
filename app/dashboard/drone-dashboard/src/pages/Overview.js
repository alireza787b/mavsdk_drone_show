// src/pages/Overview.js
import React, { useState, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import axios from 'axios';
import CommandSender from '../components/CommandSender';
import DroneWidget from '../components/DroneWidget';
import ExpandedDronePortal from '../components/ExpandedDronePortal';
import {
  FIELD_NAMES,
  attachDroneRuntimeClock,
  extractServerNowMs,
  normalizeTelemetryResponse,
} from '../constants/fieldMappings';
import { normalizeComparableId } from '../utilities/missionIdentityUtils';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import { matchesDroneSearchQuery } from '../utilities/dronePresentation';
import { getBackendURL, getTelemetryURL } from '../utilities/utilities';
import '../styles/Overview.css';

const Overview = ({ setSelectedDrone }) => {
  const [drones, setDrones] = useState([]);
  const [configByHwId, setConfigByHwId] = useState({});
  const [expandedDrone, setExpandedDrone] = useState(null);
  const [droneQuery, setDroneQuery] = useState('');
  const [cardFilter, setCardFilter] = useState('all');
  const [originRect, setOriginRect] = useState(null);
  const [error, setError] = useState(null);
  const [notification, setNotification] = useState(null);
  const droneRefs = useRef({});

  useEffect(() => {
    const backendURL = getBackendURL();
    let active = true;

    const loadConfig = async () => {
      try {
        const response = await axios.get(`${backendURL}/get-config-data`);
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
    const url = getTelemetryURL();
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        const clockMeta = {
          receivedAtMs: Date.now(),
          serverNowMs: extractServerNowMs(response.headers),
        };
        const normalizedTelemetry = normalizeTelemetryResponse(response.data || {}, clockMeta);
        const dronesArray = Object.keys(normalizedTelemetry).map((hw_ID) => attachDroneRuntimeClock({
          ...(configByHwId[normalizeComparableId(hw_ID)] || {}),
          hw_ID,
          ...normalizedTelemetry[hw_ID],
        }, clockMeta));

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

  const filteredDrones = React.useMemo(() => {
    const nowMs = Date.now();

    return drones.filter((drone) => {
      if (!matchesDroneSearchQuery(drone, droneQuery)) {
        return false;
      }

      const runtimeStatus = getDroneRuntimeStatus(drone, nowMs);
      const readiness = getDroneReadinessModel(drone, runtimeStatus);

      switch (cardFilter) {
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
  }, [cardFilter, droneQuery, drones]);

  return (
    <div className="overview-container">
      <header className="overview-header">
        <div className="overview-header__copy">
          <p className="overview-eyebrow">Operations dashboard</p>
          <h1>Fleet Command Overview</h1>
          <p className="overview-description">
            Live aircraft status, command dispatch, and launch readiness for the active control session.
          </p>
        </div>
        <div className="overview-summary-grid" role="list" aria-label="Fleet overview">
          <article className="overview-summary-card" role="listitem">
            <span className="overview-summary-card__label">Visible drones</span>
            <strong>{fleetSummary.total}</strong>
            <small>Telemetry-valid cards in view</small>
          </article>
          <article className="overview-summary-card" role="listitem">
            <span className="overview-summary-card__label">Online link</span>
            <strong>{fleetSummary.online}</strong>
            <small>{fleetSummary.degraded} delayed, {fleetSummary.unavailable} unavailable</small>
          </article>
          <article className="overview-summary-card" role="listitem">
            <span className="overview-summary-card__label">Ready status</span>
            <strong>{fleetSummary.ready}</strong>
            <small>{fleetSummary.total - fleetSummary.ready} need review or are blocked</small>
          </article>
          <article className="overview-summary-card" role="listitem">
            <span className="overview-summary-card__label">Armed aircraft</span>
            <strong>{fleetSummary.armed}</strong>
            <small>{Math.max(fleetSummary.total - fleetSummary.armed, 0)} disarmed</small>
          </article>
        </div>
      </header>

      <div className="mission-trigger-section">
        <CommandSender drones={drones} />
      </div>

      <div className="connected-drones-header">
        <div>
          <h2>Connected Drones</h2>
          <p>Filter the card wall without changing dispatch scope in Command Control.</p>
        </div>
        <span className="connected-drones-count">
          {filteredDrones.length}/{fleetSummary.total} card{fleetSummary.total === 1 ? '' : 's'} visible
        </span>
      </div>

      <div className="overview-fleet-toolbar">
        <label className="overview-fleet-toolbar__search">
          <span>Search fleet</span>
          <input
            type="search"
            value={droneQuery}
            onChange={(event) => setDroneQuery(event.target.value)}
            placeholder="Search Pos, HW, callsign"
            aria-label="Search fleet cards by position, hardware ID, or callsign"
          />
        </label>
        <div className="overview-fleet-toolbar__filters" role="tablist" aria-label="Fleet card filters">
          {[
            ['all', 'All'],
            ['attention', 'Attention'],
            ['ready', 'Ready'],
            ['online', 'Online'],
            ['armed', 'Armed'],
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
        <p className="overview-fleet-toolbar__note">
          Visibility filters affect the card wall only. Command scope stays explicit inside Command Control.
        </p>
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
            <span>Search supports position, hardware ID, and promoted callsign or alias fields.</span>
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
