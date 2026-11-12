import { useEffect, useMemo, useState } from 'react';
import { useFleetResource, mergeFleetResources } from '../fleet-overview/useFleetResources';
import { buildFleetViewModel } from '../fleet-overview/fleetViewModel';
import { getFleetConfigResponse, getFleetTelemetryResponse, getSwarmConfigResponse, unwrapFleetTelemetryPayload, unwrapSwarmConfigPayload } from '../../services/gcsApiService';
import { getPx4ParamPolicy, listPx4ParamProfiles } from '../../services/px4ParamsApiService';
import { normalizeTelemetryResponse } from '../../constants/fieldMappings';
import { buildSwarmViewModel } from '../../utilities/swarmDesignUtils';

export default function useParameterResources(context) {
  const config = useFleetResource(getFleetConfigResponse, 30000, context);
  const telemetry = useFleetResource(getFleetTelemetryResponse, 15000, context);
  const swarm = useFleetResource(getSwarmConfigResponse, 30000, context);
  const policy = useFleetResource(getPx4ParamPolicy, 60000, context);
  const profiles = useFleetResource(listPx4ParamProfiles, 60000, context);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const drones = useMemo(() => {
    const clock = { receivedAtMs: telemetry.receivedAtMs,
      serverNowMs: telemetry.response?.headers?.['x-mds-server-time'] ?? telemetry.response?.headers?.date ?? null };
    return mergeFleetResources(config.response?.data,
      normalizeTelemetryResponse(unwrapFleetTelemetryPayload(telemetry.response?.data || {}), clock), {}, clock);
  }, [config.response, telemetry.response, telemetry.receivedAtMs]);
  const displayPolicy = telemetry.response?.data?.display_policy;
  const model = useMemo(() => buildFleetViewModel(drones, { nowMs: now, displayPolicy }), [drones, now, displayPolicy]);
  const clusters = useMemo(() => buildSwarmViewModel(unwrapSwarmConfigPayload(swarm.response?.data), drones)?.clusters || [], [swarm.response, drones]);
  return { aircraft: model.aircraft, clusters, now,
    policy: policy.error ? null : policy.response?.data,
    profiles: profiles.response?.data?.profiles || [],
    loading: config.loading && telemetry.loading,
    error: config.error || telemetry.error,
    policyError: policy.error, profilesError: profiles.error,
  };
}
