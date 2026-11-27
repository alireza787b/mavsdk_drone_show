import React, { useState } from 'react';
import { FaCheckCircle, FaChevronDown, FaExclamationTriangle, FaInfoCircle, FaRulerVertical, FaSearch } from 'react-icons/fa';
import useObservationClock from '../hooks/useObservationClock';

// These are display observations, never command admission or proof of clearance.
export function summarizeHeightReadings(warning, ids, nowMs = Date.now(), receivedAtMs = null) {
  if (!warning || !Array.isArray(warning.samples)) return null;
  const scopedIds = [...new Set(ids.map(String))];
  const maxAge = Number(warning.max_age_ms);
  const sourceNow = Number.isFinite(receivedAtMs) && Number.isFinite(Number(warning.observed_at_ms)) && warning.observed_at_ms != null
    ? Number(warning.observed_at_ms) + Math.max(0, nowMs - receivedAtMs) : nowMs;
  const fresh = timestamp => Number.isFinite(maxAge) && maxAge > 0 && Number.isFinite(Number(timestamp))
    && timestamp != null && sourceNow - Number(timestamp) >= 0 && sourceNow - Number(timestamp) <= maxAge;
  const byId = new Map(warning.samples.map(row => [String(row.hw_id), row]));
  const samples = scopedIds.map(id => byId.get(id) || { hw_id: id });
  const valid = samples.filter(row => row.altitude_m != null && Number.isFinite(Number(row.altitude_m)) && fresh(row.altitude_timestamp_ms));
  const planned = valid.length === samples.length && valid.every(row => fresh(row.landed_timestamp_ms)
    && (row.landed_state === 2 || row.landed_state === 'IN_AIR') && row.planned_height_m != null && Number.isFinite(Number(row.planned_height_m)));
  const spreadOf = values => values.length >= 2 ? Math.max(...values) - Math.min(...values) : null;
  const spread = spreadOf(valid.map(row => Number(row.altitude_m)));
  const comparisonSpread = spreadOf(valid.map(row => Number(row.altitude_m) - (planned ? Number(row.planned_height_m) : 0)));
  const active = comparisonSpread != null && warning.threshold_m != null && Number.isFinite(Number(warning.threshold_m)) && comparisonSpread > Number(warning.threshold_m);
  return { active, spread_m: spread, comparison_spread_m: comparisonSpread, comparison: planned ? 'planned' : 'readings',
    valid_count: valid.length, expected_count: samples.length, samples, valid, fresh, sourceNow };
}

export function heightStatusById(summary) {
  if (!summary) return {};
  const valid = new Set(summary.valid);
  return Object.fromEntries(summary.samples.map(row => {
    const id = String(row.hw_id);
    if (!valid.has(row)) return [id, { tone: 'warning', symbol: '?', ariaLabel: `Height for H${id} unavailable or stale` }];
    const value = `${Number(row.altitude_m).toFixed(1)} m MSL`;
    return [id, {
      tone: summary.active ? 'warning' : 'success',
      symbol: summary.active ? '!' : '✓',
      ariaLabel: `Height for H${id}: ${value}${summary.active ? ', review difference' : ''}`,
    }];
  }));
}

function HeightIcon({ incomplete, high }) {
  if (high) return <FaExclamationTriangle aria-hidden="true" />;
  if (incomplete) return <FaInfoCircle aria-hidden="true" />;
  return <FaCheckCircle aria-hidden="true" />;
}

