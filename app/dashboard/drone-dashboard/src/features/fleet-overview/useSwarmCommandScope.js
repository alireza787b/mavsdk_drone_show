import { useEffect, useState } from 'react';
import { uniqueTargetIds } from './targetSelection';

/** One explicit snapshot per chosen formation; never a polling subscription. */
export default function useSwarmCommandScope(context, configuredIds) {
  const [selection, setSelection] = useState({ context: null, ids: [] });
  useEffect(() => {
    if (context && context !== selection.context) setSelection({ context, ids: uniqueTargetIds(configuredIds) });
  }, [context, configuredIds, selection.context]);
  const initialized = Boolean(context && context === selection.context);
  const ids = initialized ? selection.ids : [];
  return { ids, initialized, missing: ids.filter(id => !configuredIds.includes(id)),
    choose: next => setSelection({ context, ids: uniqueTargetIds(next) }) };
}
