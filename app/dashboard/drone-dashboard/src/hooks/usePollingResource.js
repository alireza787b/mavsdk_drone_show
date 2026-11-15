import { useEffect, useState } from 'react';

/** Sequential, cancellable refreshes; retain aging evidence across outages. */
export default function usePollingResource(load, intervalMs, contextKey, enabled = true) {
  const [snapshot, setSnapshot] = useState({ response: null, error: null, loading: true, consecutiveFailures: 0 });
  useEffect(() => {
    if (!enabled) return undefined;
    let live = true, timer, controller;
    let inFlight = false;
    setSnapshot({ response: null, error: null, loading: true, consecutiveFailures: 0 });
    const poll = async () => {
      if (!live || inFlight || document.hidden) return;
      inFlight = true;
      controller = new AbortController();
      try {
        const response = await load({ signal: controller.signal, timeout: 10000 });
        if (live) setSnapshot({ response, receivedAtMs: Date.now(), error: null, loading: false, consecutiveFailures: 0 });
      } catch (error) {
        if (live && !controller.signal.aborted) setSnapshot((previous) => ({ ...previous, error, loading: false,
          consecutiveFailures: Math.min((previous.consecutiveFailures || 0) + 1, 1000000) }));
      } finally {
        inFlight = false;
        if (live && !document.hidden && intervalMs !== null) timer = setTimeout(poll, intervalMs);
      }
    };
    const resume = () => { clearTimeout(timer); if (!document.hidden) poll(); };
    poll();
    document.addEventListener('visibilitychange', resume);
    window.addEventListener('focus', resume);
    return () => {
      live = false;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', resume);
      window.removeEventListener('focus', resume);
    };
  }, [load, intervalMs, contextKey, enabled]);
  return snapshot;
}
