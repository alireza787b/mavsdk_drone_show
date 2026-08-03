import { calculateSearchPathLengthM } from './quickScoutSearchGeometry';

export function formatQuickScoutArea(areaSqM) {
  if (!Number.isFinite(Number(areaSqM)) || Number(areaSqM) <= 0) {
    return '--';
  }

  const area = Number(areaSqM);
  if (area >= 10000) {
    return `${(area / 10000).toFixed(1)} ha`;
  }
  return `${Math.round(area)} m²`;
}

export function formatQuickScoutDuration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) {
    return '--';
  }

  const totalSeconds = Math.round(Number(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainderSeconds = totalSeconds % 60;

  if (minutes <= 0) {
    return `${remainderSeconds}s`;
  }

  if (remainderSeconds === 0) {
    return `${minutes} min`;
  }

  return `${minutes}m ${remainderSeconds}s`;
}

export function formatQuickScoutDistance(distanceM) {
  if (!Number.isFinite(Number(distanceM)) || Number(distanceM) <= 0) {
    return '--';
  }

  const distance = Number(distanceM);
  if (distance >= 1000) {
    return `${(distance / 1000).toFixed(1)} km`;
  }
  return `${Math.round(distance)} m`;
}

export function getQuickScoutMissionTemplateLabel(missionTemplate) {
  if (missionTemplate === 'point_dispatch') {
    return 'Point Dispatch';
  }
  if (missionTemplate === 'last_known_point') {
    return 'Last Known Point';
  }
  if (missionTemplate === 'corridor_search') {
    return 'Corridor Search';
  }
  return 'Area Sweep';
}

export function getQuickScoutMissionPhaseLabel(operationPhase) {
  if (operationPhase === 'ready_to_launch') {
    return 'Ready to Launch';
  }
  if (operationPhase === 'launch_queued') {
    return 'Launch Queued';
  }
  if (operationPhase === 'launch_partial') {
    return 'Launch Partial';
  }
  if (operationPhase === 'searching') {
    return 'Searching';
  }
  if (operationPhase === 'mixed_control') {
    return 'Mixed Control State';
  }
  if (operationPhase === 'holding') {
    return 'Holding';
  }
  if (operationPhase === 'return_commanded') {
    return 'Return Commanded';
  }
  if (operationPhase === 'completed') {
    return 'Completed';
  }
  if (operationPhase === 'aborted') {
    return 'Aborted';
  }
  return 'Planning';
}

export function getQuickScoutCommandLifecycleMessage(batch) {
  const state = batch?.state;
  const targetCount = Object.keys(batch?.targets || {}).length;
  const targetLabel = `${targetCount} target${targetCount === 1 ? '' : 's'}`;

  if (state === 'queued') {
    return `Queued one tracked command for ${targetLabel}; no execution is implied yet.`;
  }
  if (state === 'preparing') {
    return `Checking current launch readiness for ${targetLabel}.`;
  }
  if (state === 'awaiting_ack') {
    return `Command delivery is in progress for ${targetLabel}; acknowledgements are pending.`;
  }
  if (state === 'accepted') {
    return `Delivery was accepted by ${targetLabel}; execution evidence is still pending.`;
  }
  if (state === 'delivery_unknown') {
    return 'At least one delivery outcome is uncertain. Inspect each target before retrying.';
  }
  if (state === 'rejected') {
    return 'At least one target rejected the command. Inspect the target states and blocker details.';
  }
  if (state === 'executing') {
    return `Authenticated execution evidence is available for this ${targetLabel} command.`;
  }
  if (state === 'completed') {
    return `Execution completed successfully for ${targetLabel}.`;
  }
  if (state === 'failed') {
    return 'The tracked command reached a terminal failure. Inspect each target for the exact outcome.';
  }
  if (state === 'tracking_unavailable') {
    return 'Current tracker truth is unavailable. Retained terminal target evidence is shown; do not infer success.';
  }
  return batch?.receipt?.message || 'Monitor the command tracker for lifecycle truth.';
}

function formatCoordinate(point) {
  if (!Number.isFinite(Number(point?.lat)) || !Number.isFinite(Number(point?.lng))) {
    return '--';
  }
  return `${Number(point.lat).toFixed(4)}, ${Number(point.lng).toFixed(4)}`;
}

export function buildQuickScoutGeometrySummary({
  missionTemplate,
  totalAreaSqM,
  searchArea,
  searchCenter,
  searchRadiusM,
  searchPath,
  corridorWidthM,
}) {
  if (missionTemplate === 'point_dispatch') {
    return {
      title: 'Point dispatch package',
      note: 'QuickScout sends the selected aircraft to the operator-selected global point using fixed MSL cruise altitude.',
      chips: [
        `Point ${formatCoordinate(searchCenter)}`,
        'Single waypoint',
      ],
    };
  }

  if (missionTemplate === 'last_known_point') {
    return {
      title: 'Point-centered search envelope',
      note: 'QuickScout expands the reported point into a search envelope before partitioning assignments.',
      chips: [
        `Center ${formatCoordinate(searchCenter)}`,
        `Radius ${Number(searchRadiusM) > 0 ? `${Math.round(Number(searchRadiusM))} m` : '--'}`,
        `Footprint ${formatQuickScoutArea(totalAreaSqM)}`,
      ],
    };
  }

  if (missionTemplate === 'corridor_search') {
    return {
      title: 'Route-centered corridor package',
      note: 'QuickScout buffers the authored route into a corridor footprint before partitioning coverage assignments.',
      chips: [
        `Route ${Array.isArray(searchPath) ? searchPath.length : 0} points`,
        `Track ${formatQuickScoutDistance(calculateSearchPathLengthM(searchPath))}`,
        `Width ${Number(corridorWidthM) > 0 ? `${Math.round(Number(corridorWidthM))} m` : '--'}`,
        `Footprint ${formatQuickScoutArea(totalAreaSqM)}`,
      ],
    };
  }

  return {
    title: 'Polygon coverage package',
    note: 'QuickScout partitions the authored polygon into per-aircraft coverage assignments.',
    chips: [
      `Vertices ${Array.isArray(searchArea) ? searchArea.length : 0}`,
      `Footprint ${formatQuickScoutArea(totalAreaSqM)}`,
    ],
  };
}