export default function SwarmHeightAdvisory({ warning, targetIds, referenceIds = [], aircraft = [], receivedAtMs = null, announce = true }) {
  const [filter, setFilter] = useState('');
  const [limit, setLimit] = useState(30);
  const [expanded, setExpanded] = useState(false);
  const now = useObservationClock();
  const ids = [...new Set([...targetIds, ...referenceIds].map(String))];
  const summary = summarizeHeightReadings(warning, ids, now, receivedAtMs);
  if (!summary || ids.length < 2) return null;
  const { samples, valid, fresh, active: high, comparison_spread_m: spread, sourceNow } = summary;
  const planned = summary.comparison === 'planned';
  const incomplete = valid.length !== samples.length || spread == null;
  const state = high ? 'CHECK' : incomplete ? 'UNKNOWN' : 'OK';
  const fullState = high ? 'Height difference needs review' : incomplete ? 'Height observations incomplete' : 'Height observations available';
  const names = new Map(aircraft.map(row => [String(row.hw_id ?? row.hw_ID), row.callsign || row.name || `H${row.hw_id ?? row.hw_ID}`]));
  const filtered = samples.filter(row => `${names.get(String(row.hw_id)) || ''} H${row.hw_id}`.toLowerCase().includes(filter.trim().toLowerCase()));
  const referenceSet = new Set(referenceIds.map(String));
  const targetSet = new Set(targetIds.map(String));
  const fixLabels = ['No GPS', 'No fix', '2D fix', '3D fix', 'DGPS', 'RTK float', 'RTK fixed'];
  const age = timestamp => `${Math.max(0, Math.floor((sourceNow - Number(timestamp)) / 1000))} s`;
  const gpsKnown = samples.filter(row => row.gps_fix_type != null && fresh(row.gps_timestamp_ms)).length;
  return <div className={`swarm-height-advisory${high ? ' swarm-height-advisory--warning' : ''}${incomplete ? ' swarm-height-advisory--unknown' : ''}`}>
    {announce && <span className="swarm-height-advisory__announcement" role="status">{fullState}</span>}
    <details open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary aria-label={`${fullState}. ${spread == null ? 'Height difference unknown' : `${spread.toFixed(1)} metres`}. ${valid.length} of ${samples.length} reports current`}>
        <span className="swarm-height-advisory__icon"><HeightIcon incomplete={incomplete} high={high} /></span>
        <strong>HEIGHT</strong>
        <span className="swarm-height-advisory__state">{state}</span>
        <span className="swarm-height-advisory__value">{spread == null ? '—' : `${spread.toFixed(1)} m`}</span>
        <span className="swarm-height-advisory__count">{valid.length}/{samples.length}</span>
        <FaChevronDown className="swarm-height-advisory__chevron" aria-hidden="true" />
      </summary>
      <div className="swarm-height-advisory__details">
        <div className="swarm-height-advisory__facts" aria-label="Height review facts">
          <span><FaRulerVertical aria-hidden="true" /> {planned ? 'PLAN' : 'READINGS'}</span>
          <span>{valid.length}/{samples.length} current</span>
          <span>{gpsKnown}/{samples.length} GPS</span>
        </div>
        <p className="swarm-height-advisory__note">MSL estimate · {planned ? 'planned spacing applied' : 'spacing not applied'} · advisory only</p>
        {samples.length > 30 && <label className="swarm-height-advisory__search"><FaSearch aria-hidden="true" /><span className="swarm-visually-hidden">Find aircraft</span><input aria-label="Find aircraft" value={filter} placeholder="Find" onChange={event => { setFilter(event.target.value); setLimit(30); }} /></label>}
        <ul aria-label="Height and GPS observations">{filtered.slice(0, limit).map(row => <li key={row.hw_id}>
          <strong>{names.get(String(row.hw_id)) || `H${row.hw_id}`}</strong>
          {referenceSet.has(String(row.hw_id)) && !targetSet.has(String(row.hw_id)) && <span className="swarm-height-advisory__reference">REF</span>}
          <span className="swarm-height-advisory__reading">{valid.includes(row) ? `${Number(row.altitude_m).toFixed(1)} m` : '—'}</span>
          <span className="swarm-height-advisory__age">{valid.includes(row) ? `${age(row.altitude_timestamp_ms)}` : row.altitude_timestamp_ms != null && sourceNow >= Number(row.altitude_timestamp_ms) ? `stale ${age(row.altitude_timestamp_ms)}` : 'unknown'}</span>
          <span className="swarm-height-advisory__fix">{row.gps_fix_type != null && fresh(row.gps_timestamp_ms) ? (fixLabels[Number(row.gps_fix_type)] || 'GPS') : 'GPS —'}</span>
          {Number(row.gps_fix_type) === 6 && fresh(row.gps_timestamp_ms) && Number.isFinite(Number(row.rtk_fixed_observed_since_ms)) && row.rtk_fixed_observed_since_ms != null && Number(row.gps_timestamp_ms) >= Number(row.rtk_fixed_observed_since_ms) && <span className="swarm-visually-hidden">RTK fixed for {Math.floor((Number(row.gps_timestamp_ms) - Number(row.rtk_fixed_observed_since_ms)) / 1000)} seconds</span>}
        </li>)}</ul>
        {filtered.length > limit && <button type="button" className="swarm-height-advisory__more" onClick={() => setLimit(limit + 30)}>More aircraft · {filtered.length - limit}</button>}
      </div>
    </details>
  </div>;
}
