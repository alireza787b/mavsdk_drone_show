import {
  decodePx4CustomMode,
  encodePx4CustomMode,
  getFlightModeName,
  PX4_AUTO_SUB_MODES,
  PX4_MAIN_MODES
} from '../constants/px4FlightModes';
import {
  getFlightModeCategory,
  getFlightModeTitle,
  isSafeMode
} from './flightModeUtils';

describe('PX4 custom_mode handling', () => {
  test.each([
    [67371008, 'Mission', PX4_AUTO_SUB_MODES.AUTO_MISSION],
    [50593792, 'Hold', PX4_AUTO_SUB_MODES.AUTO_LOITER],
    [84148224, 'Return', PX4_AUTO_SUB_MODES.AUTO_RTL],
    [33816576, 'Takeoff', PX4_AUTO_SUB_MODES.AUTO_TAKEOFF],
    [100925440, 'Land', PX4_AUTO_SUB_MODES.AUTO_LAND]
  ])('decodes field value %i as %s', (customMode, expectedName, expectedSubMode) => {
    expect(getFlightModeTitle(customMode)).toBe(expectedName);
    expect(decodePx4CustomMode(customMode)).toEqual({
      customMode,
      reserved: 0,
      mainMode: PX4_MAIN_MODES.AUTO,
      subMode: expectedSubMode
    });
  });

  test('encodes PX4 main and sub-mode bytes in their canonical positions', () => {
    expect(
      encodePx4CustomMode(PX4_MAIN_MODES.AUTO, PX4_AUTO_SUB_MODES.AUTO_MISSION)
    ).toBe(0x04040000);
    expect(getFlightModeName('67371008')).toBe('Mission');
  });

  test('does not treat the reserved low word as an AUTO sub-mode', () => {
    expect(getFlightModeName(0x00040004)).toBe('Auto');
  });

  test('reports unknown AUTO sub-modes without losing the AUTO category', () => {
    const customMode = encodePx4CustomMode(PX4_MAIN_MODES.AUTO, 42);

    expect(getFlightModeName(customMode)).toBe('Auto.42');
    expect(getFlightModeCategory(customMode)).toBe('auto');
  });

  test.each([
    [encodePx4CustomMode(PX4_MAIN_MODES.POSCTL), 'manual', true],
    [encodePx4CustomMode(PX4_MAIN_MODES.AUTO, PX4_AUTO_SUB_MODES.AUTO_LOITER), 'auto', false],
    [encodePx4CustomMode(PX4_MAIN_MODES.OFFBOARD), 'offboard', false],
    [0x00090000, 'unknown', false]
  ])('classifies mode %i as %s', (customMode, category, safe) => {
    expect(getFlightModeCategory(customMode)).toBe(category);
    expect(isSafeMode(customMode)).toBe(safe);
  });

  test.each([[''], ['mission'], [-1], [1.5], [0x100000000]])(
    'rejects invalid custom_mode value %p',
    (customMode) => {
      expect(decodePx4CustomMode(customMode)).toBeNull();
      expect(getFlightModeCategory(customMode)).toBe('unknown');
      expect(isSafeMode(customMode)).toBe(false);
    }
  );
});
