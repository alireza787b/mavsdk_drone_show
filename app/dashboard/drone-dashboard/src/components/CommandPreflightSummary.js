import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';

import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import { areGitRevisionsEquivalent } from '../utilities/missionIdentityUtils';
import { getDroneDisplayIdentity } from '../utilities/dronePresentation';
import { FIELD_NAMES } from '../constants/fieldMappings';
import '../styles/CommandSender.css';

function normalizeId(value) {
  return String(value ?? '').trim();
}

const CommandPreflightSummary = ({
  drones = [],
  targetMode = 'all',
  targetDroneIds = [],
  targetSummaryLabel = '',
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
}) => {
  const { data: gitStatusResponse, loading: gitLoading } = useNormalizedTelemetry(GCS_ROUTE_KEYS.gitStatus, 15000);
  const [activeExceptionGroup, setActiveExceptionGroup] = useState(null);
  const [exceptionsExpanded, setExceptionsExpanded] = useState(false);
  const [detailsExpanded, setDetailsExpanded] = useState(false);

  const summary = useMemo(() => {
    const scopedLookup = new Set(targetDroneIds.map((value) => normalizeId(value)).filter(Boolean));
    const isScopedTarget = targetMode !== 'all';
    const targetDrones = isScopedTarget
      ? drones.filter((drone) => scopedLookup.has(normalizeId(drone?.[FIELD_NAMES.HW_ID])))
      : drones;

    const counts = {
      configured: isScopedTarget ? scopedLookup.size : drones.length,
      online: 0,
      degraded: 0,
      unavailable: 0,
      ready: 0,
      review: 0,
      blocked: 0,
      armed: 0,
    };

    targetDrones.forEach((drone) => {
      const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
      const readiness = getDroneReadinessModel(drone, runtimeStatus);

      if (runtimeStatus.level === 'online') {
        counts.online += 1;
      } else if (runtimeStatus.level === 'degraded') {
        counts.degraded += 1;
      } else {
        counts.unavailable += 1;
      }

      if (readiness.isReady) {
        counts.ready += 1;
      } else if (readiness.status === 'warning') {
        counts.review += 1;
      } else {
        counts.blocked += 1;
      }

      if (drone?.[FIELD_NAMES.IS_ARMED]) {
        counts.armed += 1;
      }
    });

    const gcsGitStatus = gitStatusResponse?.gcs_status || null;
    const gitStatusByDrone = gitStatusResponse?.git_status || {};
    let gitInSync = 0;
    let gitUnknown = 0;
    let gitMismatch = 0;
    const exceptions = [];

    targetDrones.forEach((drone) => {
      const identity = getDroneDisplayIdentity(drone);
      const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID]);
      const droneGitStatus = gitStatusByDrone[hwId];
      const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
      const readiness = getDroneReadinessModel(drone, runtimeStatus);

      if (runtimeStatus.level !== 'online') {
        exceptions.push({
          key: `runtime-${hwId}`,
          group: 'link',
          label: identity.primary,
          detail: runtimeStatus.label,
          state: runtimeStatus.level === 'offline' ? 'danger' : 'warning',
        });
      }

      if (!readiness.isReady) {
        exceptions.push({
          key: `readiness-${hwId}`,
          group: 'readiness',
          label: identity.primary,
          detail: readiness.statusLabel,
          state: readiness.status === 'blocked' ? 'danger' : 'warning',
        });
      }

      if (!droneGitStatus?.commit || !gcsGitStatus?.commit) {
        gitUnknown += 1;
        exceptions.push({
          key: `git-unknown-${hwId}`,
          group: 'git',
          label: identity.primary,
          detail: 'Git status unavailable',
          state: 'warning',
        });
        return;
      }

      if (areGitRevisionsEquivalent(droneGitStatus.commit, gcsGitStatus.commit)) {
        gitInSync += 1;
      } else {
        gitMismatch += 1;
        exceptions.push({
          key: `git-mismatch-${hwId}`,
          group: 'git',
          label: identity.primary,
          detail: 'Git mismatch',
          state: 'danger',
        });
      }
    });

    return {
      counts,
      git: {
        inSync: gitInSync,
        unknown: gitUnknown,
        mismatch: gitMismatch,
      },
      exceptions: exceptions.slice(0, 8),
      gcsBranch: gcsGitStatus?.branch || gcsGitStatus?.current_branch || '',
    };
  }, [drones, gitStatusResponse, referenceNowMs, targetDroneIds, targetMode]);

  const gitReadyCount = summary.counts.configured - summary.git.unknown;
  const metricExceptionCounts = useMemo(() => summary.exceptions.reduce((accumulator, exception) => {
    const key = exception.group || 'other';
    accumulator[key] = (accumulator[key] || 0) + 1;
    return accumulator;
  }, {}), [summary.exceptions]);
  const gitStatusLabel = !gitStatusResponse
    ? (gitLoading ? 'Checking git state' : 'Git status unavailable')
    : gitReadyCount <= 0
      ? 'Git status unavailable'
      : `${summary.git.inSync}/${summary.counts.configured} match GCS`;

  const metrics = [
    {
      key: 'link',
      label: 'Live Link',
      value: `${summary.counts.online}/${summary.counts.configured}`,
      detail: `${summary.counts.degraded} delayed · ${summary.counts.unavailable} unavailable`,
      state: summary.counts.unavailable > 0 ? 'danger' : summary.counts.degraded > 0 ? 'warning' : 'good',
      tooltip: `${summary.counts.online} targets have fresh telemetry, ${summary.counts.degraded} are delayed, and ${summary.counts.unavailable} are currently unavailable.`,
      exceptionCount: metricExceptionCounts.link || 0,
    },
    {
      key: 'readiness',
      label: 'Readiness',
      value: `${summary.counts.ready}/${summary.counts.configured}`,
      detail: `${summary.counts.review} review · ${summary.counts.blocked} blocked`,
      state: summary.counts.blocked > 0 ? 'danger' : summary.counts.review > 0 ? 'warning' : 'good',
      tooltip: `${summary.counts.ready} targets are ready, ${summary.counts.review} need review, and ${summary.counts.blocked} are blocked for launch or dispatch.`,
      exceptionCount: metricExceptionCounts.readiness || 0,
    },
    {
      key: 'armed',
      label: 'Armed',
      value: summary.counts.armed,
      detail: `${summary.counts.configured - summary.counts.armed} disarmed`,
      state: summary.counts.armed > 0 ? 'warning' : 'neutral',
      tooltip: `${summary.counts.armed} targets are armed and ${summary.counts.configured - summary.counts.armed} are disarmed.`,
      exceptionCount: 0,
    },
    {
      key: 'git',
      label: 'Git Sync',
      value: gitStatusLabel,
      detail: summary.gcsBranch ? `GCS branch ${summary.gcsBranch}` : 'GCS branch unknown',
      state: summary.git.mismatch > 0 ? 'danger' : summary.git.unknown > 0 ? 'warning' : gitReadyCount > 0 ? 'good' : 'neutral',
      tooltip: gitReadyCount <= 0
        ? 'Git commit information is not available for the current targets yet.'
        : `${summary.git.inSync} targets match the GCS commit, ${summary.git.mismatch} differ, and ${summary.git.unknown} are still unknown.`,
      exceptionCount: metricExceptionCounts.git || 0,
    },
  ];
  const displayedExceptions = activeExceptionGroup
    ? summary.exceptions.filter((exception) => exception.group === activeExceptionGroup)
    : summary.exceptions;

  const handleMetricClick = (metric) => {
    if (!metric.exceptionCount) {
      return;
    }
    setExceptionsExpanded(true);
    setActiveExceptionGroup((current) => (current === metric.key ? null : metric.key));
  };

  return (
    <section className="command-preflight" aria-label="Command preflight summary">
      <div className="command-preflight__header">
        <div className="command-preflight__header-copy">
          <h3>Preflight</h3>
          <div className="command-preflight__header-meta">
            <span className="command-preflight__header-pill">{targetSummaryLabel || 'Current scope'}</span>
            <span className="command-preflight__header-pill command-preflight__header-pill--secondary">
              {clockOffsetLabel ? `Scheduler ${clockOffsetLabel}` : 'Scheduler aligned'}
            </span>
          </div>
        </div>
        <button
          type="button"
          className="command-preflight__toggle"
          onClick={() => setDetailsExpanded((current) => !current)}
          aria-expanded={detailsExpanded}
        >
          {detailsExpanded ? 'Hide' : 'Details'}
        </button>
      </div>

      <div className={`command-preflight__grid ${detailsExpanded ? 'is-expanded' : ''}`}>
        {metrics.map((metric) => (
          <button
            key={metric.key}
            type="button"
            className={`command-preflight__metric command-preflight__metric--${metric.state}`}
            title={metric.tooltip}
            onClick={() => handleMetricClick(metric)}
            disabled={!metric.exceptionCount}
          >
            <span className="command-preflight__metric-label">{metric.label}</span>
            <strong>{metric.value}</strong>
            {detailsExpanded ? <small>{metric.detail}</small> : null}
            {metric.exceptionCount ? (
              <span className="command-preflight__metric-badge">{metric.exceptionCount}</span>
            ) : null}
          </button>
        ))}
      </div>

      {summary.exceptions.length > 0 && (
        <div className="command-preflight__exceptions">
          <button
            type="button"
            className="command-preflight__exceptions-toggle"
            onClick={() => setExceptionsExpanded((current) => !current)}
          >
            {activeExceptionGroup ? 'Focused attention' : 'Attention'}
            <span>({displayedExceptions.length}/{summary.exceptions.length})</span>
          </button>
          {exceptionsExpanded || detailsExpanded ? (
          <div className="command-preflight__exception-list">
            {displayedExceptions.map((exception) => (
              <div
                key={exception.key}
                className={`command-preflight__exception command-preflight__exception--${exception.state}`}
              >
                <strong>{exception.label}</strong>
                <span>{exception.detail}</span>
              </div>
            ))}
          </div>
          ) : null}
        </div>
      )}
    </section>
  );
};

CommandPreflightSummary.propTypes = {
  drones: PropTypes.array,
  targetMode: PropTypes.oneOf(['all', 'selected', 'cluster']),
  targetDroneIds: PropTypes.array,
  targetSummaryLabel: PropTypes.string,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
};

export default CommandPreflightSummary;
