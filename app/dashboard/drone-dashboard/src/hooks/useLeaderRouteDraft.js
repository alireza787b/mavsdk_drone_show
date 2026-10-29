import { useCallback, useState } from 'react';

const PREFIX = 'mds.trajectory.draft.v1';

function readDraft(key) {
  if (!key) return [];
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    return Array.isArray(saved) ? saved : [];
  } catch {
    return [];
  }
}

// A setter captures its own leader key. A late terrain response must not write
// into whichever leader happens to be selected when the response arrives.
export default function useLeaderRouteDraft(mode, leaderId) {
  const key = mode && leaderId ? `${PREFIX}.${mode}.${leaderId}` : null;
  const [drafts, setDrafts] = useState({});
  const waypoints = key ? (drafts[key] ?? readDraft(key)) : [];
  const update = useCallback((value) => {
    if (!key) return;
    setDrafts((previous) => {
      const current = previous[key] ?? readDraft(key);
      const next = typeof value === 'function' ? value(current) : value;
      return { ...previous, [key]: next };
    });
  }, [key]);

  // Persist outside state updaters: React may invoke updaters more than once.
  const persist = useCallback(() => {
    Object.entries(drafts).forEach(([draftKey, value]) => {
      try {
        localStorage.setItem(draftKey, JSON.stringify(value));
      } catch {
        // In-memory editing remains available when browser storage is disabled.
      }
    });
  }, [drafts]);
  return { waypoints, update, persist, key };
}
