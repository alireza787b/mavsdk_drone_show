import { createDraftHistory, draftHistoryReducer, moveAssignmentInPlane, offsetForWorldPosition, preservePositionPatch, relativeToWorld, resolveFormationPositions, worldToRelative, worldToView, viewToWorld, formationToScene, sceneToFormation, projectFormationPoint } from './swarmFormationGeometry';

const fleet = [
  { hw_id: '1', follow: '0', frame: 'ned', offset_x: 0, offset_y: 0, offset_z: 0 },
  { hw_id: '2', follow: '1', frame: 'body', offset_x: 6, offset_y: 2, offset_z: 1 },
  { hw_id: '3', follow: '2', frame: 'body', offset_x: 3, offset_y: 0, offset_z: 2 },
];
describe('formation design geometry', () => {
  test.each(['ned', 'body'])('view reference round-trips world and scene positions (%s)', (frame) => {
    const original = { north: 6, east: 4, up: 3 };
    const view = worldToView(original, frame, 90);
    const restored = viewToWorld(view, frame, 90);
    expect(restored.north).toBeCloseTo(6); expect(restored.east).toBeCloseTo(4); expect(restored.up).toBe(3);
    const scene = formationToScene(original, frame, 90);
    const back = sceneToFormation({ x: scene[0], y: scene[1], z: scene[2] }, frame, 90);
    expect(back.north).toBeCloseTo(6); expect(back.east).toBeCloseTo(4); expect(back.up).toBe(3);
  });
  test('body 90° links Top, Front, Side, and 3D reference axes without changing geometry', () => {
    const position = { north: -2, east: 6, up: 3 };
    expect(projectFormationPoint(position, 'top', 'body', 90).x).toBeCloseTo(2);
    expect(projectFormationPoint(position, 'top', 'body', 90).y).toBeCloseTo(6);
    expect(projectFormationPoint(position, 'east-up', 'body', 90).x).toBeCloseTo(2);
    expect(projectFormationPoint(position, 'east-up', 'body', 90).y).toBe(3);
    expect(projectFormationPoint(position, 'north-up', 'body', 90).x).toBeCloseTo(6);
    expect(formationToScene(position, 'body', 90)[1]).toBe(3);
    expect(position).toEqual({ north: -2, east: 6, up: 3 });
  });
  test('view-axis drag converts independently from aircraft own parent/frame', () => {
    // Aircraft body axes use parent heading 180°, display axes use heading 90°.
    const before = relativeToWorld(fleet[2], 180);
    const patch = moveAssignmentInPlane(fleet[2], 2, 1, 'top', 180, 'body', 90);
    const after = relativeToWorld({ ...fleet[2], ...patch }, 180);
    expect(after.north - before.north).toBeCloseTo(-2);
    expect(after.east - before.east).toBeCloseTo(1);
    expect(after.up).toBe(2);
    const vertical = moveAssignmentInPlane(fleet[2], 2, 3, 'north-up', 180, 'body', 90);
    const verticalWorld = relativeToWorld({ ...fleet[2], ...vertical }, 180);
    expect(verticalWorld.east - before.east).toBeCloseTo(2);
    expect(verticalWorld.north).toBeCloseTo(before.north);
    expect(verticalWorld.up).toBe(5);
  });
  test.each([0, 90, 180, 270])('round-trips body offsets at heading %s', (heading) => {
    const original = fleet[1];
    const result = worldToRelative(relativeToWorld(original, heading), 'body', heading);
    expect(result.offset_x).toBeCloseTo(6); expect(result.offset_y).toBeCloseTo(2); expect(result.offset_z).toBe(1);
  });
  test('resolves each parent heading in a mixed chain', () => {
    const positions = resolveFormationPositions(fleet, { 1: 90, 2: 180 });
    expect(positions['2'].north).toBeCloseTo(-2); expect(positions['2'].east).toBeCloseTo(6);
    expect(positions['3'].north).toBeCloseTo(-5); expect(positions['3'].east).toBeCloseTo(6); expect(positions['3'].up).toBe(3);
  });
  test('horizontal movement adds to existing offsets, not resets to delta', () => {
    expect(moveAssignmentInPlane({ ...fleet[1], frame: 'ned' }, 2, 1)).toEqual({ offset_x: 7, offset_y: 4, offset_z: 1 });
  });
  test('side movement changes height and selected world axis only', () => {
    const result = moveAssignmentInPlane(fleet[1], 2, 3, 'east-up', 90);
    expect(result.offset_x).toBeCloseTo(8); expect(result.offset_y).toBeCloseTo(2); expect(result.offset_z).toBe(4);
  });
  test('frame changes and same-cluster reparent preserve preview position', () => {
    const headings = { 1: 90, 2: 180 };
    for (const patch of [{ frame: 'ned' }, { follow: '1' }]) {
      const preserved = preservePositionPatch(fleet, '3', patch, headings);
      const updated = fleet.map((entry) => entry.hw_id === '3' ? { ...entry, ...preserved } : entry);
      const before = resolveFormationPositions(fleet, headings)['3'];
      const after = resolveFormationPositions(updated, headings)['3'];
      expect(after.north).toBeCloseTo(before.north); expect(after.east).toBeCloseTo(before.east); expect(after.up).toBeCloseTo(before.up);
    }
  });
  test('rejects cycles and cross-cluster preserve-position fiction', () => {
    expect(() => preservePositionPatch(fleet, '1', { follow: '3' })).toThrow('Invalid follow chain');
    expect(() => preservePositionPatch([...fleet, { ...fleet[0], hw_id: '4' }], '2', { follow: '4' })).toThrow('Independent clusters');
  });
  test('absolute world move uses parent position and heading', () => {
    const result = offsetForWorldPosition(fleet[1], { north: 4, east: 9, up: 3 }, { north: 1, east: 2, up: 1 }, { 1: 90 });
    expect(result.offset_x).toBeCloseTo(7); expect(result.offset_y).toBeCloseTo(-3); expect(result.offset_z).toBe(2);
  });
});

describe('formation draft gesture history', () => {
  test('one drag is one undo step and redo restores final position', () => {
    let state = createDraftHistory(fleet);
    state = draftHistoryReducer(state, { type: 'begin' });
    state = draftHistoryReducer(state, { type: 'edit', id: '2', patch: { offset_x: 8 } });
    state = draftHistoryReducer(state, { type: 'edit', id: '2', patch: { offset_x: 12 } });
    expect(state.past).toHaveLength(0);
    state = draftHistoryReducer(state, { type: 'end' });
    expect(state.past).toHaveLength(1);
    state = draftHistoryReducer(state, { type: 'undo' }); expect(state.present).toEqual(fleet);
    state = draftHistoryReducer(state, { type: 'redo' }); expect(state.present[1].offset_x).toBe(12);
  });
  test('cancel restores exact assignments and creates no undo entry', () => {
    let state = draftHistoryReducer(createDraftHistory(fleet), { type: 'begin' });
    state = draftHistoryReducer(state, { type: 'edit', id: '2', patch: { offset_z: 9 } });
    state = draftHistoryReducer(state, { type: 'end', cancelled: true });
    expect(state.present).toEqual(fleet); expect(state.past).toHaveLength(0);
  });
});
