//app/dashboard/drone-dashboard/src/components/trajectory/TrajectoryStats.js
import React from 'react';
import PropTypes from 'prop-types';
import {
  getTrajectoryHeadingPlanSummary,
  getTrajectoryTimingPlanSummary,
} from '../../utilities/trajectoryAuthoringGuidance';
import '../../styles/TrajectoryStats.css';

const TrajectoryStats = ({ stats }) => {
  const formatDistance = (distance) => {
    if (distance > 1000) {
      return `${(distance / 1000).toFixed(2)} km`;
    }
    return `${distance.toFixed(1)} m`;
  };

  const formatTime = (time) => {
    if (time > 60) {
      const minutes = Math.floor(time / 60);
      const seconds = time % 60;
      return `${minutes}m ${seconds.toFixed(0)}s`;
    }
    return `${time.toFixed(0)}s`;
  };

  const formatAltitudeRange = (minAltitude, maxAltitude) => {
    if (minAltitude === maxAltitude) {
      return `${maxAltitude.toFixed(0)} m`;
    }
    return `${minAltitude.toFixed(0)}-${maxAltitude.toFixed(0)} m`;
  };

  const formatCountPair = (firstLabel, firstValue, secondLabel, secondValue) => (
    `${firstLabel} ${firstValue} · ${secondLabel} ${secondValue}`
  );

  const altitudeModes = stats.altitudeReferenceCounts || {};
  const terrainCoverage = stats.terrainCoverage || {};

  const briefSignals = [
    {
      label: 'Timing',
      value: getTrajectoryTimingPlanSummary(stats),
    },
    {
      label: 'Altitude Input',
      value: formatCountPair(
        'MSL',
        altitudeModes.msl || 0,
        'AGL',
        altitudeModes.agl || 0,
      ),
    },
    {
      label: 'Heading',
      value: getTrajectoryHeadingPlanSummary(stats),
    },
    {
      label: 'Terrain',
      value: formatCountPair(
        'Accurate',
        terrainCoverage.accurate || 0,
        'Estimated',
        (terrainCoverage.estimated || 0) + (terrainCoverage.unknown || 0),
      ),
    },
  ];

  return (
    <div className="trajectory-brief" aria-label="Trajectory mission brief">
      <div className="trajectory-brief__metrics">
        <div className="trajectory-brief__metric">
          <span className="trajectory-brief__label">Distance</span>
          <span className="trajectory-brief__value">{formatDistance(stats.totalDistance)}</span>
        </div>
        <div className="trajectory-brief__metric">
          <span className="trajectory-brief__label">Route Time</span>
          <span className="trajectory-brief__value">{formatTime(stats.totalTime)}</span>
          <span className="trajectory-brief__detail">Excludes climb and end behavior</span>
        </div>
        <div className="trajectory-brief__metric">
          <span className="trajectory-brief__label">Altitude Envelope</span>
          <span className="trajectory-brief__value">{formatAltitudeRange(stats.minAltitude, stats.maxAltitude)} MSL</span>
          <span className="trajectory-brief__detail">
            {formatAltitudeRange(stats.minAgl, stats.maxAgl)} AGL
          </span>
        </div>
        <div className={`trajectory-brief__metric trajectory-brief__metric--${stats.maxSpeedStatus || 'unknown'}`}>
          <span className="trajectory-brief__label">Max Leg Speed</span>
          <span className="trajectory-brief__value">{stats.maxSpeed.toFixed(1)} m/s</span>
          <span className="trajectory-brief__detail">
            {stats.maxSpeedStatus === 'impossible'
              ? 'Unsafe'
              : stats.maxSpeedStatus === 'marginal'
                ? 'Attention'
                : stats.maxSpeedStatus === 'feasible'
                  ? 'Nominal'
                  : 'Pending'}
          </span>
        </div>
      </div>

      <div className="trajectory-brief__signals">
        {briefSignals.map((signal) => (
          <div key={signal.label} className="trajectory-brief__signal">
            <span className="trajectory-brief__signal-label">{signal.label}</span>
            <span className="trajectory-brief__signal-value">{signal.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

TrajectoryStats.propTypes = {
  stats: PropTypes.shape({
    totalDistance: PropTypes.number.isRequired,
    totalTime: PropTypes.number.isRequired,
    maxSpeed: PropTypes.number.isRequired,
    speedWarnings: PropTypes.number.isRequired,
    maxAltitude: PropTypes.number.isRequired,
    minAltitude: PropTypes.number.isRequired,
    maxAgl: PropTypes.number,
    minAgl: PropTypes.number,
    routeEntryDelaySeconds: PropTypes.number,
    maxSpeedStatus: PropTypes.string,
    timingModeCounts: PropTypes.object,
    altitudeReferenceCounts: PropTypes.object,
    headingModeCounts: PropTypes.object,
    authoringBreakdown: PropTypes.shape({
      routeEntryAnchors: PropTypes.number,
      speedDrivenLegs: PropTypes.number,
      timeDrivenLegs: PropTypes.number,
      entryHeadings: PropTypes.number,
      autoArrivalHeadings: PropTypes.number,
      manualArrivalHeadings: PropTypes.number,
    }),
    terrainCoverage: PropTypes.object,
    speedStatusCounts: PropTypes.object,
  }).isRequired,
};

export default TrajectoryStats;
