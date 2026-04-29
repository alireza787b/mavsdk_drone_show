// src/hooks/useLogStream.js
// SSE hook for real-time log streaming with batching and ring buffer

import { useState, useEffect, useRef, useCallback } from 'react';
import { MAX_LOG_LINES, SSE_BATCH_INTERVAL_MS } from '../constants/logConstants';
import { buildStreamURL } from '../services/logService';

/**
 * useLogStream — connects to SSE log endpoint, batches incoming entries,
 * maintains a capped ring buffer.
 *
 * @param {object} options
 * @param {string|null} options.level - Minimum log level filter
 * @param {string|null} options.component - Component name filter
 * @param {string|null} options.source - Source filter (drone/gcs/frontend)
 * @param {number|null} options.droneId - Drone ID for proxy stream (null = GCS)
 * @param {boolean} options.enabled - Whether streaming is active (false = disconnected)
 * @returns {{ entries: Array, connected: boolean, error: string|null, clear: Function }}
 */
const useLogStream = ({ level = null, component = null, source = null, droneId = null, enabled = true, paused = false } = {}) => {
  const [entries, setEntries] = useState([]);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState(null);
  const batchRef = useRef([]);
  const esRef = useRef(null);
  const timerRef = useRef(null);
  const idCounterRef = useRef(0);
  const pausedRef = useRef(paused);
  pausedRef.current = paused;

  // Flush batched entries into state (ring buffer)
  // When paused, entries accumulate in batchRef but are not flushed to state
  // (SSE stays connected — no data loss per §12.8)
  const flush = useCallback(() => {
    if (batchRef.current.length === 0) return;
    if (pausedRef.current) return; // Keep buffering, don't update display
    const batch = batchRef.current;
    batchRef.current = [];
    setEntries(prev => {
      const merged = [...prev, ...batch];
      return merged.length > MAX_LOG_LINES
        ? merged.slice(merged.length - MAX_LOG_LINES)
        : merged;
    });
  }, []);

  const clear = useCallback(() => {
    batchRef.current = [];
    setEntries([]);
  }, []);

  useEffect(() => {
    if (!enabled) {
      // Disconnect
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      batchRef.current = [];
      idCounterRef.current = 0;
      setEntries([]);
      setConnected(false);
      return;
    }

    batchRef.current = [];
    idCounterRef.current = 0;
    setEntries([]);
    const url = buildStreamURL({ level, component, source }, droneId);
    const es = new EventSource(url, { withCredentials: true });
    esRef.current = es;

    es.onopen = () => {
      setConnected(true);
      setError(null);
    };

    es.onmessage = (event) => {
      try {
        const entry = JSON.parse(event.data);
        entry._id = idCounterRef.current++;  // Stable monotonic ID for DataGrid row key
        batchRef.current.push(entry);
        // Cap batch size to prevent unbounded growth when paused
        if (batchRef.current.length > MAX_LOG_LINES) {
          batchRef.current = batchRef.current.slice(-MAX_LOG_LINES);
        }
      } catch {
        // Skip malformed SSE data
      }
    };

    es.onerror = () => {
      setConnected(false);
      setError('SSE connection lost — reconnecting...');
      // EventSource auto-reconnects
    };

    // Start batch flush timer
    timerRef.current = setInterval(flush, SSE_BATCH_INTERVAL_MS);

    return () => {
      es.close();
      esRef.current = null;
      batchRef.current = []; // Clear pending batch to prevent stale entries leaking
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setEntries([]);
      setConnected(false);
    };
  }, [level, component, source, droneId, enabled, flush]);

  return { entries, connected, error, clear };
};

export default useLogStream;
