import React, { useMemo } from 'react';
import PropTypes from 'prop-types';

import {
  getTrajectoryHeadingModeLabel,
  getTrajectoryTimingModeLabel,
} from '../../utilities/trajectoryAuthoringGuidance';
import '../../styles/TrajectorySegmentReview.css';

const formatDistance = (distanceMeters = 0) => {
  if (distanceMeters >= 1000) {
    return `${(distanceMeters / 1000).toFixed(2)} km`;
  }
  return `${distanceMeters.toFixed(0)} m`;
};

const formatDuration = (durationSeconds = 0) => {
  if (durationSeconds >= 60) {
    const minutes = Math.floor(durationSeconds / 60);
    const seconds = Math.round(durationSeconds % 60);
    return `${minutes}m ${seconds}s`;
  }
  return `${Math.round(durationSeconds)}s`;
};

const formatStatusLabel = (speedStatus = 'unknown') => {
  switch (speedStatus) {
    case 'feasible':
      return 'Nominal';
    case 'marginal':
      return 'Review';
    case 'impossible':
      return 'Unsafe';
    default:
      return 'Pending';
  }
};

const TrajectorySegmentReview = ({ segments = [] }) => {
  const summary = useMemo(() => {
    return segments.reduce(
      (acc, segment) => {
        acc[segment.speedStatus] = (acc[segment.speedStatus] || 0) + 1;
        return acc;
      },
      { feasible: 0, marginal: 0, impossible: 0, unknown: 0 }
    );
  }, [segments]);

  const highlightedSegments = useMemo(() => {
    const flagged = segments.filter(
      (segment) => segment.speedStatus === 'marginal' || segment.speedStatus === 'impossible'
    );

    if (flagged.length > 0) {
      return flagged;
    }

    return segments.slice(0, 3);
  }, [segments]);

  if (segments.length === 0) {
    return (
      <section className="trajectory-segment-review" aria-label="Trajectory leg review">
        <div className="trajectory-segment-review__header">
          <div>
            <span className="trajectory-segment-review__eyebrow">Leg Review</span>
            <h3>No route legs yet</h3>
          </div>
        </div>
        <p className="trajectory-segment-review__empty">
          Add at least two waypoints to review leg distance, duration, required speed, and operator intent.
        </p>
      </section>
    );
  }

  const showingFlaggedOnly = highlightedSegments.length > 0 && highlightedSegments.length !== segments.length;

  return (
    <section className="trajectory-segment-review" aria-label="Trajectory leg review">
      <div className="trajectory-segment-review__header">
        <div>
          <span className="trajectory-segment-review__eyebrow">Leg Review</span>
          <h3>Check segment pacing before swarm assignment</h3>
        </div>
        <div className="trajectory-segment-review__summary">
          <span className="trajectory-segment-review__pill trajectory-segment-review__pill--feasible">
            Nominal {summary.feasible || 0}
          </span>
          <span className="trajectory-segment-review__pill trajectory-segment-review__pill--marginal">
            Review {summary.marginal || 0}
          </span>
          <span className="trajectory-segment-review__pill trajectory-segment-review__pill--impossible">
            Unsafe {summary.impossible || 0}
          </span>
        </div>
      </div>

      <p className="trajectory-segment-review__intro">
        {showingFlaggedOnly
          ? 'Showing attention legs only. Each leg inherits timing and heading intent from the waypoint it arrives at.'
          : 'All current legs are nominal. Review remains visible so route pacing stays explicit before transfer.'}
      </p>

      <div className="trajectory-segment-review__list">
        {highlightedSegments.map((segment) => (
          <article
            key={segment.id}
            className={`trajectory-segment-review__item trajectory-segment-review__item--${segment.speedStatus}`}
          >
            <div className="trajectory-segment-review__item-header">
              <div>
                <strong>
                  Leg {segment.fromIndex} → {segment.toIndex}
                </strong>
                <span className="trajectory-segment-review__route">
                  {segment.fromWaypointName} → {segment.toWaypointName}
                </span>
              </div>
              <span className={`trajectory-segment-review__status trajectory-segment-review__status--${segment.speedStatus}`}>
                {formatStatusLabel(segment.speedStatus)}
              </span>
            </div>

            <div className="trajectory-segment-review__metrics">
              <span>{formatDistance(segment.distanceMeters)}</span>
              <span>{formatDuration(segment.durationSeconds)}</span>
              <span>{segment.speed.toFixed(1)} m/s</span>
            </div>

            <div className="trajectory-segment-review__detail-row">
              <span>{getTrajectoryTimingModeLabel(segment.timingMode)}</span>
              <span>{getTrajectoryHeadingModeLabel(segment.headingMode)}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
};

TrajectorySegmentReview.propTypes = {
  segments: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      fromIndex: PropTypes.number.isRequired,
      toIndex: PropTypes.number.isRequired,
      fromWaypointName: PropTypes.string,
      toWaypointName: PropTypes.string,
      speed: PropTypes.number.isRequired,
      speedStatus: PropTypes.string.isRequired,
      distanceMeters: PropTypes.number.isRequired,
      durationSeconds: PropTypes.number.isRequired,
      timingMode: PropTypes.string.isRequired,
      headingMode: PropTypes.string.isRequired,
    })
  ),
};

export default TrajectorySegmentReview;
