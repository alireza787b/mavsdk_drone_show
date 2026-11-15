import { useMemo } from 'react';
import { DRONE_RUNTIME_CLOCK_PROP, FIELD_NAMES, attachDroneRuntimeClock, normalizeTelemetryResponse } from '../../constants/fieldMappings';
import { normalizeComparableId } from '../../utilities/missionIdentityUtils';
import { getFleetConfigResponse, getFleetTelemetryResponse, getSwarmConfigResponse,
  unwrapFleetTelemetryPayload, unwrapSwarmConfigPayload } from '../../services/gcsApiService';
import { DEFAULT_FLEET_AVAILABILITY_POLICY } from './fleetAvailability';
import usePollingResource from '../../hooks/usePollingResource';
import { useObservationResource } from '../../contexts/ObservationContext';
import useObservationClock from '../../hooks/useObservationClock';

// Each resource has one sequential owner. Failed refreshes retain explicitly
// aging evidence; a response from an obsolete route/mode cannot install itself.
export function useFleetResource(load, intervalMs, contextKey) {
  const name = load === getFleetConfigResponse ? 'config' : load === getFleetTelemetryResponse ? 'telemetry'
    : load === getSwarmConfigResponse ? 'swarm' : null;
  const shared = useObservationResource(name, contextKey);
  const owned = usePollingResource(load, intervalMs, contextKey, !name);
  return name ? shared : owned;
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
  const config = useObservationResource('config', contextKey);
  const telemetry = useObservationResource('telemetry', contextKey);
  const boot = useObservationResource('boot', contextKey);
  const swarm = useObservationResource('swarm', contextKey);
  const nowMs = useObservationClock();
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
