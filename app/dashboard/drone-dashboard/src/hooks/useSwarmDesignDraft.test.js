import { act, renderHook } from '@testing-library/react';
import useSwarmDesignDraft from './useSwarmDesignDraft';

const initial = [{ hw_id: '1', follow: '0', offset_x: 0 }, { hw_id: '2', follow: '1', offset_x: 6 }];

test('same-event begin/edit/end is one transaction with synchronous current data', () => {
  const { result } = renderHook(() => useSwarmDesignDraft(initial));
  act(() => {
    result.current.begin();
    result.current.edit('2', { offset_x: 9 });
    expect(result.current.assignmentsRef.current[1].offset_x).toBe(9);
    result.current.edit('2', { offset_x: 12 });
    result.current.end();
  });
  expect(result.current.assignments[1].offset_x).toBe(12);
  act(() => result.current.undo());
  expect(result.current.assignments).toEqual(initial);
  expect(result.current.canUndo).toBe(false);
  act(() => result.current.redo());
  expect(result.current.assignments[1].offset_x).toBe(12);
});

test('cancel on view switch restores draft and preserves earlier undo', () => {
  const { result } = renderHook(() => useSwarmDesignDraft(initial));
  act(() => result.current.edit('2', { offset_x: 8 }));
  act(() => { result.current.begin(); result.current.edit('2', { offset_x: 15 }); result.current.end({ cancelled: true }); });
  expect(result.current.assignments[1].offset_x).toBe(8);
  act(() => result.current.undo());
  expect(result.current.assignments).toEqual(initial);
});

test('replace is undoable and reset clears history', () => {
  const { result } = renderHook(() => useSwarmDesignDraft(initial));
  const replacement = [{ hw_id: '3', follow: '0', offset_x: 0 }];
  act(() => result.current.replace(replacement));
  expect(result.current.canUndo).toBe(true);
  act(() => result.current.undo()); expect(result.current.assignments).toEqual(initial);
  act(() => result.current.reset(replacement));
  expect(result.current.canUndo).toBe(false); expect(result.current.canRedo).toBe(false);
  expect(result.current.assignmentsRef.current).toEqual(replacement);
});

test('undo during a gesture cancels only that gesture', () => {
  const { result } = renderHook(() => useSwarmDesignDraft(initial));
  act(() => result.current.edit('2', { offset_x: 8 }));
  act(() => { result.current.begin(); result.current.edit('2', { offset_x: 9 }); result.current.undo(); });
  expect(result.current.assignments[1].offset_x).toBe(8);
  expect(result.current.isEditing).toBe(false);
  expect(result.current.canUndo).toBe(true);
});
