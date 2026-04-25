import {
  findNearestScreenAnchor,
  getEventClientPoint,
} from './globeScreenInteractions';

describe('globeScreenInteractions', () => {
  test('resolves mouse and touch client points', () => {
    expect(getEventClientPoint({ clientX: 10, clientY: 20 })).toEqual({ x: 10, y: 20 });
    expect(getEventClientPoint({ touches: [{ clientX: 30, clientY: 40 }] })).toEqual({ x: 30, y: 40 });
    expect(getEventClientPoint({ clientX: 'bad', clientY: 20 })).toBeNull();
  });

  test('selects the nearest visible projected anchor inside the hit radius', () => {
    const anchors = [
      { id: 'far', x: 180, y: 180, visible: true },
      { id: 'near', x: 84, y: 92, visible: true },
      { id: 'hidden', x: 70, y: 70, visible: false },
    ];

    expect(findNearestScreenAnchor(
      anchors,
      { x: 100, y: 110 },
      { left: 10, top: 15 },
      40,
    )).toEqual(expect.objectContaining({ id: 'near' }));
  });

  test('returns null outside the projected anchor hit radius', () => {
    expect(findNearestScreenAnchor(
      [{ id: 'drone-1', x: 20, y: 20, visible: true }],
      { x: 200, y: 200 },
      { left: 0, top: 0 },
      35,
    )).toBeNull();
  });
});
