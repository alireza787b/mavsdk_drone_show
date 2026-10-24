// PX4's native landed-state fact, not an altitude-derived flight policy.
export function px4LandedState(value) {
  if (typeof value === 'string' && !/^\d+$/.test(value)) {
    return value.toUpperCase().replace(/^MAV_LANDED_STATE_/, '');
  }
  return ({ 1: 'ON_GROUND', 2: 'IN_AIR', 3: 'TAKING_OFF', 4: 'LANDING' })[value] || 'UNDEFINED';
}
