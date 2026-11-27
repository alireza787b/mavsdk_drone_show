import { fleetHeightReviews, heightReviewClusters } from './heightReviewObservations';
import { createFleetAlertsState, fleetAlertsReducer } from './FleetAlertsContext';

const now = 1900000000000;
const policy = { height_review_threshold_m: 1, height_sample_max_age_ms: 3000 };
const row = (hw_id, position_alt) => ({ hw_id, position_alt, global_position_valid: true, global_position_timestamp_ms: now });
const clusters = heightReviewClusters([{ hw_id: '200', follow: '199', offset_z: 3 }, { hw_id: '199', follow: '0' }]);

test('a saved formation at the end of a large roster has one review that expires with its source', () => {
  const fleet = Array.from({ length: 200 }, (_, i) => row(String(i + 1), i === 199 ? 105.5 : 100));
  const reviews = t => fleetHeightReviews(clusters, fleet, policy, t);
  expect(reviews(now)).toHaveLength(1);
  expect(reviews(now)[0]).toMatchObject({ active: true, ids: ['199', '200'] });
  const apply = (state, t) => fleetAlertsReducer(state, { type: 'snapshot', snapshot: { heightReviews: reviews(t), observedAtMs: t } });
  const active = apply(createFleetAlertsState(), now);
  expect(apply(active, now + 3001).heightReviews[0]).toMatchObject({ active: false, complete: false });
  fleet[199].position_alt = 100;
  expect(apply(active, now).heightReviews).toHaveLength(0);
});

test('an intentionally stepped airborne formation and unrelated aircraft do not create height alerts', () => {
  const fleet = [row('1', 340), row('199', 100), row('200', 103)].map(sample => ({
    ...sample, landed_state: 2, landed_state_timestamp_ms: now,
  }));
  expect(fleetHeightReviews(clusters, fleet, policy, now)[0]).toMatchObject({ active: false, complete: true });
});
