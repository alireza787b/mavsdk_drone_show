import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';

import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import { areGitRevisionsEquivalent } from '../utilities/missionIdentityUtils';
import { getDroneDisplayIdentity } from '../utilities/dronePresentation';
import { FIELD_NAMES } from '../constants/fieldMappings';
import '../styles/CommandPreflightSummary.css';

const MAX_VISIBLE_EXCEPTIONS = 8;

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

  const summary = useMemo(() => {
    const roster = new Map();
    drones.forEach((drone) => {
      const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID]);
      if (hwId && !roster.has(hwId)) roster.set(hwId, drone);
    });
    const scopeIds = targetMode === 'all'
      ? [...roster.keys()]
      : [...new Set(targetDroneIds.map(normalizeId).filter(Boolean))];
    const counts = {
      configured: scopeIds.length,
      online: 0,
      degraded: 0,
      unavailable: 0,
      ready: 0,
      review: 0,
      blocked: 0,
      armed: 0,
      disarmed: 0,
      armUnknown: 0,
    };
    const gcsGitStatus = gitStatusResponse?.gcs_status || null;
    const gitStatusByDrone = gitStatusResponse?.git_status || {};
    let gitInSync = 0;
    let gitUnknown = 0;
    let gitMismatch = 0;
    const exceptions = [];

    scopeIds.forEach((hwId) => {
      const drone = roster.get(hwId);
      const identity = drone ? getDroneDisplayIdentity(drone) : { primary: `HW ${hwId}` };
      const droneGitStatus = gitStatusByDrone[hwId];
      const runtimeStatus = getDroneRuntimeStatus(drone, referenceNowMs);
      const readiness = getDroneReadinessModel(drone, runtimeStatus);
      const liveTelemetry = runtimeStatus.level === 'online'
        && drone?.[FIELD_NAMES.TELEMETRY_AVAILABLE] !== false;
      const ready = liveTelemetry && readiness.isReady;

      if (liveTelemetry) counts.online += 1;
      else if (runtimeStatus.level === 'degraded') counts.degraded += 1;
      else counts.unavailable += 1;

      if (ready) counts.ready += 1;
      else if (liveTelemetry && readiness.status === 'warning') counts.review += 1;
      else counts.blocked += 1;

      if (liveTelemetry && drone?.[FIELD_NAMES.IS_ARMED] === true) counts.armed += 1;
      else if (liveTelemetry && drone?.[FIELD_NAMES.IS_ARMED] === false) counts.disarmed += 1;
      else counts.armUnknown += 1;

      if (!liveTelemetry) {
        exceptions.push({
          key: `runtime-${hwId}`,
          group: 'link',
          label: identity.primary,
          detail: !drone ? 'Selected aircraft unavailable' : runtimeStatus.level === 'online'
            ? 'Telemetry unavailable' : runtimeStatus.label,
          state: runtimeStatus.level === 'offline' ? 'danger' : 'warning',
        });
      }

      if (!ready) {
        exceptions.push({
          key: `readiness-${hwId}`,
          group: 'readiness',
          label: identity.primary,
          detail: liveTelemetry ? readiness.statusLabel : 'Live readiness unavailable',
          state: !liveTelemetry || readiness.status === 'blocked' ? 'danger' : 'warning',
        });
      } else if (readiness.warnings.length > 0) {
        exceptions.push({
          key: `readiness-warning-${hwId}`,
          group: 'readiness',
          label: identity.primary,
          detail: readiness.warnings[0].message,
          state: 'warning',
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
      exceptions,
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
      state: !summary.counts.configured ? 'neutral' : summary.counts.unavailable > 0 ? 'danger' : summary.counts.degraded > 0 ? 'warning' : 'good',
      tooltip: `${summary.counts.online} targets have fresh telemetry, ${summary.counts.degraded} are delayed, and ${summary.counts.unavailable} are currently unavailable.`,
      exceptionCount: metricExceptionCounts.link || 0,
    },
    {
      key: 'readiness',
      label: 'Readiness',
      value: `${summary.counts.ready}/${summary.counts.configured}`,
      detail: `${summary.counts.review} review · ${summary.counts.blocked} blocked`,
      state: !summary.counts.configured ? 'neutral' : summary.counts.blocked > 0 ? 'danger' : summary.exceptions.some((exception) => exception.group === 'readiness' && exception.state === 'warning') ? 'warning' : 'good',
      tooltip: `${summary.counts.ready} targets are ready, ${summary.counts.review} need review, and ${summary.counts.blocked} are blocked for launch or dispatch. Advisory warnings do not block an armable target.`,
      exceptionCount: metricExceptionCounts.readiness || 0,
    },
    {
      key: 'armed',
      label: 'Armed',
      value: summary.counts.armed,
      detail: `${summary.counts.disarmed} disarmed · ${summary.counts.armUnknown} unknown`,
      state: summary.counts.armed > 0 ? 'warning' : 'neutral',
      tooltip: `${summary.counts.armed} targets are observed armed, ${summary.counts.disarmed} observed disarmed, and ${summary.counts.armUnknown} have unknown or stale arm state.`,
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
  const matchingExceptions = activeExceptionGroup
    ? summary.exceptions.filter((exception) => exception.group === activeExceptionGroup)
    : summary.exceptions;
  const displayedExceptions = matchingExceptions.slice(0, MAX_VISIBLE_EXCEPTIONS);
  const hasTargets = summary.counts.configured > 0;
  const hasReadinessBlocker = summary.counts.ready < summary.counts.configured;
  const hasReadinessCaution = summary.exceptions.some(
    (exception) => exception.group === 'readiness' && exception.state === 'warning',
  );
  const overallState = !hasTargets ? 'neutral' : hasReadinessBlocker ? 'danger' : hasReadinessCaution ? 'warning' : 'good';
  const overallLabel = !hasTargets ? 'NO TARGETS' : hasReadinessBlocker
    ? 'NOT READY'
    : hasReadinessCaution
      ? 'READY · CAUTION'
      : 'READY';

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
          <h3>Flight readiness</h3>
          <div className="command-preflight__header-meta">
            <span className={`command-preflight__state command-preflight__state--${overallState}`}>
              <span className="command-preflight__state-dot" aria-hidden="true" />
              {overallLabel}
            </span>
            <span className="command-preflight__header-pill">{targetSummaryLabel || 'Current scope'}</span>
            <span className="command-preflight__header-pill command-preflight__header-pill--secondary">
              {clockOffsetLabel ? `Scheduler ${clockOffsetLabel}` : 'Scheduler aligned'}
            </span>
          </div>
        </div>
      </div>

      <div className="command-preflight__grid">
        {metrics.map((metric) => (
          <button
            key={metric.key}
            type="button"
            className={`command-preflight__metric command-preflight__metric--${metric.state}`}
            title={metric.tooltip}
            onClick={() => handleMetricClick(metric)}
            disabled={!metric.exceptionCount}
            aria-pressed={activeExceptionGroup === metric.key}
          >
            <span className="command-preflight__metric-label">{metric.label}</span>
            <strong>{metric.value}</strong>
            <small>{metric.detail}</small>
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
            aria-expanded={exceptionsExpanded}
          >
            {activeExceptionGroup ? 'Focused attention' : 'Attention'}
            <span>({displayedExceptions.length}/{matchingExceptions.length})</span>
          </button>
          {exceptionsExpanded ? (
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
            {matchingExceptions.length > displayedExceptions.length && (
              <p className="command-preflight__remaining">
                {matchingExceptions.length - displayedExceptions.length} more entries. Select a metric to narrow the list.
              </p>
            )}
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
