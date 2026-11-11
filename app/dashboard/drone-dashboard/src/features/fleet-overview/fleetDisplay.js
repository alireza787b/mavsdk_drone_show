/** Presentation grouping/filtering never owns command membership. */
export function filterFleetAircraft(aircraft, { query = '', filter = 'available', selectedIds = new Set(), matches = () => true } = {}) {
  return aircraft.filter((item) => matches(item.raw, query) && (
    filter === 'all' || (filter === 'available' && item.availability.available)
    || (filter === 'selected' && selectedIds.has(item.id))
    || (filter === 'attention' && item.attention)
    || (filter === 'unavailable' && !item.availability.available)
    || (filter === 'unmapped' && !item.position.current)
    || (filter === 'airborne' && item.flightState === 'Airborne')
  ));
}

export function groupFleetAircraft(aircraft, clusters, enabled) {
  if (!enabled) return [{ id: 'fleet', label: '', aircraft }];
  const remaining = new Map(aircraft.map((item) => [item.id, item]));
  const result = [];
  clusters.forEach((cluster) => {
    const members = [];
    cluster.drones.forEach((row) => {
      const id = String(row.hw_id);
      if (remaining.has(id)) { members.push(remaining.get(id)); remaining.delete(id); }
    });
    if (members.length) result.push({ id: String(cluster.id), label: cluster.label || `Cluster ${cluster.leaderId || cluster.id}`, aircraft: members });
  });
  if (remaining.size) result.push({ id: 'unassigned', label: 'Other aircraft', aircraft: [...remaining.values()] });
  return result;
}
