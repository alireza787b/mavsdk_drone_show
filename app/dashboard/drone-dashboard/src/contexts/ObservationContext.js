import React, { createContext, useContext, useMemo, useSyncExternalStore } from 'react';
import ObservationResource from '../services/observationResource';
import { buildTelemetryWebSocketUrl, fetchGcsResource, getFleetConfigResponse, getFleetTelemetryResponse,
  getUnifiedGitStatusResponse, GCS_ROUTE_KEYS } from '../services/gcsApiService';

const Context = createContext(null);
const disabledSnapshot = Object.freeze({ response: null, error: null, loading: false, consecutiveFailures: 0 });
const disabled = { subscribe: () => () => {}, getSnapshot: () => disabledSnapshot, refresh: () => {} };
const definitions = {
  config: [getFleetConfigResponse, 30000],
  swarm: [options => fetchGcsResource(GCS_ROUTE_KEYS.swarmConfig, options), 30000],
  boot: [options => fetchGcsResource(GCS_ROUTE_KEYS.fleetNodeBootStatus, options), 5000],
  runtime: [options => fetchGcsResource(GCS_ROUTE_KEYS.systemRuntimeStatus, options), 15000],
  heartbeats: [options => fetchGcsResource(GCS_ROUTE_KEYS.fleetHeartbeats, options), 5000],
  git: [async options => {
    const response = await getUnifiedGitStatusResponse(options);
    if (!response?.data || !Number.isInteger(response.data.needs_sync_count)
        || response.data.needs_sync_count < 0 || !Number.isInteger(response.data.unknown_count ?? 0)) throw new Error('Software revision status unavailable');
    return response;
  }, 10000],
  telemetry: [options => getFleetTelemetryResponse({ ...options, params: { protocol_version: 1 } }), 1000],
};

export function createObservationRegistry(seed = {}) {
  const resources = new Map(Object.entries(seed));
  return {
    get(name) {
      if (!name) return disabled;
      if (!resources.has(name)) {
        if (!definitions[name]) throw new Error(`Unknown shared resource: ${name}`);
        const [load, intervalMs] = definitions[name];
        resources.set(name, new ObservationResource(load, { intervalMs,
          streamUrl: name === 'telemetry' && typeof WebSocket !== 'undefined' ? () => {
            const url = new URL(buildTelemetryWebSocketUrl());
            url.searchParams.set('protocol_version', '1');
            return url.toString();
          } : null }));
      }
      return resources.get(name);
    },
    stop() { resources.forEach(resource => resource.stop()); },
  };
}

/** Provider is remounted for each authenticated operator/runtime context. */
export function ObservationProvider({ children }) {
  const parent = useContext(Context);
  // Mode-scoped children reset aircraft data without opening another runtime
  // poller. The outer authenticated owner retains only this mode-independent read.
  const registry = useMemo(() => createObservationRegistry(parent ? { runtime: parent.get('runtime') } : {}), [parent]);
  return <Context.Provider value={registry}>{children}</Context.Provider>;
}

export function useObservationResource(name, contextKey = '') {
  const shared = useContext(Context);
  // Standalone workspaces/tests retain a scoped owner, never a module-global
  // cache that could cross authenticated contexts.
  const local = useMemo(createObservationRegistry, [contextKey]);
  const resource = (shared || local).get(name);
  const snapshot = useSyncExternalStore(resource.subscribe, resource.getSnapshot, resource.getSnapshot);
  return useMemo(() => ({ ...snapshot, refresh: resource.refresh }), [resource, snapshot]);
}
