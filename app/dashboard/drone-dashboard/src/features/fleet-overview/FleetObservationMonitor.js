import { useEffect, useMemo } from 'react';
import { heightReviewClusters, fleetHeightReviews } from './heightReviewObservations';
import useFleetResources from './useFleetResources';
import useFleetAttention from './useFleetAttention';
import { buildFleetViewModel } from './fleetViewModel';
import { useFleetAlerts } from './FleetAlertsContext';

/** Shell-wide monitoring; changing page must not stop observing the fleet. */
export default function FleetObservationMonitor() {
  const resources = useFleetResources();
  const model = useMemo(() => buildFleetViewModel(resources.drones, {
    nowMs: resources.nowMs, displayPolicy: resources.displayPolicy,
  }), [resources.drones, resources.nowMs, resources.displayPolicy]);
  const clusters = useMemo(() => heightReviewClusters(resources.swarm), [resources.swarm]);
  const heightReviews = useMemo(() => fleetHeightReviews(clusters, resources.drones, resources.displayPolicy, resources.nowMs),
    [clusters, resources.drones, resources.displayPolicy, resources.nowMs]);
  const attention = useFleetAttention(model, resources);
  const { publishSnapshot, sourceUnavailable } = useFleetAlerts();
  useEffect(() => {
    publishSnapshot({ heightReviews, aircraft: attention.model.aircraft, sourceError: attention.telemetry.active,
      sourceRecovering: attention.telemetry.phase === 'recovering', observedAtMs: resources.nowMs });
  }, [heightReviews, attention.model.aircraft, attention.telemetry.active, attention.telemetry.phase, resources.nowMs, publishSnapshot]);
  useEffect(() => () => sourceUnavailable(), [sourceUnavailable]);
  return null;
}
