import { act, renderHook } from '@testing-library/react';
import useCommandDispatch from './useCommandDispatch';
import { fetchGcsResource } from '../services/gcsApiService';
import { sendDroneCommand } from '../services/droneApiService';
import { trackCommandReceipt } from '../utilities/commandLifecycleFeedback';

jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {} }) }));
jest.mock('../services/gcsApiService', () => ({ ...jest.requireActual('../services/gcsApiService'), buildGcsUrl: path => `https://gcs.test${path}`, fetchGcsResource: jest.fn() }));
jest.mock('../services/droneApiService', () => ({ ...jest.requireActual('../services/droneApiService'), sendDroneCommand: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ trackCommandReceipt: jest.fn() }));
const command = { mission_type: 3, target_drone_ids: ['2'], trigger_time: 1700000000, auto_global_origin: false, use_global_setpoints: false };

beforeEach(() => { jest.restoreAllMocks(); sessionStorage.clear(); jest.clearAllMocks(); });

test('lost receipt survives reload and is recovered by GET without replay or changing targets', async () => {
  sendDroneCommand.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = renderHook(() => useCommandDispatch('custom', 'sitl'));
  await act(async () => first.result.current.submit('launch', command));
  const frozen = first.result.current.pending.launch.command;
  expect(frozen).toMatchObject(command);
  first.unmount();
  const second = renderHook(() => useCommandDispatch('custom', 'sitl'));
  expect(second.result.current.pending.launch.command).toEqual(frozen);
  fetchGcsResource.mockResolvedValue({ data: { accepted_for_tracking: true, command_id: 'custom-1' } });
  await act(async () => second.result.current.recover('launch'));
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
  expect(fetchGcsResource).toHaveBeenCalledWith('/api/v1/commands/lookup', { params: { idempotency_key: frozen.idempotency_key } });
  expect(trackCommandReceipt).toHaveBeenCalledWith(frozen, expect.objectContaining({ command_id: 'custom-1' }), {});
  expect(second.result.current.pending).toEqual({});
});

test('lookup miss retains uncertainty, runtime modes are fenced, and definitive rejection permits new review', async () => {
  sendDroneCommand.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const { result, rerender } = renderHook(({ mode }) => useCommandDispatch('custom', mode), { initialProps: { mode: 'sitl' } });
  await act(async () => result.current.submit('launch', command));
  fetchGcsResource.mockRejectedValue({ response: { status: 404 } });
  await act(async () => result.current.recover('launch'));
  expect(result.current.pending.launch).toBeDefined();
  rerender({ mode: 'real' });
  expect(result.current.pending).toEqual({});
  sendDroneCommand.mockRejectedValue({ response: { status: 400, data: { detail: 'Native readiness rejected' } } });
  await act(async () => result.current.submit('launch', command));
  expect(result.current.pending).toEqual({});
  expect(result.current.error).toBe('Native readiness rejected');
});

test('serialization freezes nested data and persists the exact API payload before POST', async () => {
  const original = { ...command, target_drone_ids: ['2'], precision_move: { frame: 'body' }, uiMeta: { operatorLabel: 'Move' } };
  let finish;
  sendDroneCommand.mockImplementation(payload => {
    const saved = JSON.parse(sessionStorage.getItem(sessionStorage.key(0)));
    expect(saved.move.command).toEqual(payload);
    return new Promise(resolve => { finish = resolve; });
  });
  const { result } = renderHook(() => useCommandDispatch('move', 'sitl'));
  let work;
  act(() => { work = result.current.submit('move', original); });
  original.target_drone_ids.push('8'); original.precision_move.frame = 'ned';
  expect(sendDroneCommand.mock.calls[0][0]).toMatchObject({ target_drone_ids: ['2'], precision_move: { frame: 'body' }, operator_label: 'Move' });
  expect(sendDroneCommand.mock.calls[0][0].uiMeta).toBeUndefined();
  await act(async () => { finish({ accepted_for_tracking: true, command_id: 'frozen' }); await work; });
});

test('denied persistence never posts and accepted cleanup failure never becomes uncertainty', async () => {
  const write = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Denied'); });
  const first = renderHook(() => useCommandDispatch('denied', 'sitl'));
  await act(async () => first.result.current.submit('move', command));
  expect(sendDroneCommand).not.toHaveBeenCalled();
  expect(first.result.current.error).toMatch(/Command not sent/);
  first.unmount(); write.mockRestore();
  const originalWrite = Storage.prototype.setItem;
  let count = 0;
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(function(key, value) {
    if (++count > 1) throw new Error('Cleanup denied');
    originalWrite.call(this, key, value);
  });
  sendDroneCommand.mockResolvedValue({ accepted_for_tracking: true, command_id: 'accepted' });
  const second = renderHook(() => useCommandDispatch('accepted', 'sitl'));
  let accepted;
  await act(async () => { accepted = await second.result.current.submit('move', command); });
  expect(accepted).toBe(true);
  expect(second.result.current.pending).toEqual({});
  expect(second.result.current.error).toBe('');
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
});

test.each(['unmount', 'mode', 'namespace', 'operator'])('late result is fenced after %s', async change => {
  let finish;
  sendDroneCommand.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { result, rerender, unmount } = renderHook(({ mode, namespace, operator }) => useCommandDispatch(namespace, mode, operator),
    { initialProps: { mode: 'sitl', namespace: 'one', operator: 'pilot' } });
  let work;
  act(() => { work = result.current.submit('move', command); });
  if (change === 'unmount') unmount();
  else rerender({ mode: change === 'mode' ? 'real' : 'sitl', namespace: change === 'namespace' ? 'two' : 'one', operator: change === 'operator' ? 'other' : 'pilot' });
  let accepted;
  await act(async () => { finish({ accepted_for_tracking: true, command_id: 'late' }); accepted = await work; });
  expect(accepted).toBe(false);
  expect(trackCommandReceipt).not.toHaveBeenCalled();
});

test('pending commands can only be checked explicitly and invalid broad scope never posts', async () => {
  sendDroneCommand.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const { result } = renderHook(() => useCommandDispatch('explicit', 'sitl'));
  await act(async () => result.current.submit('move', command));
  await act(async () => result.current.submit('move', { ...command, target_drone_ids: ['9'] }));
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
  expect(fetchGcsResource).not.toHaveBeenCalled();
  await act(async () => result.current.submit('hold', { ...command, target_scope: 'all' }));
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
});
