import React from 'react';
import { memberLabel } from '../utilities/swarmOperationModel';
import { swarmDiagramRows } from '../utilities/swarmDiagramModel';
import '../styles/SwarmClusterDiagram.css';

export default function SwarmClusterDiagram({ members, selectedId, onSelect, statuses = {}, dirtyIds = [], label = 'Cluster aircraft' }) {
  return <ul className="swarm-diagram" aria-label={label}>
    {swarmDiagramRows(members).map(({ member, depth }) => {
      const id = String(member.hw_id);
      const leader = String(member.follow) === '0';
      const relay = members.some((other) => String(other.follow) === id);
      const status = statuses[id];
      const dirty = dirtyIds.includes(id);
      return <li key={id} className={depth ? 'swarm-diagram__branch' : 'swarm-diagram__root'}
        style={{ '--swarm-depth': Math.min(depth, 5) }}>
        <button type="button" className={`swarm-diagram__node ${selectedId === id ? 'is-selected' : ''}`}
          aria-pressed={selectedId === id} aria-label={`${memberLabel(member)}${dirty ? ', unsaved changes' : ''}`}
          onClick={() => onSelect(id)}>
          <span className="swarm-diagram__identity"><strong>{memberLabel(member)}</strong>
            <span>{leader ? 'Leader' : relay ? 'Follower · relay' : 'Follower'}{dirty && <span aria-label="Unsaved changes"> *</span>}</span>
          </span>
          {!leader && <span className="swarm-diagram__relationship">← Drone {member.follow}</span>}
          {status && <span className={`swarm-diagram__state is-${status.tone}`}><span aria-hidden="true">{status.symbol}</span> {status.label}</span>}
        </button>
      </li>;
    })}
  </ul>;
}
