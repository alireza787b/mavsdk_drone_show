import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';

import {
  getTrajectoryAltitudeIntentSummary,
  getTrajectoryHeadingIntentSummary,
  getTrajectoryHeadingModeLabel,
  getTrajectoryTimingIntentSummary,
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

const TrajectorySegmentReview = ({
  segments = [],
  onSelectSegment = null,
  activeSegmentId = '',
}) => {
  const [showAllSegments, setShowAllSegments] = useState(false);

  const summary = useMemo(() => {
    return segments.reduce(
      (acc, segment) => {
        acc[segment.speedStatus] = (acc[segment.speedStatus] || 0) + 1;
        return acc;
      },
      { feasible: 0, marginal: 0, impossible: 0, unknown: 0 }
    );
  }, [segments]);

  const flaggedSegments = useMemo(
    () =>
      segments.filter(
        (segment) => segment.speedStatus === 'marginal' || segment.speedStatus === 'impossible'
      ),
    [segments]
  );

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

  const hasFlaggedSegments = flaggedSegments.length > 0;
  const hasCondensedFallback = !hasFlaggedSegments && segments.length > 3;
  const canToggleView = hasFlaggedSegments || hasCondensedFallback;

  const visibleSegments = showAllSegments
    ? segments
    : hasFlaggedSegments
      ? flaggedSegments
      : segments.slice(0, 3);

  const hiddenSegmentCount = Math.max(0, segments.length - visibleSegments.length);
  const showingFlaggedOnly = !showAllSegments && hasFlaggedSegments && visibleSegments.length !== segments.length;
  const showingCondensedNominal = !showAllSegments && hasCondensedFallback;

  const introText = showingFlaggedOnly
    ? `Showing attention legs only. Expand to audit all ${segments.length} legs before transfer.`
    : showingCondensedNominal
      ? `Showing the first 3 nominal legs. Expand to audit all ${segments.length} legs before transfer.`
      : showAllSegments && hasFlaggedSegments
        ? 'Showing all legs. Attention items remain highlighted so the full route can be reviewed without losing risk context.'
        : 'All current legs are nominal. Full-route review remains visible so pacing stays explicit before transfer.';

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

      <div className="trajectory-segment-review__intro-row">
        <p className="trajectory-segment-review__intro">{introText}</p>
        {canToggleView ? (
          <button
            type="button"
            className="trajectory-segment-review__toggle"
            onClick={() => setShowAllSegments((current) => !current)}
          >
            {showAllSegments
              ? hasFlaggedSegments
                ? 'Show attention legs'
                : 'Show condensed view'
              : `Show all ${segments.length} legs${hiddenSegmentCount > 0 ? ` (+${hiddenSegmentCount})` : ''}`}
          </button>
        ) : null}
      </div>

      <div className="trajectory-segment-review__list">
        {visibleSegments.map((segment) => {
          const timingSummary = getTrajectoryTimingIntentSummary({
            timingMode: segment.timingMode,
            timeFromStart: segment.arrivalTimeFromStart,
            preferredSpeed: segment.preferredSpeed,
            requiredSpeed: segment.speed,
          });
          const headingSummary = getTrajectoryHeadingIntentSummary({
            headingMode: segment.headingMode,
            heading: segment.heading,
            calculatedHeading: segment.calculatedHeading,
          });
          const altitudeSummary = getTrajectoryAltitudeIntentSummary({
            altitudeReference: segment.toAltitudeReference,
            altitude: segment.toAltitude,
            targetAgl: segment.toTargetAgl,
            groundElevation: segment.toGroundElevation,
            terrainAccurate: segment.terrainAccurate,
          });

          return (
            <article
              key={segment.id}
              className={`trajectory-segment-review__item trajectory-segment-review__item--${segment.speedStatus} ${
                activeSegmentId === segment.id ? 'trajectory-segment-review__item--active' : ''
              }`}
            >
              <button
                type="button"
                className="trajectory-segment-review__button"
                onClick={() => onSelectSegment?.(segment)}
                disabled={!onSelectSegment}
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

                <div className="trajectory-segment-review__audit-row">
                  <span>{timingSummary.compact}</span>
                  <span>{headingSummary.compact}</span>
                </div>

                <div className="trajectory-segment-review__audit-row">
                  <span>{altitudeSummary.compact}</span>
                  <span>{segment.terrainAccurate ? 'Verified terrain' : 'Estimated terrain'}</span>
                </div>
              </button>
            </article>
          );
        })}
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
      arrivalTimeFromStart: PropTypes.number,
      timingMode: PropTypes.string.isRequired,
      preferredSpeed: PropTypes.number,
      headingMode: PropTypes.string.isRequired,
      heading: PropTypes.number,
      calculatedHeading: PropTypes.number,
      toAltitude: PropTypes.number,
      toAltitudeReference: PropTypes.string,
      toTargetAgl: PropTypes.number,
      toGroundElevation: PropTypes.number,
      terrainAccurate: PropTypes.bool,
    })
  ),
  onSelectSegment: PropTypes.func,
  activeSegmentId: PropTypes.string,
};

export default TrajectorySegmentReview;
