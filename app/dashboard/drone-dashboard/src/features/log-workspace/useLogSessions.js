import { useCallback, useEffect, useRef, useState } from 'react';
import { getDroneSessionContent, getDroneSessions, getSessionContent, getSessions } from '../../services/logService';
import { logError } from './logWorkspace';

/** One source/session/query owner. Pagination never appends an unbounded archive. */
export default function useLogSessions({ droneId, enabled, query, queryError }) {
  const [sessions, setSessions] = useState([]), [sessionId, setSessionId] = useState('');
  const [listBusy, setListBusy] = useState(false), [listError, setListError] = useState('');
  const [page, setPage] = useState({ lines: [], status: 'idle' }), [cursors, setCursors] = useState([null]);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0), selected = useRef(sessionId);
  selected.current = sessionId;
  const source = droneId == null ? 'gcs' : `H${droneId}`;
  const queryKey = JSON.stringify(query);
  const refresh = useCallback(() => setRevision(value => value + 1), []);
  useEffect(() => { selected.current = ''; setSessionId(''); setSessions([]); setCursors([null]); }, [source]);
  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    const controller = new AbortController();
    setListBusy(true); setListError('');
    (droneId == null ? getSessions({ signal: controller.signal, timeout: 15000 }) : getDroneSessions(droneId, { signal: controller.signal, timeout: 15000 }))
      .then(data => {
        if (!active) return;
        setSessions(data.sessions || []);
        if (!selected.current && data.sessions?.length) setSessionId(data.sessions[0].session_id);
      }).catch(error => { if (active) { setSessions([]); setListError(logError(error)); } })
      .finally(() => { if (active) setListBusy(false); });
    return () => { active = false; controller.abort(); };
  }, [droneId, enabled, revision]);
  useEffect(() => { setCursors([null]); }, [source, sessionId, queryKey]);
  const cursor = cursors[cursors.length - 1];
  useEffect(() => {
    const token = ++generation.current;
    const controller = new AbortController();
    setPage({ lines: [], status: enabled && sessionId && !queryError ? 'loading' : 'idle' });
    if (!enabled || !sessionId || queryError) return () => controller.abort();
    const args = { ...JSON.parse(queryKey), limit: 500, ...(cursor ? { cursor } : {}) };
    const request = droneId == null ? getSessionContent(sessionId, args, { signal: controller.signal }) : getDroneSessionContent(droneId, sessionId, args, { signal: controller.signal });
    request.then(data => {
      if (token !== generation.current || controller.signal.aborted) return;
      const lines = (data.lines || []).map((entry, index) => ({ ...entry, _raw: entry,
        _id: JSON.stringify([source, sessionId, data.snapshot_id || revision, data.entry_offsets?.[index] ?? `${cursors.length}:${index}`]) }));
      setPage({ ...data, lines, status: 'loaded' });
    }).catch(error => { if (token === generation.current && !controller.signal.aborted) setPage({ lines: [], status: 'error', error: logError(error) }); });
    return () => { generation.current += 1; controller.abort(); };
  }, [source, droneId, enabled, sessionId, queryKey, queryError, cursor, cursors.length, revision]);
  return { sessions, sessionId, select: id => { setPage({ lines: [], status: 'loading' }); setSessionId(id); },
    listBusy, listError, refresh, page, pageNumber: cursors.length,
    next: () => { if (page.has_more && page.next_cursor) setCursors(previous => [...previous, page.next_cursor]); },
    previous: () => setCursors(previous => previous.length > 1 ? previous.slice(0, -1) : previous),
    restart: () => { setCursors([null]); refresh(); } };
}
