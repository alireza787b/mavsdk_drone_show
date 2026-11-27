import React, { useState } from 'react';
import { FiChevronDown } from 'react-icons/fi';

const pageSize = 8;
const measurements = [
  ['position_age_ms', 'Leader position age', 'ms'],
  ['heading_age_ms', 'Leader heading age', 'ms'],
  ['own_position_age_ms', 'Aircraft position age', 'ms'],
  ['own_heading_age_ms', 'Aircraft heading age', 'ms'],
  ['max_gap_ms', 'Longest update gap', 'ms'],
  ['max_setpoint_send_ms', 'Longest setpoint send', 'ms'],
  ['max_setpoint_gap_ms', 'Longest setpoint gap', 'ms'], ['setpoint_count', 'Setpoints sent'],
  ['hard_stale_ms', 'Update age limit', 'ms'],
  ['accepted', 'Accepted updates'], ['rejected', 'Rejected updates'],
  ['duplicate', 'Duplicate updates'], ['fallback_attempts', 'Fallback attempts'],
  ['transport', 'Source'], ['last_rejection', 'Last rejection'],
  ['rx_bytes_per_s', 'Received', 'B/s'], ['tx_bytes_per_s', 'Sent', 'B/s'],
  ['rx_message_count_delta', 'Received messages'], ['rx_message_lost_count_delta', 'Missing messages'],
  ['rx_parse_errors_delta', 'Parse errors'], ['rx_buffer_overruns_delta', 'Receive overruns'],
  ['rx_packet_drop_count_delta', 'Dropped packets'], ['tx_buffer_overruns_delta', 'Transmit overruns'],
  ['interval_ms', 'Sample interval', 'ms'], ['counter_reset', 'Counter reset'],
  ['trigger_age_ms', 'Observed age', 'ms'], ['threshold_ms', 'Configured limit', 'ms'],
  ['dropped_before', 'Omitted records'], ['validation', 'Validation'],
  ['wifi_signal_percent', 'Aircraft Wi-Fi signal', '%'], ['wifi_interface', 'Aircraft interface'],
  ['wifi_status', 'Wi-Fi observation'], ['last_transport_error', 'Last transport error'],
  ['mode_age_ms', 'Mode age', 'ms'], ['armed', 'Armed'], ['mode', 'Observed mode'],
  ['source_system', 'Source system'], ['source_component', 'Source component'],
  ['target_system', 'Target system'], ['target_component', 'Target component'],
  ['from_external', 'External request'], ['leader_hw_id', 'Leader ID'],
  ['reason', 'Reason'], ['outcome', 'Outcome'], ['error', 'Error'],
];

function clockTime(ms) {
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const date = new Date(ms);
  return Number.isFinite(date.getTime()) ? date.toISOString() : null;
}

function EventList({ events, elapsed = false }) {
  const [visible, setVisible] = useState(pageSize);
  if (!events.length) return null;
  let lastDay;
  return <>
    <ol className="ulog-timeline__events" aria-label={elapsed ? 'Elapsed events' : 'UTC events'}>
      {events.slice(0, visible).map(({ event, utc }, index) => {
        const day = utc?.slice(0, 10);
        const newDay = day && day !== lastDay;
        lastDay = day;
        const metrics = event.metrics || {};
        const fields = measurements.filter(([key]) => ['string', 'boolean'].includes(typeof metrics[key]) || Number.isFinite(metrics[key]));
        const title = <span className="ulog-timeline__title"><strong>{event.label}</strong>
          <small>{event.source}{event.instance != null && ' · #' + event.instance}</small></span>;
        return <li key={index}>{newDay && <div className="ulog-timeline__date">{day} UTC</div>}
          <div className="ulog-timeline__row">
            {utc ? <time dateTime={utc} title={utc}>{utc.slice(11, 23)}</time> : <span className="ulog-timeline__time">
              {Number.isFinite(event.elapsed_ms) ? '+' + (event.elapsed_ms / 1000).toFixed(3) + ' s' : 'Unknown'}
            </span>}
            {fields.length ? <details><summary>{title}<FiChevronDown aria-hidden="true" /></summary>
              <dl>{fields.map(([key, name, unit]) => <React.Fragment key={key}><dt>{name}</dt>
                <dd>{typeof metrics[key] === 'boolean' ? (metrics[key] ? 'Yes' : 'No') : metrics[key]}{unit && ' ' + unit}</dd></React.Fragment>)}</dl>
            </details> : <div>{title}</div>}
          </div>
        </li>;
      })}
    </ol>
    {visible < events.length && <button type="button" className="ulog-timeline__more"
      onClick={() => setVisible(count => count + pageSize)}>Show more events ({events.length - visible})</button>}
  </>;
}

export default function UlogTimeline({ timeline, companion }) {
  const [showSamples, setShowSamples] = useState(false);
  if (!timeline && !companion) return null;
  const px4 = Array.isArray(timeline?.events) ? timeline.events : [];
  const swarm = Array.isArray(companion?.events) ? companion.events : [];
  const aligned = [];
  const elapsed = [];
  const events = [...px4, ...swarm].filter(event => event?.label);
  const sampleCount = events.filter(event => event.kind === 'sample').length;
  const mixed = sampleCount > 0 && sampleCount < events.length;
  for (const event of events) {
    if (mixed && !showSamples && event.kind === 'sample') continue;
    const utc = clockTime(event.utc_ms);
    (utc ? aligned : elapsed).push({ event, utc });
  }
  aligned.sort((a, b) => a.event.utc_ms - b.event.utc_ms);
  elapsed.sort((a, b) => (a.event.elapsed_ms ?? Infinity) - (b.event.elapsed_ms ?? Infinity));
  const coverage = !companion ? 'PX4 recording only' : companion.status === 'unavailable' ? 'Link record unavailable'
    : companion?.status === 'partial' ? 'Partial link record' : null;
  return <section className="ulog-timeline" aria-label="Flight timeline">
    <header><h4>Flight timeline</h4>
      {mixed && <label><input type="checkbox" checked={showSamples}
        onChange={e => setShowSamples(e.target.checked)} /> Link samples ({sampleCount})</label>}</header>
    {coverage && (companion?.reason ? <details className="ulog-timeline__coverage">
      <summary>{coverage}<FiChevronDown aria-hidden="true" /></summary><p>{companion.reason}</p>
    </details> : <p className="ulog-timeline__coverage">{coverage}</p>)}
    {!aligned.length && !elapsed.length && <p>No recorded events.</p>}
    <EventList events={aligned} />
    {!!elapsed.length && <><p className="ulog-timeline__date">Elapsed time · UTC unavailable</p>
      <EventList events={elapsed} elapsed /></>}
    {timeline?.truncated && <p className="ulog-timeline__coverage">Partial event list</p>}
  </section>;
}
