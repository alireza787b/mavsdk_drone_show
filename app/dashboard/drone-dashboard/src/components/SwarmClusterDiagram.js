import React from 'react';
import { FaRulerVertical } from 'react-icons/fa';
import { memberLabel } from '../utilities/swarmOperationModel';
import { swarmDiagramRows } from '../utilities/swarmDiagramModel';
import { heightStatusById, summarizeHeightReadings } from './SwarmHeightAdvisory';
import '../styles/SwarmClusterDiagram.css';

export default function SwarmClusterDiagram({ members, selectedId, onSelect, statuses = {}, dirtyIds = [], label = 'Cluster aircraft', heightWarning = null, heightIds = [], heightReceivedAtMs = null }) {
  const heightSummary = summarizeHeightReadings(heightWarning, heightIds.length ? heightIds : members.map(member => member.hw_id), Date.now(), heightReceivedAtMs);
  const heightStatuses = heightStatusById(heightSummary);
  return <ul className="swarm-diagram" aria-label={label}>
    {swarmDiagramRows(members).map(({ member, depth }) => {
      const id = String(member.hw_id);
      const leader = String(member.follow) === '0';
      const relay = members.some((other) => String(other.follow) === id);
      const status = statuses[id];
      const height = heightStatuses[id];
      const dirty = dirtyIds.includes(id);
      const heightDescriptionId = height ? `swarm-height-${id}` : undefined;
      return <li key={id} className={depth ? 'swarm-diagram__branch' : 'swarm-diagram__root'}
        style={{ '--swarm-depth': Math.min(depth, 5) }}>
        <button type="button" className={`swarm-diagram__node ${selectedId === id ? 'is-selected' : ''}`}
          aria-pressed={selectedId === id} aria-describedby={heightDescriptionId} aria-label={`${memberLabel(member)}${dirty ? ', unsaved changes' : ''}`}
          onClick={() => onSelect(id)}>
          <span className="swarm-diagram__identity"><strong>{memberLabel(member)}</strong>
            <span>{leader ? 'Leader' : relay ? 'Follower · relay' : 'Follower'}{dirty && <span aria-label="Unsaved changes"> *</span>}</span>
          </span>
          {!leader && <span className="swarm-diagram__relationship">← H{member.follow}</span>}
          {height && <><span className={`swarm-diagram__height is-${height.tone}`} title={height.ariaLabel} aria-hidden="true"><FaRulerVertical /> <b>{height.symbol}</b></span>
            <span id={heightDescriptionId} className="swarm-visually-hidden">{height.ariaLabel}</span></>}
          {status && <span className={`swarm-diagram__state is-${status.tone}`}><span aria-hidden="true">{status.symbol}</span> {status.label}</span>}
        </button>
      </li>;
    })}
  </ul>;
}
