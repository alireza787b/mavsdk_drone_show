import { useCallback, useMemo, useRef, useState } from 'react';
import { createDraftHistory, draftHistoryReducer } from '../utilities/swarmFormationGeometry';

/** One draft/history authority. Ref updates are synchronous across pointer events. */
export default function useSwarmDesignDraft(initialAssignments = []) {
  const [state, setState] = useState(() => createDraftHistory(initialAssignments));
  const stateRef = useRef(state);
  const assignmentsRef = useRef(state.present);
  const dispatch = useCallback((action) => {
    const next = draftHistoryReducer(stateRef.current, action);
    stateRef.current = next;
    assignmentsRef.current = next.present;
    setState(next);
    return next.present;
  }, []);
  const actions = useMemo(() => ({
    reset: (assignments) => dispatch({ type: 'reset', assignments }),
    replace: (assignments) => dispatch({ type: 'edit', assignments }),
    edit: (id, patch) => dispatch({ type: 'edit', id, patch }),
    begin: () => dispatch({ type: 'begin' }),
    end: ({ cancelled = false } = {}) => dispatch({ type: 'end', cancelled }),
    undo: () => {
      if (stateRef.current.gesture) return dispatch({ type: 'end', cancelled: true });
      return dispatch({ type: 'undo' });
    },
    redo: () => {
      if (stateRef.current.gesture) return dispatch({ type: 'end', cancelled: true });
      return dispatch({ type: 'redo' });
    },
  }), [dispatch]);
  return {
    assignments: state.present,
    assignmentsRef,
    ...actions,
    canUndo: state.past.length > 0 || Boolean(state.gesture),
    canRedo: state.future.length > 0 && !state.gesture,
    isEditing: Boolean(state.gesture),
  };
}
