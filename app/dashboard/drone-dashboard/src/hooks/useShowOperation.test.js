import { renderHook } from '@testing-library/react';
import useShowOperation from './useShowOperation';
import useGcsResourcePolling from './useGcsResourcePolling';

jest.mock('./useGcsResourcePolling');

test('poll failure retains recorded recovery targets without claiming fresh data', () => {
  const data = { operation_target_ids: ['7'], command_id: 'show-7' };
  useGcsResourcePolling.mockReturnValue({ data, receivedAt: 100 });
  const { result, rerender } = renderHook(() => useShowOperation(3, 'sitl'));
  expect(result.current.data).toEqual(data);
  const error = new Error('Disconnected');
  useGcsResourcePolling.mockReturnValue({ data: null, error });
  rerender();
  expect(result.current.data.operation_target_ids).toEqual(['7']);
  expect(result.current.error).toBe(error);
  expect(result.current.receivedAt).toBe(100);
});

test('runtime transition cannot carry an old operation into the new runtime', () => {
  const old = { data: { operation_target_ids: ['7'] }, receivedAt: 100 };
  useGcsResourcePolling.mockReturnValue(old);
  const { result, rerender } = renderHook(({ mode }) => useShowOperation(1, mode), { initialProps: { mode: 'sitl' } });
  rerender({ mode: 'real' });
  expect(result.current.data).toBeNull();
  useGcsResourcePolling.mockReturnValue({ data: { operation_target_ids: ['9'] }, receivedAt: 200 });
  rerender({ mode: 'real' });
  expect(result.current.data.operation_target_ids).toEqual(['9']);
});
