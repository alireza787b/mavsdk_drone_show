import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FaExclamationTriangle, FaGlobeAmericas, FaRedoAlt, FaSatelliteDish } from 'react-icons/fa';

import Globe from '../components/Globe';
import GlobeMapView from '../components/GlobeMapView';
import IdentityDoctrineStrip from '../components/IdentityDoctrineStrip';
import ViewModeToggle, { VIEW_MODES } from '../components/map/ViewModeToggle';
import {
  ActionIconButton,
  EmptyState,
  PageShell,
  StatusBadge,
} from '../components/ui';
import '../styles/GlobeView.css';

import {
  buildTelemetryWebSocketUrl,
  getFleetConfigResponse,
  getFleetTelemetryResponse,
  unwrapFleetTelemetryPayload,
} from '../services/gcsApiService';
import {
  buildGlobeDroneViewModels,
  calculateGlobeTelemetryIntervalMs,
} from '../utilities/globeTelemetryViewModel';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';

const GlobeView = () => {
  const [drones, setDrones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isFirstLoad, setIsFirstLoad] = useState(true);
  const [error, setError] = useState(null);
  const [viewMode, setViewMode] = useState(VIEW_MODES.SCENE_3D);
  const [selectedDroneId, setSelectedDroneId] = useState(null);
  const [streamTransport, setStreamTransport] = useState('http');
  const [telemetryIntervalMs, setTelemetryIntervalMs] = useState(() => calculateGlobeTelemetryIntervalMs(0));
  const configRowsRef = useRef([]);
  const latestTelemetryPayloadRef = useRef(null);
  const wsHealthyRef = useRef(false);
  const droneCountRef = useRef(0);

  const applyTelemetryPayload = useCallback((payload, configRows = configRowsRef.current) => {
    const dronesData = buildGlobeDroneViewModels(payload, configRows);
    latestTelemetryPayloadRef.current = payload || {};
    droneCountRef.current = dronesData.length;
    setDrones(dronesData);
    setSelectedDroneId((current) => (
      current && !dronesData.some((drone) => String(drone.hw_id) === String(current))
        ? null
        : current
    ));
    setTelemetryIntervalMs((current) => {
      const next = calculateGlobeTelemetryIntervalMs(dronesData.length);
      return current === next ? current : next;
    });
    setError(null);
    setIsLoading(false);
    setIsFirstLoad(false);
  }, []);

  const fetchFleetConfig = useCallback(async () => {
    const configResponse = await getFleetConfigResponse();
    const nextConfigRows = configResponse?.data || [];
    configRowsRef.current = nextConfigRows;
    if (latestTelemetryPayloadRef.current !== null) {
      applyTelemetryPayload(latestTelemetryPayloadRef.current, nextConfigRows);
    }
  }, [applyTelemetryPayload]);

  const fetchTelemetryHttp = useCallback(async () => {
    const response = await getFleetTelemetryResponse();
    const payload = unwrapFleetTelemetryPayload(response.data);
    setStreamTransport('http');
    applyTelemetryPayload(payload, configRowsRef.current);
  }, [applyTelemetryPayload]);

  const fetchDrones = useCallback(async () => {
    try {
      if (isFirstLoad) setIsLoading(true);

      const [response, configResponse] = await Promise.allSettled([
        getFleetTelemetryResponse(),
        getFleetConfigResponse(),
      ]);
      if (response.status !== 'fulfilled') {
        throw response.reason;
      }

      const configRows = configResponse.status === 'fulfilled' ? configResponse.value?.data || [] : configRowsRef.current;
      configRowsRef.current = configRows;
      setStreamTransport('http');
      applyTelemetryPayload(unwrapFleetTelemetryPayload(response.value.data), configRows);
    } catch (err) {
      console.error('Error fetching drones:', err);
      setError('Failed to load drones. Please try again later.');
      setIsLoading(false);
    }
  }, [applyTelemetryPayload, isFirstLoad]);

  useEffect(() => {
    let cancelled = false;
    const refreshConfig = async () => {
      try {
        await fetchFleetConfig();
      } catch (err) {
        console.warn('Fleet config refresh failed:', err);
      }
    };

    refreshConfig();
    const interval = window.setInterval(() => {
      if (!cancelled) refreshConfig();
    }, 10000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [fetchFleetConfig]);

  useEffect(() => {
    const updateIntervalForVisibility = () => {
      setTelemetryIntervalMs((current) => {
        const next = calculateGlobeTelemetryIntervalMs(droneCountRef.current);
        return current === next ? current : next;
      });
    };

    document.addEventListener('visibilitychange', updateIntervalForVisibility);
    return () => {
      document.removeEventListener('visibilitychange', updateIntervalForVisibility);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timeoutId;

    const tick = async () => {
      if (!wsHealthyRef.current) {
        try {
          await fetchTelemetryHttp();
        } catch (err) {
          if (isFirstLoad) {
            console.error('Telemetry fallback fetch failed:', err);
            setError('Failed to load drones. Please try again later.');
            setIsLoading(false);
          }
        }
      }

      if (!cancelled) {
        timeoutId = window.setTimeout(tick, telemetryIntervalMs);
      }
    };

    tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timeoutId);
    };
  }, [fetchTelemetryHttp, isFirstLoad, telemetryIntervalMs]);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.WebSocket) {
      wsHealthyRef.current = false;
      setStreamTransport('http');
      return undefined;
    }

    let closed = false;
    let reconnectId;
    let socket;

    const connect = () => {
      try {
        const wsUrl = new URL(buildTelemetryWebSocketUrl());
        wsUrl.searchParams.set('interval_ms', String(telemetryIntervalMs));
        socket = new WebSocket(wsUrl.toString());
      } catch (err) {
        wsHealthyRef.current = false;
        setStreamTransport('http');
        return;
      }

      socket.onopen = () => {
        wsHealthyRef.current = true;
        setStreamTransport('ws');
      };

      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          const payload = unwrapFleetTelemetryPayload(message.data || message);
          wsHealthyRef.current = true;
          setStreamTransport('ws');
          applyTelemetryPayload(payload, configRowsRef.current);
        } catch (err) {
          console.warn('Telemetry WebSocket message parse failed:', err);
        }
      };

      socket.onerror = () => {
        wsHealthyRef.current = false;
        setStreamTransport('http');
      };

      socket.onclose = () => {
        wsHealthyRef.current = false;
        if (!closed) {
          setStreamTransport('http');
          reconnectId = window.setTimeout(connect, Math.max(2500, telemetryIntervalMs));
        }
      };
    };

    connect();

    return () => {
      closed = true;
      wsHealthyRef.current = false;
      if (reconnectId) window.clearTimeout(reconnectId);
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close();
      }
    };
  }, [applyTelemetryPayload, telemetryIntervalMs]);

  const renderDroneStrip = () => (
    <div className="globe-tactical-strip" aria-label="Live drone selection strip">
      <div className="globe-tactical-strip__drones">
        {drones.map((drone) => {
          const droneId = String(drone.hw_id);
          const selected = String(selectedDroneId || '') === droneId;
          return (
            <button
              key={droneId}
              type="button"
              className={[
                'globe-tactical-strip__chip',
                selected ? 'selected' : '',
                drone.runtime_indicator_class ? `runtime-${drone.runtime_indicator_class}` : '',
              ].filter(Boolean).join(' ')}
              style={{ '--mds-drone-marker-color': drone.marker_color || getPlotThemeColors().primary }}
              onClick={() => setSelectedDroneId(selected ? null : droneId)}
              aria-label={`Select ${formatCompactDroneIdentity(drone.pos_id, drone.hw_id, `H${drone.hw_id}`)} on the active view`}
            >
              {formatCompactDroneIdentity(drone.pos_id, drone.hw_id, `H${drone.hw_id}`)}
            </button>
          );
        })}
      </div>
    </div>
  );

  const renderChrome = (content, { showStrip = drones.length > 0 } = {}) => (
    <PageShell
      className="globe-view-container"
      eyebrow="Live visualization"
      title="Fleet Map"
      subtitle="3D scene and tactical map with adaptive telemetry transport."
      icon={<FaGlobeAmericas />}
      docsRoute="/globe-view"
      status={(
        <StatusBadge tone={streamTransport === 'ws' ? 'success' : 'info'}>
          {streamTransport === 'ws' ? 'WS' : 'HTTP'} · {(telemetryIntervalMs / 1000).toFixed(1)}s
        </StatusBadge>
      )}
    >
      <IdentityDoctrineStrip surface="globe-view" className="globe-view-doctrine" />
      <div className="globe-view-toolbar">
        <ViewModeToggle viewMode={viewMode} onChange={setViewMode} />
        {showStrip ? renderDroneStrip() : null}
      </div>
      {content}
    </PageShell>
  );

  if (isLoading) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<span className="globe-view-state__radar"><FaSatelliteDish /></span>}
        title="Loading telemetry"
        detail="Connecting to the fleet stream and mission configuration."
      />,
      { showStrip: false },
    );
  }

  if (error) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<FaExclamationTriangle />}
        title="Telemetry unavailable"
        detail={error}
        action={(
          <ActionIconButton icon={<FaRedoAlt />} label="Retry fleet telemetry load" onClick={fetchDrones}>
            Retry
          </ActionIconButton>
        )}
      />,
      { showStrip: false },
    );
  }

  if (drones.length === 0) {
    return renderChrome(
      <EmptyState
        className="globe-view-state"
        icon={<FaSatelliteDish />}
        title="No telemetry targets"
        detail="No configured or live drones are available for the current runtime."
      />,
      { showStrip: false },
    );
  }

  return renderChrome(
    <>
      {viewMode === VIEW_MODES.SCENE_3D ? (
        <Globe drones={drones} selectedDroneId={selectedDroneId} onSelectDrone={setSelectedDroneId} />
      ) : (
        <GlobeMapView drones={drones} selectedDroneId={selectedDroneId} onSelectDrone={setSelectedDroneId} />
      )}
    </>,
  );
};

export default GlobeView;
