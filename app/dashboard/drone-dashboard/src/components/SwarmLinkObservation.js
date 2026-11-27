import React from 'react';
import { FaArrowLeft, FaClock, FaQuestionCircle, FaUnlink } from 'react-icons/fa';

const states = {
  fresh: { label: 'Receiving updates', Icon: FaArrowLeft },
  delayed: { label: 'Updates delayed', Icon: FaClock },
  missing: { label: 'Updates missing', Icon: FaUnlink },
  unknown: { label: 'Unknown', Icon: FaQuestionCircle },
};

export function readLeaderLink(member, commandId, nowMs) {
  const observation = member.link_observation;
  if (String(member.follow) === '0') return null;
  if (!observation) return { state: 'unknown' };
  const current = member.available === true
    && String(observation.hw_id) === String(member.hw_id)
    && String(observation.leader_hw_id) === String(member.follow)
    && observation.session_id && (!commandId || observation.session_id === commandId)
    && Number.isFinite(nowMs) && Number.isFinite(observation.valid_until_ms)
    && nowMs < observation.valid_until_ms && Object.prototype.hasOwnProperty.call(states, observation.state);
  return current ? observation : { state: 'unknown' };
}

export function LeaderLinkMark({ id, follow, observation }) {
  const state = observation?.state;
  const { label, Icon } = states[state] || states.fresh;
  const description = `Leader H${follow}${state ? ` · ${label}` : ''}`;
  return <span id={id} className={`swarm-diagram__relationship swarm-diagram__link is-${state || 'idle'}`}
    title={description}>
    <Icon aria-hidden="true" /><span aria-hidden="true">H{follow}</span>
    <span className="swarm-visually-hidden">{description}</span>
  </span>;
}

function milliseconds(value) {
  if (!Number.isFinite(value) || value < 0) return 'Unknown';
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function LeaderLinkDetails({ follow, observation }) {
  if (String(follow) === '0') return null;
  const state = observation?.state || 'unknown';
  const stamp = new Date(observation?.observed_at_ms);
  const sampledAt = state !== 'unknown' && Number.isFinite(observation?.observed_at_ms)
    && Number.isFinite(stamp.getTime()) ? stamp.toISOString() : null;
  const reportedCounters = [
    ['Accepted updates', observation?.accepted], ['Rejected updates', observation?.rejected],
    ['Duplicate updates', observation?.duplicate], ['Fallback attempts', observation?.fallback_attempts],
  ].filter(([, value]) => Number.isFinite(value));
  return <section className="swarm-diagram__link-detail" aria-label="Leader link">
    <h4>Link to H{follow} <small>{states[state].label}</small></h4>
    {sampledAt && <time dateTime={sampledAt} title={sampledAt}>Sampled {sampledAt.slice(11, 19)} UTC</time>}
    {state !== 'unknown' && <dl>
      <dt>Position age</dt><dd>{milliseconds(observation.position_age_ms)}</dd>
      <dt>Heading age</dt><dd>{milliseconds(observation.heading_age_ms)}</dd>
      <dt>Longest update gap</dt><dd>{milliseconds(observation.max_gap_ms)}</dd>
      <dt>Source</dt><dd>{{ ws: 'Live stream', 'http-fallback': 'HTTP fallback' }[observation.transport] || 'Unknown'}</dd>
    </dl>}
    {state !== 'unknown' && reportedCounters.length > 0 && <details>
      <summary>Session counts</summary><dl>{reportedCounters.map(([name, value]) =>
        <React.Fragment key={name}><dt>{name}</dt><dd>{value}</dd></React.Fragment>)}</dl>
    </details>}
  </section>;
}
