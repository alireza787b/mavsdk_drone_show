import { summarizeHeightReadings } from '../../components/SwarmHeightAdvisory';
import { getDroneReferenceNowMs } from '../../utilities/droneRuntimeStatus';

// Run once per saved layout. Unresolved or cyclic assignments have no common plan.
export function heightReviewClusters(assignments = []) {
  const children = new Map();
  for (const row of assignments) {
    const parent = String(row.follow ?? 0);
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent).push(row);
  }
  const result = [];
  for (const root of children.get('0') || []) {
    const members = [];
    const queue = [{ hw_id: String(root.hw_id), planned_height_m: 0 }];
    const visited = new Set();
    for (let i = 0; i < queue.length; i += 1) {
      const member = queue[i];
      if (visited.has(member.hw_id)) continue;
      visited.add(member.hw_id);
      members.push(member);
      for (const child of children.get(member.hw_id) || []) {
        queue.push({ hw_id: String(child.hw_id), planned_height_m: member.planned_height_m + Number(child.offset_z ?? 0) });
      }
    }
    if (members.length > 1) result.push({ id: String(root.hw_id), members });
  }
  return result;
}

export function fleetHeightReviews(clusters, drones, policy, nowMs) {
  if (!Number.isFinite(policy?.height_review_threshold_m) || !Number.isFinite(policy?.height_sample_max_age_ms)) return [];
  const byId = new Map(drones.map(row => [String(row.hw_ID ?? row.hw_id), row]));
  const reviews = [];
  for (const cluster of clusters) {
    const ids = cluster.members.map(member => member.hw_id);
    const source = cluster.members.map(member => byId.get(member.hw_id)).find(Boolean);
    if (!source) continue;
    const samples = cluster.members.map(member => {
      const row = byId.get(member.hw_id);
      if (!row || row.telemetry_available === false) return member;
      return { ...member, altitude_m: row.global_position_valid === true ? row.position_alt : null,
        altitude_timestamp_ms: row.global_position_timestamp_ms, gps_fix_type: row.gps_fix_type,
        gps_timestamp_ms: row.gps_raw_timestamp_ms, rtk_fixed_observed_since_ms: row.rtk_fixed_observed_since_ms,
        landed_state: row.landed_state, landed_timestamp_ms: row.landed_state_timestamp_ms };
    });
    const warning = { samples, threshold_m: policy.height_review_threshold_m,
      max_age_ms: policy.height_sample_max_age_ms, observed_at_ms: getDroneReferenceNowMs(source, nowMs) };
    const summary = summarizeHeightReadings(warning, ids, nowMs, nowMs);
    reviews.push({ id: cluster.id, ids, warning, receivedAtMs: nowMs, active: summary.active,
      complete: summary.valid_count === summary.expected_count, name: byId.get(cluster.id)?.callsign || `H${cluster.id}` });
  }
  return reviews;
}
