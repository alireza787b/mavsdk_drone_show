import { interpolateGlobePosition } from './globeMotion';

describe('interpolateGlobePosition', () => {
  test('moves smoothly toward a target without overshooting', () => {
    const next = interpolateGlobePosition([0, 0, 0], [10, 0, 0], 0.1);

    expect(next[0]).toBeGreaterThan(0);
    expect(next[0]).toBeLessThan(10);
  });

  test('bounds a large discontinuity by display speed', () => {
    const next = interpolateGlobePosition([0, 0, 0], [1000, 0, 0], 0.1, {
      maxDisplaySpeedMps: 5,
    });

    expect(next[0]).toBeCloseTo(0.5, 5);
  });

  test('does not move when the frame delta is zero', () => {
    expect(interpolateGlobePosition([1, 2, 3], [9, 8, 7], 0)).toEqual([1, 2, 3]);
  });
});
