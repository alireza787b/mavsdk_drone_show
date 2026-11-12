import React, { useMemo, useState } from 'react';
import { OperatorNotice, PageActionBar } from '../ui';
import useLogStream from '../../hooks/useLogStream';
import useLogSessions from '../../features/log-workspace/useLogSessions';
import { historyQuery, matchesLog } from '../../features/log-workspace/logWorkspace';
import { buildComponentCatalog } from '../../utilities/logViewerUtils';
import { LIVE_TIME_WINDOWS } from '../../constants/logConstants';
import LogTable from './LogTable';
import LogExportDialog from './LogExportDialog';

export default function RuntimeLogsWorkspace({ tab, droneId, sourceLabel, context, registry, now }) {
  const [level, setLevel] = useState('WARNING'), [component, setComponent] = useState(''), [search, setSearch] = useState('');
  const [start, setStart] = useState(''), [end, setEnd] = useState(''), [windowValue, setWindowValue] = useState('all');
  const [paused, setPaused] = useState(false), [exportOpen, setExportOpen] = useState(false), [clearEpoch, setClearEpoch] = useState(0);
  const live = tab === 'live';
  let query = {}, queryError = '';
  try { query = historyQuery({ level, component, search, start, end }); } catch (error) { queryError = error.message; }
  const stream = useLogStream({ enabled: live, level, component: component || null, droneId, paused, contextKey: context });
  const history = useLogSessions({ droneId, enabled: !live, query, queryError });
  const duration = LIVE_TIME_WINDOWS.find(item => item.value === windowValue)?.durationMs;
  const anchor = paused ? stream.frozenAt : now;
  const entries = useMemo(() => live ? stream.entries.filter(entry => matchesLog(entry, search) && (!duration || (Number.isFinite(Date.parse(entry.ts)) && Date.parse(entry.ts) >= anchor - duration))) : history.page.lines,
    [live, stream.entries, search, duration, anchor, history.page.lines]);
  const components = buildComponentCatalog(live ? stream.entries : history.page.lines, registry);
  const activeFilters = [component, !live && start, !live && end, live && windowValue !== 'all'].filter(Boolean).length;
  const status = live ? ({ connected: 'Connected', loading: 'Connecting', reconnecting: 'Reconnecting', offline: 'Source unavailable', idle: 'Not connected' }[stream.status] || 'Unknown')
    : history.page.status === 'loading' || history.listBusy ? 'Loading history' : history.page.status === 'error' || history.listError ? 'History unavailable' : 'Recorded session';
  const coverage = live ? stream.coverage : history.page.coverage;
  return <section className="logs-runtime" aria-label={live ? 'Live logs' : 'Recorded sessions'}>
    <div className="logs-toolbar"><span className={`logs-source-state is-${stream.status}`} role="status">{status}{live && paused ? ' · Frozen' : ''}</span>
      <label className="logs-search"><span className="logs-visually-hidden">Search logs</span><input type="search" aria-label="Search logs" placeholder="Search logs" value={search} onChange={event => setSearch(event.target.value)} maxLength={256} /></label>
      <label><span className="logs-visually-hidden">Minimum severity</span><select aria-label="Minimum severity" value={level} onChange={event => setLevel(event.target.value)}>
        <option value="WARNING">Warnings+</option><option value="ERROR">Errors+</option><option value="CRITICAL">Critical</option><option value="INFO">Info+</option><option value="DEBUG">All levels</option></select></label>
      <details className="logs-filter-menu"><summary>Filters{activeFilters ? ` · ${activeFilters}` : ''}</summary><div className="logs-filter-fields">
        <label>Component<select aria-label="Log component" value={component} onChange={event => setComponent(event.target.value)}><option value="">All components</option>{components.map(item => <option key={item.name}>{item.name}</option>)}</select></label>
        {live ? <label>Time window<select aria-label="Live time window" value={windowValue} onChange={event => setWindowValue(event.target.value)}>{LIVE_TIME_WINDOWS.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          : <><label>After (UTC)<input type="text" aria-label="After UTC" placeholder="YYYY-MM-DDTHH:mm:ssZ" value={start} onChange={event => setStart(event.target.value)} /></label><label>Through (UTC)<input type="text" aria-label="Through UTC" placeholder="YYYY-MM-DDTHH:mm:ssZ" value={end} onChange={event => setEnd(event.target.value)} /></label></>}
      </div></details>
      <PageActionBar primary={live ? <button type="button" className="operator-button operator-button--ghost" onClick={() => setPaused(value => !value)}>{paused ? 'Follow latest' : 'Freeze view'}</button> : <button type="button" className="operator-button operator-button--ghost" disabled={history.listBusy} onClick={history.refresh}>Refresh</button>}
        secondary={live ? <button type="button" className="operator-button operator-button--ghost" onClick={() => { stream.clear(); setClearEpoch(value => value + 1); }}>Clear view</button>
          : <button type="button" className="operator-button operator-button--ghost" disabled={!history.sessions.length || Boolean(queryError)} onClick={() => setExportOpen(true)}>Export</button>} />
    </div>
    {!live && <div className="logs-session-strip"><label>Session<select aria-label="Recorded session" value={history.sessionId} onChange={event => history.select(event.target.value)}><option value="">Choose session…</option>
      {history.sessions.map(session => <option key={session.session_id} value={session.session_id}>{session.session_id}</option>)}</select></label><span>{history.pageNumber > 1 ? `Page ${history.pageNumber}` : 'First page'} · up to 500 matching records</span></div>}
    {!!activeFilters && <div className="logs-filter-summary">{component && <span>{component}</span>}{!live && start && <span>After {start} UTC</span>}{!live && end && <span>Through {end} UTC</span>}{live && windowValue !== 'all' && <span>Last {windowValue}</span>}
      <button type="button" className="operator-button operator-button--ghost" onClick={() => { setComponent(''); setStart(''); setEnd(''); setWindowValue('all'); }}>Clear filters</button></div>}
    {queryError && !live && <OperatorNotice tone="warning" title="Invalid UTC range">{queryError}</OperatorNotice>}
    {live && stream.error && <OperatorNotice tone="warning" title="Live source unavailable">{stream.error}</OperatorNotice>}
    {!live && (history.listError || history.page.error) && <OperatorNotice tone="warning" title="Session read unavailable">{history.listError || history.page.error}</OperatorNotice>}
    <LogTable entries={queryError && !live ? [] : entries} loading={!live && history.page.status === 'loading'} autoScroll={live && !paused} sourceLabel={sourceLabel}
      identity={`${context}:${droneId ?? 'gcs'}:${tab}:${history.sessionId}:${clearEpoch}`} emptyStateTitle={live ? stream.connected ? 'No matching events in the retained buffer.' : 'Waiting for the selected log source.' : 'No matching records in this session page.'} />
    <footer className="logs-coverage"><span>{entries.length} shown · {live ? 'bounded live buffer' : `page ${history.pageNumber}`}{live && paused ? ` · ${stream.pending} pending` : ''}</span>
      {(stream.discarded > 0 && live) && <span className="logs-warning">{stream.discarded} browser records discarded</span>}
      {coverage?.gapCount > 0 && live && <span className="logs-warning">Source coverage gaps · {coverage.droppedEvents || 'unknown'} missed</span>}
      {!live && <div className="logs-inline-actions"><button type="button" className="operator-button operator-button--ghost" disabled={history.pageNumber === 1 || history.page.status === 'loading'} onClick={history.previous}>Previous</button><button type="button" className="operator-button operator-button--ghost" disabled={!history.page.has_more || !history.page.next_cursor || history.page.status === 'loading'} onClick={history.next}>Next page</button></div>}
    </footer>
    <details className="logs-details"><summary>Coverage</summary>{live ? <p>Retained live events, not a complete session archive. Freeze view does not pause logging. Source: {coverage?.coverage || 'unknown'}.</p> : <p>Snapshot: {history.page.snapshot_id || 'Unknown'} · {history.page.has_more ? 'More pages available' : history.page.status === 'loaded' ? 'Read boundary reached' : 'Coverage unknown'}</p>}
      {coverage && <pre>{JSON.stringify(coverage, null, 2)}</pre>}</details>
    {exportOpen && <LogExportDialog sessions={history.sessions} selectedSession={history.sessionId} filters={query} droneId={droneId} scopeLabel={sourceLabel} onClose={() => setExportOpen(false)} />}
  </section>;
}
