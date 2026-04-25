import React from 'react';
import PropTypes from 'prop-types';

import { formatDroneLabel, formatShowSlotLabel } from '../../utilities/missionIdentityUtils';

export default function PendingEnrollmentPanel({
  candidates,
  panelRef,
  onOpenQueue,
  onReviewCandidate,
}) {
  if (!candidates.length) {
    return null;
  }

  return (
    <section
      ref={panelRef}
      className="mission-config-pending-panel"
      aria-label="Detected nodes pending enrollment"
    >
      <div className="mission-config-pending-panel__header">
        <div>
          <h3>Detected, not enrolled</h3>
          <p>
            Heartbeat-only nodes stay out of fleet config until reviewed.
          </p>
        </div>
        <div className="mission-config-pending-panel__header-actions">
          <span className="mission-config-pending-panel__count">
            {candidates.length} candidate{candidates.length === 1 ? '' : 's'}
          </span>
          <button
            type="button"
            className="mission-config-primary-button mission-config-primary-button--add"
            onClick={onOpenQueue}
          >
            Review enrollment queue
          </button>
        </div>
      </div>
      <div className="mission-config-pending-grid">
        {candidates.map((candidate) => (
          <article key={candidate.hw_id} className="mission-config-pending-card">
            <div className="mission-config-pending-card__identity">
              <strong>{formatDroneLabel(candidate.hw_id)}</strong>
              <span>
                {candidate.pos_id
                  ? `${formatShowSlotLabel(candidate.pos_id)} reported`
                  : candidate.detected_pos_id
                    ? `${formatShowSlotLabel(candidate.detected_pos_id)} detected`
                    : 'No slot hint reported'}
              </span>
            </div>
            <div className="mission-config-pending-card__meta">
              <span>{candidate.ip ? `IP ${candidate.ip}` : 'IP pending'}</span>
              <span>{candidate.mavlink_port ? `Port ${candidate.mavlink_port}` : 'Port pending'}</span>
              <span className={`mission-config-pending-status mission-config-pending-status--${candidate.heartbeatTone}`}>
                {candidate.heartbeatStatus}
                {candidate.heartbeatAgeSec !== null ? ` · ${candidate.heartbeatAgeSec}s` : ''}
              </span>
            </div>
            <p className="mission-config-pending-card__note">
              {candidate.registration_state === 'conflict'
                ? `Conflict: ${candidate.conflict_reasons.join(', ')}. Review before editing fleet config.`
                : 'Use Fleet Enrollment to add or replace this node.'}
            </p>
            <div className="mission-config-pending-card__actions">
              <button
                type="button"
                className="mission-config-primary-button mission-config-primary-button--add"
                onClick={() => onReviewCandidate(candidate.candidate_id)}
              >
                Review candidate
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

PendingEnrollmentPanel.propTypes = {
  candidates: PropTypes.arrayOf(PropTypes.shape({
    candidate_id: PropTypes.string,
    hw_id: PropTypes.string,
    pos_id: PropTypes.string,
    detected_pos_id: PropTypes.string,
    ip: PropTypes.string,
    mavlink_port: PropTypes.string,
    heartbeatTone: PropTypes.string,
    heartbeatStatus: PropTypes.string,
    heartbeatAgeSec: PropTypes.number,
    registration_state: PropTypes.string,
    conflict_reasons: PropTypes.arrayOf(PropTypes.string),
  })).isRequired,
  panelRef: PropTypes.oneOfType([
    PropTypes.func,
    PropTypes.shape({ current: PropTypes.any }),
  ]).isRequired,
  onOpenQueue: PropTypes.func.isRequired,
  onReviewCandidate: PropTypes.func.isRequired,
};
