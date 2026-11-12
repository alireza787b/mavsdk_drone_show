import { useState, useEffect, useRef, useCallback } from 'react';
import { MAX_LOG_LINES, SSE_BATCH_INTERVAL_MS } from '../constants/logConstants';
import { buildStreamURL } from '../services/logService';

export default function useLogStream({ level = null, component = null, source = null, droneId = null, enabled = true, paused = false, contextKey = '' } = {}) {
  const [entries, setEntries] = useState([]), [status, setStatus] = useState('loading'), [error, setError] = useState(null);
  const [pending, setPending] = useState(0), [discarded, setDiscarded] = useState(0), [coverage, setCoverage] = useState(null);
  const [frozenAt, setFrozenAt] = useState(null);
  const batch = useRef([]), visible = useRef([]), pausedRef = useRef(paused), counter = useRef(0);
  pausedRef.current = paused;
  const flush = useCallback(() => {
    if (pausedRef.current || !batch.current.length) return;
    const next = batch.current; batch.current = []; setPending(0);
    const combined = [...visible.current, ...next];
    if (combined.length > MAX_LOG_LINES) setDiscarded(value => value + combined.length - MAX_LOG_LINES);
    visible.current = combined.slice(-MAX_LOG_LINES); setEntries(visible.current);
  }, []);
  useEffect(() => { setFrozenAt(paused ? Date.now() : null); if (!paused) flush(); }, [paused, flush]);
  const clear = useCallback(() => { batch.current = []; visible.current = []; setEntries([]); setPending(0); setDiscarded(0); }, []);
  useEffect(() => {
    let active = true;
    batch.current = []; visible.current = []; setEntries([]); setPending(0); setDiscarded(0); setCoverage(null); setError(null);
    if (!enabled) { setStatus('idle'); return undefined; }
    setStatus('loading');
    const epoch = `${contextKey}:${droneId ?? 'gcs'}:${Date.now()}:${counter.current++}`;
    const seen = new Set();
    const es = new EventSource(buildStreamURL({ level, component, source }, droneId), { withCredentials: true });
    es.onopen = () => { if (active) { setStatus('connected'); setError(null); } };
    es.onmessage = event => {
      if (!active) return;
      try {
        const raw = JSON.parse(event.data);
        if (!raw || typeof raw !== 'object' || Array.isArray(raw) || typeof raw.msg !== 'string') throw new Error('Invalid log record');
        const id = event.lastEventId ? `${contextKey}:${droneId ?? 'gcs'}:${event.lastEventId}` : `${epoch}:${counter.current++}`;
        if (event.lastEventId && seen.has(id)) return;
        seen.add(id); if (seen.size > MAX_LOG_LINES * 2) seen.delete(seen.values().next().value);
        batch.current.push({ ...raw, _raw: raw, _id: id });
        if (batch.current.length > MAX_LOG_LINES) { batch.current.shift(); setDiscarded(value => value + 1); }
        if (pausedRef.current) setPending(batch.current.length);
      } catch (_) { setCoverage(previous => ({ ...previous, malformed_records: (previous?.malformed_records || 0) + 1 })); }
    };
    const metadata = event => {
      if (!active) return;
      try {
        const value = JSON.parse(event.data);
        setCoverage(previous => ({ ...previous, ...value,
          gapCount: (previous?.gapCount || 0) + (event.type === 'gap' ? 1 : 0),
          droppedEvents: (previous?.droppedEvents || 0) + (event.type === 'gap' && Number.isFinite(value.lost_count) ? value.lost_count : 0) }));
        if (value.state === 'unavailable') { setStatus('offline'); setError(value.message || 'Selected log source is unavailable.'); }
        else if (value.state === 'connected') { setStatus('connected'); setError(null); }
      } catch (_) { /* Ignore malformed status, never fabricate a log row. */ }
    };
    es.addEventListener?.('status', metadata); es.addEventListener?.('gap', metadata);
    es.onerror = () => { if (active) { setStatus(es.readyState === 2 ? 'offline' : 'reconnecting'); setError('Log stream unavailable. Retained rows are last observed.'); } };
    const timer = setInterval(flush, SSE_BATCH_INTERVAL_MS);
    return () => { active = false; es.close(); clearInterval(timer); batch.current = []; };
  }, [level, component, source, droneId, enabled, contextKey, flush]);
  return { entries, connected: status === 'connected', status, error, clear, pending, discarded, coverage, frozenAt };
}
