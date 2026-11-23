import React from 'react';
import { Link } from 'react-router-dom';
import { FaChevronRight, FaRegClock } from 'react-icons/fa';
import { DRONE_MISSION_TYPES } from '../../constants/droneConstants';
import { formatCommandTargetIssue } from '../../utilities/commandLifecycleFeedback';

const MISSION_ROUTES = {
  [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: '/drone-show',
  [DRONE_MISSION_TYPES.SMART_SWARM]: '/swarm-design',
  [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: '/custom-show',
  [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: '/swarm-trajectory',
  [DRONE_MISSION_TYPES.QUICKSCOUT]: '/quickscout',
};

const OUTCOME = {
  completed: 'Complete', partial: 'Partial result', failed: 'Failed',
  timeout: 'Outcome unconfirmed', cancelled: 'Cancelled', superseded: 'Replaced',
};

export function commandStage(command) {
  if (command.trackingIssue) return 'Outcome unconfirmed';
  return OUTCOME[command.outcome] || OUTCOME[command.progress?.stage] || command.progress?.label || 'Awaiting command status';
}

export const commandTime = (command) => Number(command.updatedAtMs) || 0;

function aircraft(command) {
  return [...new Set((command.targetDrones || []).map(String).filter(id => id.trim()))];
}

export function memoAircraftLabel(ids) {
  if (!ids.length) return 'Aircraft unavailable';
  return ids.slice(0, 3).map(id => `H${id}`).join(', ') + (ids.length > 3 ? ` +${ids.length - 3}` : '');
}

export default function MemoCommands({ commands, label, onInspect }) {
  const groups = new Map();
  for (const command of commands) {
    const key = JSON.stringify([command.commandLabel, commandStage(command)]);
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(command);
  }
  if (!groups.size) return null;
  return <ul className="fleet-alert-list" aria-label={label}>
    {[...groups].map(([key, group]) => {
      const ids = [...new Set(group.flatMap(aircraft))];
      return <li key={key} className="fleet-alert-card fleet-alert-card--group">
        <details><summary>
          <FaRegClock className="fleet-alert-card__severity" aria-hidden="true" />
          <span className="fleet-alert-card__copy"><strong>{group[0].commandLabel} · {commandStage(group[0])}</strong>
            <small>{memoAircraftLabel(ids)}{group.length > 1 && ` · ${group.length} commands`}</small></span>
          <FaChevronRight className="fleet-alert-chevron" aria-hidden="true" />
        </summary>
          <div className="fleet-memo__receipts">{group.map(command => {
            const targets = aircraft(command);
            const issues = (command.targetIssues || []).slice(0, 8);
            const omitted = Math.max(0, (Number(command.targetIssueCount) || 0) - issues.length);
            const route = MISSION_ROUTES[command.missionType];
            return <div key={command.commandId} className="fleet-memo__receipt">
              <small>{targets.length ? targets.map(id => `H${id}`).join(', ') : 'Aircraft unavailable'}</small>
              <code>{command.commandId}</code>
              {command.errorSummary && <p>{command.errorSummary}</p>}
              {command.progress?.message && <p>{command.progress.message}</p>}
              {command.lateEvidence?.message && command.lateEvidence.message !== command.progress?.message
                && <p>{command.lateEvidence.message}</p>}
              {!!issues.length && <ul>{issues.map((issue, index) => <li key={index}>
                {formatCommandTargetIssue(issue, { includeStage: true })}
              </li>)}</ul>}
              {!!omitted && <small>{omitted} more affected aircraft in the receipt</small>}
              <Link className="fleet-memo__workspace" to={route || '/'} onClick={onInspect}>
                {route ? 'Open mission workspace' : 'Open fleet controls'} <FaChevronRight aria-hidden="true" />
              </Link>
            </div>;
          })}</div>
        </details>
      </li>;
    })}
  </ul>;
}
