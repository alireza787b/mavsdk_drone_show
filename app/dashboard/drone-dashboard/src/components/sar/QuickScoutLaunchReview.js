import React from 'react';
import PropTypes from 'prop-types';

import CommandPreflightSummary from '../CommandPreflightSummary';
import { getQuickScoutProfile } from '../../utilities/quickScoutProfiles';

function formatArea(areaSqM) {
  if (!Number.isFinite(Number(areaSqM)) || Number(areaSqM) <= 0) {
    return '--';
  }

  const area = Number(areaSqM);
  if (area >= 10000) {
    return `${(area / 10000).toFixed(1)} ha`;
  }
  return `${Math.round(area)} m²`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(Number(seconds)) || Number(seconds) <= 0) {
    return '--';
  }

  const totalSeconds = Math.round(Number(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  const remainderSeconds = totalSeconds % 60;

  if (minutes <= 0) {
    return `${remainderSeconds}s`;
  }

  if (remainderSeconds === 0) {
    return `${minutes} min`;
  }

  return `${minutes}m ${remainderSeconds}s`;
}

function getReturnBehaviorLabel(returnBehavior) {
  if (returnBehavior === 'hold_position') {
    return 'Hold position';
  }
  if (returnBehavior === 'land_current') {
    return 'Land current';
  }
  return 'Return home';
}

function getLaunchStatus(planNeedsRecompute, launchReadiness) {
  if (planNeedsRecompute) {
    return {
      tone: 'danger',
      title: 'Recompute required before launch',
      detail: 'Mission inputs changed after the last compute. Review the update and regenerate the search package before dispatch.',
    };
  }

  if (launchReadiness?.blockers?.length > 0) {
    return {
      tone: 'danger',
      title: 'Resolve launch blockers first',
      detail: 'At least one assigned aircraft is unavailable or not ready for this package.',
    };
  }

  if (launchReadiness?.warnings?.length > 0) {
    return {
      tone: 'warning',
      title: 'Package is ready, but advisories remain',
      detail: 'Live telemetry is available, but the current target set still needs operator review before dispatch.',
    };
  }

  return {
    tone: 'good',
    title: 'Package and live scope are clear for launch review',
    detail: 'Assignments, mission setup, and live target status are aligned for dispatch.',
  };
}

const QuickScoutLaunchReview = ({
  coveragePlan = null,
  missionLabel = '',
  missionBrief = '',
  missionProfileId = '',
  returnBehavior = 'return_home',
  surveyConfig = {},
  targetHwIds = [],
  targetSummaryLabel = '',
  targetDrones = [],
  launchReadiness = null,
  planNeedsRecompute = false,
  currentMissionState = null,
}) => {
  if (!coveragePlan) {
    return null;
  }

  const profile = getQuickScoutProfile(missionProfileId);
  const status = getLaunchStatus(planNeedsRecompute, launchReadiness);
  const blockers = [
    ...(planNeedsRecompute
      ? [{
        key: 'recompute-required',
        label: 'Package drift',
        detail: 'Current setup no longer matches the computed QuickScout package.',
      }]
      : []),
    ...((launchReadiness?.blockers) || []),
  ];
  const warnings = launchReadiness?.warnings || [];
  const metrics = [
    {
      label: 'Mission',
      value: missionLabel || 'Untitled QuickScout mission',
    },
    {
      label: 'Profile',
      value: profile?.label || (missionProfileId ? missionProfileId.replace(/_/g, ' ') : 'Custom'),
    },
    {
      label: 'Area',
      value: formatArea(coveragePlan.total_area_sq_m),
    },
    {
      label: 'Coverage Time',
      value: formatDuration(coveragePlan.estimated_coverage_time_s),
    },
    {
      label: 'Assignments',
      value: `${targetHwIds.length} drone${targetHwIds.length === 1 ? '' : 's'}`,
    },
    {
      label: 'End Behavior',
      value: getReturnBehaviorLabel(returnBehavior),
    },
  ];

  return (
    <div className="qs-config-section qs-launch-review">
      <div className="qs-launch-review__header">
        <div>
          <div className="qs-config-title" style={{ marginBottom: 4 }}>
            Launch Review
          </div>
          <div className="qs-launch-review__subtitle">
            Review the mission package and live aircraft scope before dispatch.
          </div>
        </div>
        {currentMissionState && (
          <span className={`qs-state-badge ${currentMissionState}`}>
            {currentMissionState}
          </span>
        )}
      </div>

      <div className={`qs-launch-review__banner qs-launch-review__banner--${status.tone}`}>
        <strong>{status.title}</strong>
        <span>{status.detail}</span>
      </div>

      <div className="qs-launch-review__grid">
        {metrics.map((metric) => (
          <div key={metric.label} className="qs-launch-review__metric">
            <span className="qs-launch-review__metric-label">{metric.label}</span>
            <strong className="qs-launch-review__metric-value">{metric.value}</strong>
          </div>
        ))}
      </div>

      {missionBrief ? (
        <div className="qs-launch-review__brief">
          <span className="qs-launch-review__brief-label">Mission brief</span>
          <p>{missionBrief}</p>
        </div>
      ) : null}

      <details className="qs-launch-review__details">
        <summary>Package settings</summary>
        <div className="qs-launch-review__chip-row">
          <span className="qs-inline-chip">Pattern {surveyConfig.algorithm || 'boustrophedon'}</span>
          <span className="qs-inline-chip">Survey alt {surveyConfig.survey_altitude_agl ?? '--'} m AGL</span>
          <span className="qs-inline-chip">Sweep {surveyConfig.sweep_width_m ?? '--'} m</span>
          <span className="qs-inline-chip">Survey {surveyConfig.survey_speed_ms ?? '--'} m/s</span>
          <span className="qs-inline-chip">
            Terrain {surveyConfig.use_terrain_following ? 'On' : 'Off'}
          </span>
        </div>
      </details>

      {blockers.length > 0 && (
        <div className="qs-launch-review__issue-group">
          <div className="qs-launch-review__issue-title">Launch blockers</div>
          <ul className="qs-launch-review__issue-list">
            {blockers.map((issue) => (
              <li key={issue.key}>
                <strong>{issue.label}:</strong> {issue.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="qs-launch-review__issue-group qs-launch-review__issue-group--warning">
          <div className="qs-launch-review__issue-title">Advisories</div>
          <ul className="qs-launch-review__issue-list">
            {warnings.map((issue) => (
              <li key={issue.key}>
                <strong>{issue.label}:</strong> {issue.detail}
              </li>
            ))}
          </ul>
        </div>
      )}

      <CommandPreflightSummary
        drones={targetDrones}
        targetMode="selected"
        targetDroneIds={targetHwIds}
        targetSummaryLabel={targetSummaryLabel}
      />
    </div>
  );
};

QuickScoutLaunchReview.propTypes = {
  coveragePlan: PropTypes.object,
  missionLabel: PropTypes.string,
  missionBrief: PropTypes.string,
  missionProfileId: PropTypes.string,
  returnBehavior: PropTypes.string,
  surveyConfig: PropTypes.object,
  targetHwIds: PropTypes.array,
  targetSummaryLabel: PropTypes.string,
  targetDrones: PropTypes.array,
  launchReadiness: PropTypes.shape({
    canLaunch: PropTypes.bool,
    blockers: PropTypes.array,
    warnings: PropTypes.array,
  }),
  planNeedsRecompute: PropTypes.bool,
  currentMissionState: PropTypes.string,
};

export default QuickScoutLaunchReview;
