import { useCallback, useMemo, useRef, useState } from 'react';
import { createDraftHistory, draftHistoryReducer } from '../utilities/swarmFormationGeometry';

/** One draft/history authority. Ref updates are synchronous across pointer events. */
export default function useSwarmDesignDraft(initialAssignments = []) {
  const [state, setState] = useState(() => createDraftHistory(initialAssignments));
  const stateRef = useRef(state);
  const assignmentsRef = useRef(state.present);
  const metadataRef = useRef(state.metadata);
  const dispatch = useCallback((action) => {
    const next = draftHistoryReducer(stateRef.current, action);
    stateRef.current = next;
    assignmentsRef.current = next.present;
    metadataRef.current = next.metadata;
    setState(next);
    return next.present;
  }, []);
  const actions = useMemo(() => ({
    reset: (assignments, metadata) => dispatch({ type: 'reset', assignments, metadata }),
    replace: (assignments, metadata) => dispatch({ type: 'edit', assignments, metadata }),
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
    metadata: state.metadata,
    metadataRef,
    ...actions,
    canUndo: state.past.length > 0 || Boolean(state.gesture),
    canRedo: state.future.length > 0 && !state.gesture,
    isEditing: Boolean(state.gesture),
  };
}
