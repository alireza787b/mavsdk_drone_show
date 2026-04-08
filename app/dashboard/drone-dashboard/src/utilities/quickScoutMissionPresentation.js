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
  if (missionTemplate === 'last_known_point') {
    return 'Last Known Point';
  }
  if (missionTemplate === 'corridor_search') {
    return 'Corridor Search';
  }
  return 'Area Sweep';
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
