import React, { useState } from 'react';

const PAGE_SIZE = 30;

// Keep all aircraft searchable while bounding the initial DOM for a fleet-wide condition.
export default function AircraftConditionList({ entries, renderEntry, className, label }) {
  const [query, setQuery] = useState('');
  const [limit, setLimit] = useState(PAGE_SIZE);
  const term = query.trim().toLowerCase();
  const matches = term ? entries.filter(item =>
    `${item.aircraftLabel} H${item.aircraftId} ${item.reason}`.toLowerCase().includes(term)) : entries;
  return <>
    {entries.length > PAGE_SIZE && <label>Find aircraft <input type="search" value={query}
      onChange={event => { setQuery(event.target.value); setLimit(PAGE_SIZE); }} /></label>}
    <ul className={className} aria-label={label}>{matches.slice(0, limit).map(renderEntry)}</ul>
    {!matches.length && <p>No matching aircraft</p>}
    {matches.length > limit && <button type="button" onClick={() => setLimit(limit + PAGE_SIZE)}>Show more aircraft</button>}
  </>;
}
