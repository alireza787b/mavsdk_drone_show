import {
  DRONE_SEARCH_PLACEHOLDER,
  matchesDroneSearchQuery,
} from './dronePresentation';

describe('matchesDroneSearchQuery', () => {
  const drone = {
    hw_id: '5',
    pos_id: '3',
    callsign: 'Atlas',
    notes: 'alpha relay',
  };

  it('matches plain text across identity and promoted metadata', () => {
    expect(matchesDroneSearchQuery(drone, 'atlas')).toBe(true);
    expect(matchesDroneSearchQuery(drone, 'relay')).toBe(true);
  });

  it('matches structured position ranges', () => {
    expect(matchesDroneSearchQuery(drone, 'pos 1-5')).toBe(true);
    expect(matchesDroneSearchQuery(drone, 'pos 6-9')).toBe(false);
  });

  it('matches structured hardware lists', () => {
    expect(matchesDroneSearchQuery(drone, 'hw 1,5')).toBe(true);
    expect(matchesDroneSearchQuery(drone, 'hw 2,4')).toBe(false);
  });

  it('matches combined structured and free-text filters', () => {
    expect(matchesDroneSearchQuery(drone, 'pos:3 atlas')).toBe(true);
    expect(matchesDroneSearchQuery(drone, 'pos:3 bravo')).toBe(false);
  });

  it('matches additional page-specific search terms', () => {
    expect(matchesDroneSearchQuery(drone, 'leader bravo', ['leader bravo', '172.18.0.9'])).toBe(true);
    expect(matchesDroneSearchQuery(drone, '172.18.0.9', ['leader bravo', '172.18.0.9'])).toBe(true);
  });
});

describe('DRONE_SEARCH_PLACEHOLDER', () => {
  it('documents the scoped query format', () => {
    expect(DRONE_SEARCH_PLACEHOLDER).toContain('pos 1-5');
    expect(DRONE_SEARCH_PLACEHOLDER).toContain('hw 2,4');
  });
});
