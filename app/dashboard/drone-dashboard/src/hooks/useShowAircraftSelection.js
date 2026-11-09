import { useEffect, useState } from 'react';

// Initialize once; filters, telemetry changes and arriving aircraft never retarget.
export default function useShowAircraftSelection(fleet, runtimeMode) {
  const [selection, setSelection] = useState({ mode: runtimeMode, ids: null });
  const ids = selection.mode === runtimeMode ? selection.ids : null;
  useEffect(() => {
    if (ids === null && fleet.length) setSelection({ mode: runtimeMode, ids: fleet.map(d => String(d.hw_id)) });
  }, [fleet, ids, runtimeMode]);
  const setIds = next => setSelection(previous => ({ mode: runtimeMode,
    ids: typeof next === 'function' ? next(previous.mode === runtimeMode ? previous.ids || [] : []) : next }));
  return [ids || [], setIds];
}
