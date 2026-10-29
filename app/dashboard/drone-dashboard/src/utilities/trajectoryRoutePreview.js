import { normalizeComparableId } from './missionIdentityUtils';
import { getDroneOperatorAlias } from './dronePresentation';

// Global theme tokens resolve in SVG, Leaflet and the HTML legend alike.
export const TRAJECTORY_ROUTE_COLORS = [
  'var(--color-primary, #5fb9ff)', 'var(--color-success, #38c172)',
  'var(--color-warning, #f0b429)', 'var(--color-danger, #ef5a5a)',
  'var(--brand-secondary, #2d7fe6)', 'var(--color-info, #57b6ff)',
  'var(--brand-accent, #79d0ff)', 'var(--color-primary-hover, #8ccfff)',
];

export function trajectoryRouteColor(identity, palette = TRAJECTORY_ROUTE_COLORS) {
  const key = normalizeComparableId(identity);
  const index = /^\d+$/.test(key)
    ? Math.max(0, Number(key) - 1)
    : Array.from(key).reduce((hash, character) => (hash * 31 + character.charCodeAt(0)) >>> 0, 0);
  return palette[index % palette.length];
}

export function normalizeRoutePoint(point = {}) {
  const latitude = point?.latitude ?? point?.lat;
  const longitude = point?.longitude ?? point?.lng;
  if (!Number.isFinite(latitude) || Math.abs(latitude) > 90
      || !Number.isFinite(longitude) || Math.abs(longitude) > 180) return null;
  return { ...point, latitude, longitude };
}

export function routePointSegments(points = []) {
  const segments = [];
  let segment = [];
  points.forEach((point) => {
    const normalized = normalizeRoutePoint(point);
    if (normalized) segment.push(normalized);
    else if (segment.length) { segments.push(segment); segment = []; }
  });
  if (segment.length) segments.push(segment);
  return segments;
}

export function normalizeTrajectoryPreviewRoutes(preview = {}, formationAssignments = [], fleet = [], palette = TRAJECTORY_ROUTE_COLORS) {
  const assignments = new Map(formationAssignments.map((row) => [normalizeComparableId(row.hw_id), row]));
  const aircraft = new Map(fleet.map((row) => [normalizeComparableId(row.hw_id), row]));
  const seen = new Set();
  return (preview?.drones || []).flatMap((drone) => {
    const id = normalizeComparableId(drone.drone_id);
    if (!/^[1-9]\d*$/.test(id) || seen.has(id)) return [];
    const segments = routePointSegments(drone.points || []);
    if (!segments.length) return [];
    seen.add(id);
    const assignment = assignments.get(id);
    const explicitFollow = assignment && assignment.follow !== null && assignment.follow !== undefined && assignment.follow !== ''
      ? Number(assignment.follow) : null;
    const validFollow = Number.isInteger(explicitFollow) && explicitFollow >= 0;
    const role = validFollow ? (explicitFollow === 0 ? 'leader' : 'follower')
      : ['leader', 'follower'].includes(drone.role) ? drone.role : 'unknown';
    const leaderId = validFollow && explicitFollow > 0 ? String(explicitFollow)
      : drone.direct_leader_id != null && Number(drone.direct_leader_id) > 0 ? normalizeComparableId(drone.direct_leader_id) : null;
    const member = assignments.size ? assignments.has(id) : role !== 'unknown';
    const record = aircraft.get(id);
    const alias = record ? getDroneOperatorAlias(record)?.value : '';
    const label = String(alias || record?.name || '').trim() || `H${id}`;
    return [{
      id, hardwareLabel: `H${id}`, label, role, leaderId, outsideMission: !member,
      roleLabel: role === 'leader' ? 'Leader' : role === 'follower' ? `Follows ${leaderId ? `H${leaderId}` : 'unknown leader'}` : 'Role unknown',
      color: trajectoryRouteColor(id, palette), segments, points: segments.flat(),
    }];
  }).sort((a, b) => Number(a.id) - Number(b.id));
}

export function routeGeographicBounds(series = [], coordinateFrame = null) {
  const points = series.flatMap((item) => item.points || []).map(normalizeRoutePoint).filter(Boolean);
  if (!points.length) return null;
  if (coordinateFrame) {
    const longitudes = points.map((point) => coordinateFrame.unwrap(point.longitude));
    return {
      minLat: Math.min(...points.map((point) => point.latitude)), maxLat: Math.max(...points.map((point) => point.latitude)),
      minLng: Math.min(...longitudes), maxLng: Math.max(...longitudes), unwrap: coordinateFrame.unwrap,
    };
  }
  const longitudes = [...new Set(points.map((point) => (point.longitude + 360) % 360))].sort((a, b) => a - b);
  let largestGap = -1, reference = longitudes[0];
  longitudes.forEach((longitude, index) => {
    const next = longitudes[(index + 1) % longitudes.length];
    const gap = index === longitudes.length - 1 ? next + 360 - longitude : next - longitude;
    if (gap > largestGap) { largestGap = gap; reference = next; }
  });
  const rawUnwrap = (longitude) => reference + ((longitude - reference + 720) % 360);
  const rawLongitudes = points.map((point) => rawUnwrap(point.longitude));
  const shift = Math.floor(((Math.min(...rawLongitudes) + Math.max(...rawLongitudes)) / 2 + 180) / 360) * 360;
  const unwrap = (longitude) => rawUnwrap(longitude) - shift;
  return {
    minLat: Math.min(...points.map((point) => point.latitude)), maxLat: Math.max(...points.map((point) => point.latitude)),
    minLng: Math.min(...rawLongitudes) - shift, maxLng: Math.max(...rawLongitudes) - shift, unwrap,
  };
}

export function trajectoryPreviewGeometryKey(routes = []) {
  let hash = 2166136261;
  const feed = (value) => {
    for (const character of String(value)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  };
  routes.forEach((route) => {
    feed(route.id); feed(route.outsideMission);
    route.segments.forEach((segment) => {
      feed('|'); segment.forEach((point) => { feed(point.latitude); feed(','); feed(point.longitude); feed(';'); });
    });
  });
  return String(hash);
}
