import { worldToRelative } from './swarmFormationGeometry';

const finite = (value, field, id) => {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) {
    throw new Error(`H${id}: ${field} unavailable. Refresh capture.`);
  }
  return Number(value);
};

/** Reinterpret one frozen observation bundle. Never fetch telemetry or flatten relay links. */
export function deriveSwarmCaptureDraft(assignments, snapshot, { leaderId, frame, heightMode }) {
  if (!['ned', 'body'].includes(frame) || !['keep', 'level'].includes(heightMode)) {
    throw new Error('Choose a reference and height option.');
  }
  const observations = snapshot?.observations || {};
  const ids = Object.keys(observations);
  const scope = new Set(ids);
  const leader = String(leaderId);
  if (!scope.has(leader) || ids.length < 2) throw new Error('Choose a captured formation leader.');
  const byId = new Map(assignments.map((entry) => [String(entry.hw_id), entry]));
  const parents = new Map(ids.map((id) => [id, String(byId.get(id)?.follow)]));
  // Reverse only the old root-to-new-root path. All other relay branches survive.
  let child = leader;
  let parent = parents.get(child);
  parents.set(child, '0');
  const visited = new Set([child]);
  while (parent !== '0') {
    if (!scope.has(parent) || visited.has(parent)) throw new Error('Review the complete follow chain before capture.');
    visited.add(parent);
    const next = parents.get(parent);
    parents.set(parent, child);
    child = parent;
    parent = next;
  }
  const candidate = assignments.map((entry) => {
    const id = String(entry.hw_id);
    if (!scope.has(id)) return { ...entry };
    const follow = parents.get(id);
    if (follow === '0') return { ...entry, follow, frame, offset_x: 0, offset_y: 0, offset_z: 0 };
    const own = observations[id];
    const reference = observations[follow];
    if (!reference) throw new Error(`H${id}: followed aircraft was not captured.`);
    const delta = {
      north: finite(own.north_m, 'North position', id) - finite(reference.north_m, 'North position', follow),
      east: finite(own.east_m, 'East position', id) - finite(reference.east_m, 'East position', follow),
      up: heightMode === 'level' ? 0
        : finite(own.planned_up_m, 'planned height', id) - finite(reference.planned_up_m, 'planned height', follow),
    };
    const heading = frame === 'body' ? finite(reference.heading_deg, 'heading', follow) : 0;
    return { ...entry, follow, frame, ...worldToRelative(delta, frame, heading) };
  });
  return { assignments: candidate, clusterId: leader, hwIds: ids,
    headings: Object.fromEntries(ids.filter((id) => Number.isFinite(observations[id]?.heading_deg))
      .map((id) => [id, observations[id].heading_deg])) };
}

export function swarmCaptureError(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  const message = detail?.message || error?.message || 'Current positions could not be captured. Refresh when aircraft are ready.';
  return detail?.hw_id && !message.includes(`H${detail.hw_id}`) ? `H${detail.hw_id}: ${message}` : message;
}
