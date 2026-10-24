// Design coordinates are North/East/Up. Preview headings are visual-only.
const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
const angle = (heading) => number(heading) * Math.PI / 180;

export function relativeToWorld(assignment, heading = 0) {
  const x = number(assignment.offset_x), y = number(assignment.offset_y);
  const yaw = assignment.frame === 'body' ? angle(heading) : 0;
  return { north: x * Math.cos(yaw) - y * Math.sin(yaw), east: x * Math.sin(yaw) + y * Math.cos(yaw), up: number(assignment.offset_z) };
}

export function worldToRelative(position, frame = 'ned', heading = 0) {
  const yaw = frame === 'body' ? angle(heading) : 0;
  return { offset_x: position.north * Math.cos(yaw) + position.east * Math.sin(yaw), offset_y: -position.north * Math.sin(yaw) + position.east * Math.cos(yaw), offset_z: position.up };
}

export function resolveFormationPositions(assignments, headings = {}) {
  const byId = new Map(assignments.map((entry) => [String(entry.hw_id), entry]));
  const positions = {};
  const visiting = new Set();
  function resolve(id) {
    if (positions[id]) return positions[id];
    const entry = byId.get(id);
    if (!entry || visiting.has(id)) throw new Error('Invalid follow chain');
    visiting.add(id);
    const parentId = String(entry.follow);
    if (parentId === '0') positions[id] = { north: 0, east: 0, up: 0, root: id };
    else {
      const parent = resolve(parentId);
      const relative = relativeToWorld(entry, headings[parentId]);
      positions[id] = { north: parent.north + relative.north, east: parent.east + relative.east, up: parent.up + relative.up, root: parent.root };
    }
    visiting.delete(id);
    return positions[id];
  }
  byId.forEach((_, id) => resolve(id));
  return positions;
}

export function offsetForWorldPosition(assignment, position, parentPosition, headings = {}) {
  return worldToRelative({ north: position.north - parentPosition.north, east: position.east - parentPosition.east, up: position.up - parentPosition.up }, assignment.frame, headings[String(assignment.follow)]);
}

export function preservePositionPatch(assignments, id, patch, headings = {}) {
  id = String(id);
  const entry = assignments.find((item) => String(item.hw_id) === id);
  if (!entry) throw new Error('Aircraft not found');
  const positions = resolveFormationPositions(assignments, headings);
  const next = { ...entry, ...patch };
  const parentId = String(next.follow);
  if (parentId === '0') return { ...patch, offset_x: 0, offset_y: 0, offset_z: 0 };
  // Validate parent/cycles before calculating an inverse transform.
  resolveFormationPositions(assignments.map((item) => String(item.hw_id) === id ? next : item), headings);
  const parent = positions[parentId];
  if (positions[id].root !== parent.root) throw new Error('Independent clusters have no shared position; set spacing explicitly');
  return { ...patch, ...offsetForWorldPosition(next, positions[id], parent, headings) };
}

export function moveAssignmentInPlane(entry, deltaHorizontal, deltaVertical, plane = 'top', heading = 0) {
  const relative = relativeToWorld(entry, heading);
  if (plane === 'top') { relative.east += deltaHorizontal; relative.north += deltaVertical; }
  else { relative[plane === 'north-up' ? 'north' : 'east'] += deltaHorizontal; relative.up += deltaVertical; }
  return worldToRelative(relative, entry.frame, heading);
}

export function projectFormationPoint(point, plane = 'top') {
  return plane === 'top' ? { x: point.east, y: point.north } : { x: point[plane === 'north-up' ? 'north' : 'east'], y: point.up };
}

export const createDraftHistory = (assignments) => ({ present: assignments, past: [], future: [], gesture: null });
export function draftHistoryReducer(state, action) {
  const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  switch (action.type) {
    case 'reset': return createDraftHistory(action.assignments);
    case 'begin': return state.gesture ? state : { ...state, gesture: state.present };
    case 'edit': {
      const next = action.assignments || state.present.map((item) => String(item.hw_id) === String(action.id) ? { ...item, ...action.patch } : item);
      if (equal(next, state.present)) return state;
      return { ...state, present: next, past: state.gesture ? state.past : [...state.past, state.present].slice(-100), future: [] };
    }
    case 'end': {
      if (!state.gesture) return state;
      if (action.cancelled) return { ...state, present: state.gesture, gesture: null };
      return { ...state, past: equal(state.present, state.gesture) ? state.past : [...state.past, state.gesture].slice(-100), gesture: null };
    }
    case 'undo': return !state.past.length || state.gesture ? state : { present: state.past[state.past.length - 1], past: state.past.slice(0, -1), future: [state.present, ...state.future], gesture: null };
    case 'redo': return !state.future.length || state.gesture ? state : { present: state.future[0], past: [...state.past, state.present], future: state.future.slice(1), gesture: null };
    default: return state;
  }
}
