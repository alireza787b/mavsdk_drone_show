import {
  DRONE_SEARCH_PLACEHOLDER,
  getDroneDisplayIdentity,
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

  it('matches compact operator identity tokens', () => {
    expect(matchesDroneSearchQuery(drone, 'p3|h5')).toBe(true);
    expect(matchesDroneSearchQuery(drone, 'p9|h5')).toBe(false);
  });

  it('matches additional page-specific search terms', () => {
    expect(matchesDroneSearchQuery(drone, 'leader bravo', ['leader bravo', '172.18.0.9'])).toBe(true);
    expect(matchesDroneSearchQuery(drone, '172.18.0.9', ['leader bravo', '172.18.0.9'])).toBe(true);
  });
});

describe('DRONE_SEARCH_PLACEHOLDER', () => {
  it('documents the scoped query format', () => {
    expect(DRONE_SEARCH_PLACEHOLDER).toContain('P1|H1');
    expect(DRONE_SEARCH_PLACEHOLDER).toContain('pos 1-5');
    expect(DRONE_SEARCH_PLACEHOLDER).toContain('hw 2,4');
  });
});

describe('getDroneDisplayIdentity', () => {
  it('prefers the compact Pn|Hm operator identity in dense surfaces', () => {
    expect(getDroneDisplayIdentity({ pos_id: 3, hw_id: 5 })).toMatchObject({
      primary: 'P3|H5',
      compact: 'P3|H5',
      verbose: 'Position 3 · Hardware 5',
    });
  });
});
