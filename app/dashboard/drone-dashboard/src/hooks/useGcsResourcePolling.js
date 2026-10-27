import { useEffect, useState } from 'react';
import { fetchGcsResource } from '../services/gcsApiService';

// Sequential, cancellable polling: no overlap, no hidden-tab traffic, no stale
// request may overwrite a refreshed package or resurrect an unmounted page.
export default function useGcsResourcePolling(route, intervalMs, revision = 0) {
  const [snapshot, setSnapshot] = useState({ data: null, loading: true, error: null });
  useEffect(() => {
    let stopped = false;
    let timer;
    let controller;
    let inFlight = false;
    const poll = async () => {
      if (stopped || document.hidden || inFlight || !route) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const response = await fetchGcsResource(route, { signal: controller.signal });
        if (!stopped) setSnapshot({ data: response.data, loading: false, error: null, receivedAt: performance.now() });
      } catch (error) {
        if (!stopped && !controller.signal.aborted) setSnapshot({ data: null, loading: false, error });
      } finally {
        inFlight = false;
        if (!stopped && intervalMs && !document.hidden) timer = setTimeout(poll, intervalMs);
      }
    };
    const onVisibility = () => {
      clearTimeout(timer);
      if (!document.hidden) poll();
    };
    if (!route) setSnapshot({ data: null, loading: false, error: null });
    else poll();
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, [route, intervalMs, revision]);
  return snapshot;
}
