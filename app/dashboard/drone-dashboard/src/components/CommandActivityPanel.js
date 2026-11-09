import React, { useId, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';

import { useCommandActivity } from '../contexts/CommandActivityContext';
import { DRONE_MISSION_TYPES } from '../constants/droneConstants';
import { formatCommandTargetIssue } from '../utilities/commandLifecycleFeedback';
import '../styles/CommandActivityPanel.css';

const MAX_COMMANDS = 8;
const MAX_TARGET_ISSUES = 8;
const MISSION_ROUTES = {
  [DRONE_MISSION_TYPES.DRONE_SHOW_FROM_CSV]: '/drone-show',
  [DRONE_MISSION_TYPES.SMART_SWARM]: '/swarm-design',
  [DRONE_MISSION_TYPES.CUSTOM_CSV_DRONE_SHOW]: '/custom-show',
  [DRONE_MISSION_TYPES.SWARM_TRAJECTORY]: '/swarm-trajectory',
  [DRONE_MISSION_TYPES.QUICKSCOUT]: '/quickscout',
};
const OUTCOME_LABELS = {
  completed: 'Complete', partial: 'Partial result', failed: 'Failed',
  timeout: 'Outcome unconfirmed', cancelled: 'Cancelled', superseded: 'Replaced',
};

function targetIds(monitor) {
  return [...new Set((monitor?.targetDrones || []).map(String).filter((id) => id.trim()))];
}

function targetCountLabel(monitor) {
  const count = targetIds(monitor).length;
  return count ? `${count} aircraft` : 'Targets not reported';
}

function stageLabel(monitor) {
  if (monitor.trackingIssue) return monitor.trackingIssue === 'timeout' ? 'Outcome unconfirmed' : 'Tracking unavailable';
  return OUTCOME_LABELS[monitor.outcome] || OUTCOME_LABELS[monitor.progress?.stage]
    || monitor.progress?.label || 'Awaiting command status';
}

function monitorTone(monitor) {
  if (monitor.outcome === 'failed' || monitor.progress?.stage === 'failed') return 'danger';
  if (monitor.trackingIssue || ['partial', 'timeout'].includes(monitor.outcome)
    || ['partial', 'timeout'].includes(monitor.progress?.stage)) return 'warning';
  if (monitor.outcome === 'superseded') return 'neutral';
  return Number(monitor.targetIssueCount || 0) > 0 || monitor.targetIssues?.length ? 'warning' : 'neutral';
}

// Read-only projection: flight actions and receipt recovery belong to the
// owning workspace. No second transaction manager, journal or fleet polling.
export default function CommandActivityPanel({ className = '' }) {
  const { commandMonitors = [], dismissCommandMonitor } = useCommandActivity();
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const seen = new Set();
  const monitors = commandMonitors.filter((monitor) => {
    if (!monitor?.commandId || seen.has(monitor.commandId)) return false;
    seen.add(monitor.commandId);
    return true;
  }).slice(0, MAX_COMMANDS);
  const activeCount = monitors.filter((monitor) => !monitor.isTerminal).length;
  const attentionCount = monitors.filter((monitor) => monitorTone(monitor) !== 'neutral').length;
  const leading = monitors.find((monitor) => monitorTone(monitor) !== 'neutral')
    || monitors.find((monitor) => !monitor.isTerminal) || monitors[0];

  return (
    <section className={`command-activity ${attentionCount ? 'command-activity--attention' : ''} ${className}`}
      aria-label="Command activity">
      <button type="button" className="command-activity__toggle" aria-expanded={expanded}
        aria-controls={panelId} onClick={() => setExpanded((value) => !value)}>
        <strong>Activity</strong>
        <span className="command-activity__counts">{activeCount} active · {attentionCount} need review</span>
        <span className="command-activity__latest" aria-live="polite">
          {leading ? `${leading.commandLabel} · ${targetCountLabel(leading)} · ${stageLabel(leading)}` : 'No commands recorded'}
        </span>
        <span aria-hidden="true">{expanded ? '−' : '+'}</span>
      </button>
      <div id={panelId} hidden={!expanded}>
        {!monitors.length && <p className="command-activity__empty">No recent commands in this GCS history.</p>}
        {monitors.length > 0 && <ol className="command-activity__list" aria-label="Recent command activity">
          {monitors.map((monitor) => {
            const ids = targetIds(monitor);
            const issues = (monitor.targetIssues || []).slice(0, MAX_TARGET_ISSUES);
            const issueCount = Math.max(issues.length, Number(monitor.targetIssueCount || 0));
            const missionRoute = MISSION_ROUTES[monitor.missionType];
            return <li key={monitor.commandId} className={`command-activity__item command-activity__item--${monitorTone(monitor)}`}>
              <div className="command-activity__row">
                <h3>{monitor.commandLabel}</h3><span>{targetCountLabel(monitor)}</span>
                <strong className="command-activity__stage">{stageLabel(monitor)}</strong>
                {monitor.isTerminal && <button type="button" className="command-activity__action"
                  aria-label={`Dismiss ${monitor.commandLabel}`} onClick={() => dismissCommandMonitor(monitor.commandId)}>Dismiss</button>}
                <Link className="command-activity__action" to={missionRoute || '/'}
                  aria-label={`${missionRoute ? 'Open mission workspace' : 'Open fleet controls'} for ${monitor.commandLabel}`}>
                  {missionRoute ? 'Open mission workspace' : 'Open fleet controls'}
                </Link>
              </div>
              {monitor.errorSummary && <p className="command-activity__reason">{monitor.errorSummary}</p>}
              <details className="command-activity__details">
                <summary>Aircraft & details{issueCount > 0 ? ` · ${issueCount} affected` : ''}</summary>
                <p>Targets: {ids.length ? ids.join(', ') : 'Not reported'}</p>
                <p>Command: <code>{monitor.commandId}</code></p>
                {monitor.progress?.message && <p>{monitor.progress.message}</p>}
                {monitor.lateEvidence?.message && monitor.lateEvidence.message !== monitor.progress?.message
                  && <p>{monitor.lateEvidence.message}</p>}
                {issues.length > 0 && <ul>{issues.map((issue, index) => <li key={`${issue.droneId}-${index}`}>
                  {formatCommandTargetIssue(issue, { includeStage: true })}
                </li>)}</ul>}
                {issueCount > issues.length && <p>{issueCount - issues.length} additional affected aircraft.</p>}
              </details>
            </li>;
          })}
        </ol>}
      </div>
    </section>
  );
}

CommandActivityPanel.propTypes = { className: PropTypes.string };
