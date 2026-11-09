import { useRef } from 'react';
import useGcsResourcePolling from './useGcsResourcePolling';
import { GCS_ROUTE_KEYS } from '../services/gcsApiService';

// Retain the recorded operation cohort through failed polls. A disconnected
// projection must never replace mission recovery targets with today's selection.
export default function useShowOperation(missionType, runtimeMode) {
  const snapshot = useGcsResourcePolling(`${GCS_ROUTE_KEYS.showOperationStatus}?mission_type=${missionType}`, 2000, runtimeMode);
  const retained = useRef({ mode: runtimeMode, snapshot: null, previous: null });
  if (retained.current.mode !== runtimeMode) {
    retained.current = { mode: runtimeMode, snapshot: null, previous: snapshot };
  }
  if (snapshot.data && snapshot !== retained.current.previous) retained.current.snapshot = snapshot;
  return snapshot.data && snapshot !== retained.current.previous
    ? snapshot : { ...snapshot, data: retained.current.snapshot?.data || null,
      receivedAt: retained.current.snapshot?.receivedAt };
}
