import { useCallback, useMemo } from 'react';
import { extractServerNowMs } from '../constants/fieldMappings';
import { fetchGcsResource, GCS_ROUTE_KEYS, resolveGcsRouteKey } from '../services/gcsApiService';
import { useObservationResource } from '../contexts/ObservationContext';
import usePollingResource from './usePollingResource';

const sharedResources = {
  [GCS_ROUTE_KEYS.fleetConfig]: 'config', [GCS_ROUTE_KEYS.fleetTelemetry]: 'telemetry',
  [GCS_ROUTE_KEYS.swarmConfig]: 'swarm', [GCS_ROUTE_KEYS.fleetHeartbeats]: 'heartbeats',
  [GCS_ROUTE_KEYS.systemRuntimeStatus]: 'runtime', [GCS_ROUTE_KEYS.gitStatus]: 'git',
};

/** Canonical fleet readers share ownership; domain reads stay sequential. */
export default function useFetch(endpoint, interval = null) {
  const name = typeof endpoint === 'string' && !endpoint.includes('?') ? sharedResources[resolveGcsRouteKey(endpoint)] : null;
  const shared = useObservationResource(name, endpoint);
  const load = useCallback(options => fetchGcsResource(endpoint, options), [endpoint]);
  const own = usePollingResource(load, interval, endpoint, Boolean(endpoint && !name));
  const resource = name ? shared : own;
  return useMemo(() => ({ data: endpoint ? resource.response?.data ?? null : null,
    meta: resource.response ? { receivedAtMs: resource.receivedAtMs, serverNowMs: extractServerNowMs(resource.response.headers || {}) } : null,
    error: endpoint ? resource.error : null, loading: Boolean(endpoint && resource.loading), refresh: resource.refresh,
  }), [endpoint, resource]);
}
