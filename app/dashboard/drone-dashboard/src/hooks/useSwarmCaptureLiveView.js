import { useEffect, useRef, useState } from 'react';
import useGcsResourcePolling from './useGcsResourcePolling';
import { captureLivePositions, captureViewReference } from '../utilities/swarmCaptureLiveView';

/** One modal-only cached fleet read, not a second set of aircraft RPC pollers. */
export default function useSwarmCaptureLiveView(hwIds, reference, rootId) {
  const response = useGcsResourcePolling('/api/v1/fleet/telemetry', 1000);
  const cached = useRef(null);
  const observed = useRef({});
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    const timer = setInterval(() => { if (!document.hidden) setNow(performance.now()); }, 1000);
    return () => clearInterval(timer);
  }, []);
  if (response.data) cached.current = response.data;
  const rows = cached.current?.telemetry || {};
  const ages = {};
  hwIds.forEach(id => {
    const timestamp = rows[id]?.global_position_timestamp_ms;
    const previous = observed.current[id];
    if (!previous || (Number.isFinite(timestamp) && (!Number.isFinite(previous.timestamp) || timestamp > previous.timestamp))) {
      observed.current[id] = { timestamp, at: response.requestedAt ?? now };
    }
    ages[id] = Math.max(0, now - observed.current[id].at, performance.now() - observed.current[id].at);
  });
  // Retain the last positions during a failed fetch, but never label them Live.
  // Frozen GCS samples expire even when HTTP itself keeps answering successfully.
  const origin = reference || captureViewReference(rows[rootId], rootId);
  const positions = captureLivePositions(rows, hwIds, origin, ages, Boolean(response.error));
  const freshCount = positions.filter(point => !point.stale).length;
  return { positions, freshCount, loading: response.loading };
}
