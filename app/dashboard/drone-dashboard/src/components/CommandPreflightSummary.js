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

    targetDrones.forEach((drone) => {
      const hwId = normalizeId(drone?.[FIELD_NAMES.HW_ID]);
      const droneGitStatus = gitStatusByDrone[hwId];
      if (!droneGitStatus?.commit || !gcsGitStatus?.commit) {
        gitUnknown += 1;
        return;
      }

      if (areGitRevisionsEquivalent(droneGitStatus.commit, gcsGitStatus.commit)) {
        gitInSync += 1;
      }
    });

    return {
      counts,
      git: {
        inSync: gitInSync,
        unknown: gitUnknown,
      },
      gcsBranch: gcsGitStatus?.branch || gcsGitStatus?.current_branch || '',
    };
  }, [drones, gitStatusResponse, referenceNowMs, selectedDrones, targetMode]);

  const gitReadyCount = summary.counts.configured - summary.git.unknown;
  const gitStatusLabel = gitLoading
    ? 'Checking git state'
    : gitReadyCount <= 0
      ? 'Git status unavailable'
      : `${summary.git.inSync}/${summary.counts.configured} match GCS`;

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
        <div className="command-preflight__metric">
          <span className="command-preflight__metric-label">Targets</span>
          <strong>{summary.counts.configured}</strong>
          <small>{targetMode === 'selected' ? 'Selected drones' : 'All configured drones'}</small>
        </div>
        <div className="command-preflight__metric">
          <span className="command-preflight__metric-label">Live Link</span>
          <strong>{summary.counts.online}/{summary.counts.configured}</strong>
          <small>{summary.counts.degraded} delayed · {summary.counts.unavailable} unavailable</small>
        </div>
        <div className="command-preflight__metric">
          <span className="command-preflight__metric-label">Readiness</span>
          <strong>{summary.counts.ready}/{summary.counts.configured}</strong>
          <small>{summary.counts.review} review · {summary.counts.blocked} blocked</small>
        </div>
        <div className="command-preflight__metric">
          <span className="command-preflight__metric-label">Armed</span>
          <strong>{summary.counts.armed}</strong>
          <small>{summary.counts.configured - summary.counts.armed} disarmed</small>
        </div>
        <div className="command-preflight__metric">
          <span className="command-preflight__metric-label">Git Sync</span>
          <strong>{gitStatusLabel}</strong>
          <small>{summary.gcsBranch ? `GCS branch ${summary.gcsBranch}` : 'GCS branch unknown'}</small>
        </div>
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
