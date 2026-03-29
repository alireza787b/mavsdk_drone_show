import React from 'react';
import { Link } from 'react-router-dom';
import TrajectoryPolicyNotes from './TrajectoryPolicyNotes';
import { getSwarmTrajectoryExecutionDoctrine } from '../../utilities/trajectoryAuthoringGuidance';

const SwarmTrajectoryWorkspaceSummary = ({ workspaceStatus, stages, session }) => {
  const doctrine = getSwarmTrajectoryExecutionDoctrine();

  return (
    <div className="swarm-workspace-summary">
      <div className={`swarm-workspace-status swarm-workspace-status--${workspaceStatus.tone}`}>
        <div className="swarm-workspace-status__body">
          <span className="swarm-workspace-status__eyebrow">Workspace Status</span>
          <strong>{workspaceStatus.title}</strong>
          <p>{workspaceStatus.message}</p>
          {workspaceStatus.details?.length ? (
            <ul className="swarm-workspace-status__details">
              {workspaceStatus.details.map((detail) => (
                <li key={detail}>{detail}</li>
              ))}
            </ul>
          ) : null}
        </div>
        {session?.exists ? (
          <div className="swarm-workspace-session">
            <span className="swarm-workspace-session__label">Current Session</span>
            <strong>{session.session_id}</strong>
            <span>{session.total_drones} processed drone{session.total_drones === 1 ? '' : 's'}</span>
          </div>
        ) : null}
      </div>

      <TrajectoryPolicyNotes notes={doctrine} title="Swarm trajectory execution policy" />

      <div className="swarm-stage-grid" aria-label="Swarm trajectory workflow stages">
        {stages.map((stage) => (
          <article key={stage.id} className={`swarm-stage-card swarm-stage-card--${stage.tone}`}>
            <div className="swarm-stage-card__header">
              <span className="swarm-stage-card__step">Step {stage.step}</span>
              <span className={`swarm-stage-card__badge swarm-stage-card__badge--${stage.tone}`}>{stage.label}</span>
            </div>
            <h3>{stage.title}</h3>
            <p>{stage.summary}</p>
            {stage.details?.length ? (
              <ul className="swarm-stage-card__details">
                {stage.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            ) : null}
            {stage.actionHref ? (
              <Link to={stage.actionHref} className="swarm-stage-card__link">
                {stage.actionLabel}
              </Link>
            ) : null}
          </article>
        ))}
      </div>
    </div>
  );
};

export default SwarmTrajectoryWorkspaceSummary;
