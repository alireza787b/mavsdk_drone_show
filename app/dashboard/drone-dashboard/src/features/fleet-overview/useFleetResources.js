import { useEffect, useMemo, useState } from 'react';
import { DRONE_RUNTIME_CLOCK_PROP, FIELD_NAMES, attachDroneRuntimeClock, normalizeTelemetryResponse } from '../../constants/fieldMappings';
import { normalizeComparableId } from '../../utilities/missionIdentityUtils';
import { fetchGcsResource, getFleetConfigResponse, getFleetTelemetryResponse, GCS_ROUTE_KEYS, unwrapFleetTelemetryPayload, unwrapSwarmConfigPayload } from '../../services/gcsApiService';
import { DEFAULT_FLEET_AVAILABILITY_POLICY } from './fleetAvailability';

const loadBoot = (options) => fetchGcsResource(GCS_ROUTE_KEYS.fleetNodeBootStatus, options);
const loadSwarm = (options) => fetchGcsResource(GCS_ROUTE_KEYS.swarmConfig, options);

// Each resource has one sequential owner. Failed refreshes retain explicitly
// aging evidence; a response from an obsolete route/mode cannot install itself.
export function useFleetResource(load, intervalMs, contextKey) {
  const [snapshot, setSnapshot] = useState({ response: null, error: null, loading: true });
  useEffect(() => {
    let live = true, timer, controller;
    let inFlight = false;
    setSnapshot({ response: null, error: null, loading: true });
    const poll = async () => {
      if (!live || inFlight || document.hidden) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const response = await load({ signal: controller.signal, timeout: 10000 });
        if (live) setSnapshot({ response, receivedAtMs: Date.now(), error: null, loading: false });
      } catch (error) {
        if (live && !controller.signal.aborted) setSnapshot((previous) => ({ ...previous, error, loading: false }));
      } finally {
        inFlight = false;
        if (live && !document.hidden) timer = setTimeout(poll, intervalMs);
      }
    };
    const resume = () => { clearTimeout(timer); if (!document.hidden) poll(); };
    poll();
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('focus', resume);
    return () => {
      live = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('focus', resume);
    };
  }, [load, intervalMs, contextKey]);
  return snapshot;
}

export function mergeFleetResources(config = [], telemetry = {}, boot = {}, clock = {}) {
  const configured = new Map((Array.isArray(config) ? config : []).map((row) => [normalizeComparableId(row.hw_id), row]).filter(([id]) => id));
  const samples = new Map(Object.entries(telemetry).map(([key, row]) => [normalizeComparableId(row?.hw_ID ?? row?.hw_id ?? key), row]).filter(([id]) => id));
  const nodes = new Map(Object.entries(boot.nodes || {}).map(([key, row]) => [normalizeComparableId(row?.hw_id ?? key), row]).filter(([id]) => id));
  const ids = [...new Set([...configured.keys(), ...samples.keys(), ...nodes.keys()])];
  return ids.map((id) => {
    const sample = samples.get(id);
    const row = { ...configured.get(id), ...sample, hw_ID: id, [FIELD_NAMES.HW_ID]: id, node_boot_status: nodes.get(id) || null };
    const referenceClock = sample?.[DRONE_RUNTIME_CLOCK_PROP];
    if (referenceClock) Object.defineProperty(row, DRONE_RUNTIME_CLOCK_PROP, { value: referenceClock, enumerable: false, configurable: true });
    else attachDroneRuntimeClock(row, clock);
    return row;
  });
}

export default function useFleetResources(contextKey) {
  const config = useFleetResource(getFleetConfigResponse, 30000, contextKey);
  const telemetry = useFleetResource(getFleetTelemetryResponse, 1000, contextKey);
  const boot = useFleetResource(loadBoot, 5000, contextKey);
  const swarm = useFleetResource(loadSwarm, 30000, contextKey);
  const [nowMs, setNowMs] = useState(Date.now);
  useEffect(() => {
    const tick = () => setNowMs(Date.now());
    const timer = setInterval(tick, 1000);
    window.addEventListener('focus', tick);
    return () => { clearInterval(timer); window.removeEventListener('focus', tick); };
  }, []);
  const drones = useMemo(() => {
    const clock = { receivedAtMs: telemetry.receivedAtMs,
      serverNowMs: telemetry.response?.headers?.['x-mds-server-time'] ?? telemetry.response?.headers?.date ?? null };
    const normalized = normalizeTelemetryResponse(unwrapFleetTelemetryPayload(telemetry.response?.data || {}), clock);
    return mergeFleetResources(config.response?.data, normalized, boot.response?.data, clock);
  }, [config.response, telemetry.response, telemetry.receivedAtMs, boot.response]);
  return { drones, nowMs, config, telemetry, boot,
    displayPolicy: telemetry.response?.data?.display_policy || DEFAULT_FLEET_AVAILABILITY_POLICY,
    configuredIds: (Array.isArray(config.response?.data) ? config.response.data : []).map((row) => normalizeComparableId(row.hw_id)).filter(Boolean),
    swarm: unwrapSwarmConfigPayload(swarm.response?.data), loading: config.loading && telemetry.loading };
}
