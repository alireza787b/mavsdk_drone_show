import { useEffect, useState } from 'react';
import { parseTargetSelection, serializeTargetSelection, uniqueTargetIds } from './targetSelection';

function remember(context, ids) {
  try { sessionStorage.setItem(`mds:swarm-targets:v1:${context}`,
    serializeTargetSelection({ initialized: true, ids })); } catch (_) { /* storage is optional */ }
}

/** One explicit snapshot per chosen formation; never a polling subscription. */
export default function useSwarmCommandScope(context, configuredIds) {
  const [selection, setSelection] = useState({ context: null, ids: [] });
  useEffect(() => {
    if (!context || context === selection.context) return;
    let saved = null;
    try { saved = parseTargetSelection(sessionStorage.getItem(`mds:swarm-targets:v1:${context}`)); } catch (_) { /* storage is optional */ }
    // A malformed or empty saved choice must never silently widen to All.
    const ids = uniqueTargetIds(saved ? saved.ids : configuredIds);
    setSelection({ context, ids });
    remember(context, ids);
  }, [context, configuredIds, selection.context]);
  const initialized = Boolean(context && context === selection.context);
  const ids = initialized ? selection.ids : [];
  return { ids, initialized, missing: ids.filter(id => !configuredIds.includes(id)),
    choose: next => {
      if (!context) return;
      const ids = uniqueTargetIds(next);
      remember(context, ids);
      // Late accepted receipts belong to their original workspace, not a newer one.
      setSelection(previous => previous.context === context ? { context, ids } : previous);
    } };
}
