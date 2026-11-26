import React from 'react';
import { recordTime } from '../../features/log-workspace/logWorkspace';

const metric = (value, unit = '') => value === null || value === undefined || value === '' || typeof value === 'boolean' || !Number.isFinite(Number(value)) ? 'Unknown' : `${Number(value)}${unit}`;
export default function UlogSummary({ summary, label }) {
  if (!summary) return null;
  const evidence = summary.duration_evidence;
  return <section className="logs-ulog-summary" aria-label="Flight log summary">{label && <h3>{label}</h3>}
    {summary.parsed !== true || summary.parser?.status !== 'ok' ? <p>{summary.parser?.error || 'Derived metrics unavailable.'}</p> : <dl className="logs-facts">
      <dt>Observed duration</dt><dd>{metric(summary.duration_sec, ' s')}{summary.duration_sec != null && (evidence?.lower_bound !== false || evidence?.timestamp_scan_complete !== true) ? ' · partial / lower bound' : ''}</dd>
      <dt>Duration evidence</dt><dd>{evidence?.source?.replace(/_/g, ' ') || 'Unknown'}</dd>
      <dt>Local horizontal range</dt><dd>{metric(summary.local_position?.max_horizontal_distance_from_start_m, ' m')}</dd>
      <dt>Local height range</dt><dd>{metric(summary.local_position?.relative_altitude_range_m?.min, ' m')} – {metric(summary.local_position?.relative_altitude_range_m?.max, ' m')} · relative to the local origin</dd>
      <dt>Battery voltage</dt><dd>{metric(summary.battery?.voltage_v?.min, ' V')} – {metric(summary.battery?.voltage_v?.max, ' V')}</dd>
      <dt>Recording gaps</dt><dd>{metric(summary.dropouts?.count)}{summary.dropouts?.count > 0 ? ` · ${metric(summary.dropouts.total_duration_sec, ' s')} total` : ''}</dd>
      <dt>Command samples</dt><dd>{metric(summary.commands?.vehicle_command?.samples)}</dd><dt>Acknowledgment samples</dt><dd>{metric(summary.commands?.vehicle_command_ack?.samples)}</dd>
      <dt>File metadata time</dt><dd>{recordTime(summary.source?.date_utc)} · not flight-time proof</dd>
    </dl>}
    {!!summary.parser?.observability_warnings?.length && <ul>{summary.parser.observability_warnings.map(note => <li key={note}>{note}</li>)}</ul>}
    <details><summary>Parser, coverage & derived data</summary><pre>{JSON.stringify(summary, null, 2)}</pre></details>
  </section>;
}
