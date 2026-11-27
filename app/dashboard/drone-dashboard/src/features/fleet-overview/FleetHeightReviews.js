import React from 'react';
import '../../styles/SwarmOperations.css';
import SwarmHeightAdvisory from '../../components/SwarmHeightAdvisory';

export default function FleetHeightReviews({ reviews = [] }) {
  return reviews.map(review => <section key={review.id} aria-label={`Height readings for ${review.name}`}>
    <strong>Formation · {review.name}</strong>
    <SwarmHeightAdvisory warning={review.warning} targetIds={review.ids} receivedAtMs={review.receivedAtMs} announce={false} />
  </section>);
}
