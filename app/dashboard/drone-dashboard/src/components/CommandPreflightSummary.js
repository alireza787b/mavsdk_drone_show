import React, { useMemo } from 'react';
import PropTypes from 'prop-types';

import useNormalizedTelemetry from '../hooks/useNormalizedTelemetry';
import { getDroneRuntimeStatus } from '../utilities/droneRuntimeStatus';
import { getDroneReadinessModel } from '../utilities/droneReadiness';
import { areGitRevisionsEquivalent } from '../utilities/missionIdentityUtils';
import { FIELD_NAMES } from '../constants/fieldMappings';
import '../styles/CommandSender.css';

function normalizeId(value) {
  return String(value ?? '').trim();
}

const CommandPreflightSummary = ({
  drones = [],
  targetMode = 'all',
  selectedDrones = [],
  referenceNowMs = Date.now(),
  clockOffsetLabel = null,
}) => {
  const { data: gitStatusResponse, loading: gitLoading } = useNormalizedTelemetry('/git-status', 15000);

  const summary = useMemo(() => {
    const selectedLookup = new Set(selectedDrones.map((value) => normalizeId(value)).filter(Boolean));
    const targetDrones = targetMode === 'selected'
      ? drones.filter((drone) => selectedLookup.has(normalizeId(drone?.[FIELD_NAMES.HW_ID])))
      : drones;

    const counts = {
      configured: targetMode === 'selected' ? selectedLookup.size : drones.length,
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

    targetDrones.forEach((drone) => {
      const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID]);
      const droneGitStatus = gitStatusByDrone[hwId];
      if (!droneGitStatus?.commit || !gcsGitStatus?.commit) {
        gitUnknown += 1;
        return;
      }

      if (areGitRevisionsEquivalent(droneGitStatus.commit, gcsGitStatus.commit)) {
        gitInSync += 1;
      } else {
        gitMismatch += 1;
      }
    });

    return {
      counts,
      git: {
        inSync: gitInSync,
        unknown: gitUnknown,
        mismatch: gitMismatch,
      },
      gcsBranch: gcsGitStatus?.branch || gcsGitStatus?.current_branch || '',
    };
  }, [drones, gitStatusResponse, referenceNowMs, selectedDrones, targetMode]);

  const gitReadyCount = summary.counts.configured - summary.git.unknown;
  const gitStatusLabel = !gitStatusResponse
    ? (gitLoading ? 'Checking git state' : 'Git status unavailable')
    : gitReadyCount <= 0
      ? 'Git status unavailable'
      : `${summary.git.inSync}/${summary.counts.configured} match GCS`;

  const metrics = [
    {
      key: 'targets',
      label: 'Targets',
      value: summary.counts.configured,
      detail: targetMode === 'selected' ? 'Selected drones' : 'All configured drones',
      state: 'neutral',
      tooltip: targetMode === 'selected'
        ? `${summary.counts.configured} selected drones are in scope for the next command.`
        : `${summary.counts.configured} configured drones are in scope for the next command.`,
    },
    {
      key: 'link',
      label: 'Live Link',
      value: `${summary.counts.online}/${summary.counts.configured}`,
      detail: `${summary.counts.degraded} delayed · ${summary.counts.unavailable} unavailable`,
      state: summary.counts.unavailable > 0 ? 'danger' : summary.counts.degraded > 0 ? 'warning' : 'good',
      tooltip: `${summary.counts.online} targets have fresh telemetry, ${summary.counts.degraded} are delayed, and ${summary.counts.unavailable} are currently unavailable.`,
    },
    {
      key: 'readiness',
      label: 'Readiness',
      value: `${summary.counts.ready}/${summary.counts.configured}`,
      detail: `${summary.counts.review} review · ${summary.counts.blocked} blocked`,
      state: summary.counts.blocked > 0 ? 'danger' : summary.counts.review > 0 ? 'warning' : 'good',
      tooltip: `${summary.counts.ready} targets are ready, ${summary.counts.review} need review, and ${summary.counts.blocked} are blocked for launch or dispatch.`,
    },
    {
      key: 'armed',
      label: 'Armed',
      value: summary.counts.armed,
      detail: `${summary.counts.configured - summary.counts.armed} disarmed`,
      state: summary.counts.armed > 0 ? 'warning' : 'neutral',
      tooltip: `${summary.counts.armed} targets are armed and ${summary.counts.configured - summary.counts.armed} are disarmed.`,
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
    },
  ];

  return (
    <section className="command-preflight" aria-label="Command preflight summary">
      <div className="command-preflight__header">
        <div>
          <h3>Preflight Review</h3>
          <p>Scope, live link, readiness, and repo state for the current target set.</p>
        </div>
        <div className="command-preflight__clock">
          <span className="command-preflight__clock-label">Scheduler clock</span>
          <span className="command-preflight__clock-value">{clockOffsetLabel ? `GCS aligned · ${clockOffsetLabel}` : 'GCS aligned'}</span>
        </div>
      </div>

      <div className="command-preflight__grid">
        {metrics.map((metric) => (
          <div
            key={metric.key}
            className={`command-preflight__metric command-preflight__metric--${metric.state}`}
            title={metric.tooltip}
          >
            <span className="command-preflight__metric-label">{metric.label}</span>
            <strong>{metric.value}</strong>
            <small>{metric.detail}</small>
          </div>
        ))}
      </div>
    </section>
  );
};

CommandPreflightSummary.propTypes = {
  drones: PropTypes.array,
  targetMode: PropTypes.oneOf(['all', 'selected']),
  selectedDrones: PropTypes.array,
  referenceNowMs: PropTypes.number,
  clockOffsetLabel: PropTypes.string,
};

export default CommandPreflightSummary;
