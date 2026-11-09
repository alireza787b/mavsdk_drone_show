import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import ActionReview, { buildActionStorageKey, readPendingAction, readPendingActions } from './ActionReview';
import { DRONE_ACTION_TYPES, DRONE_MISSION_TYPES } from '../../constants/droneConstants';
import { fetchGcsResource } from '../../services/gcsApiService';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../../utilities/commandLifecycleFeedback';

jest.mock('../../services/gcsApiService', () => ({ ...jest.requireActual('../../services/gcsApiService'), fetchGcsResource: jest.fn() }));
jest.mock('../../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn(), trackCommandReceipt: jest.fn() }));
const mockCallbacks = { onSubmissionTracked: jest.fn() };
jest.mock('../../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: mockCallbacks }) }));

const KEY = 'action-review-test';
const receipt = { accepted_for_tracking: true, command_id: 'action-1' };
const intent = () => ({ mission_type: DRONE_ACTION_TYPES.HOLD, trigger_time: 0,
  target_drone_ids: ['2', '7'], uiMeta: { operatorLabel: 'Hold' } });
function setup(overrides = {}, strict = false) {
  const props = { intent: intent(), storageKey: KEY, runtimeMode: 'sitl', onClose: jest.fn(), onResolved: jest.fn(), ...overrides };
  const element = <ActionReview {...props} />;
  return { ...render(strict ? <React.StrictMode>{element}</React.StrictMode> : element), props };
}
const confirm = () => fireEvent.click(screen.getByRole('button', { name: /^Confirm/ }));
beforeEach(() => {
  jest.restoreAllMocks(); jest.clearAllMocks(); sessionStorage.clear();
  submitCommandWithLifecycleFeedback.mockResolvedValue(receipt);
  trackCommandReceipt.mockImplementation((_command, value) => value);
});

test('freezes exact IDs, nested parameters, key and serialized body before POST', async () => {
  const original = { ...intent(), precision_move: { north: 2 } };
  const { rerender, props } = setup({ intent: original });
  original.target_drone_ids.push('9'); original.precision_move.north = 20;
  rerender(<ActionReview {...props} intent={original} />);
  submitCommandWithLifecycleFeedback.mockImplementation(async body => {
    expect(JSON.parse(sessionStorage.getItem(KEY))).toEqual(body);
    return receipt;
  });
  confirm();
  await waitFor(() => expect(props.onResolved).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toEqual(expect.objectContaining({
    target_drone_ids: ['2', '7'], precision_move: { north: 2 }, idempotency_key: expect.any(String), operator_label: 'Hold' }));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].uiMeta).toBeUndefined();
});

test('REAL motor test requires each independent physical acknowledgment', async () => {
  setup({ runtimeMode: 'real', intent: { ...intent(), mission_type: String(DRONE_ACTION_TYPES.TEST),
    ground_test_safety: { mode: 'operator_acknowledged', props_removed: true, airframe_secured: true, area_clear: true } } });
  const button = screen.getByRole('button', { name: /^Confirm/ });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText('All propellers removed'));
  fireEvent.click(screen.getByLabelText('Every airframe secured'));
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByLabelText('Test area clear'));
  expect(button).toBeEnabled();
  confirm();
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].ground_test_safety).toEqual({
    mode: 'operator_acknowledged', props_removed: true, airframe_secured: true, area_clear: true });
  expect(screen.queryByText(/five-second/)).not.toBeInTheDocument();
});

test('uncertain SITL motor test checks only its saved request and original safety metadata', async () => {
  submitCommandWithLifecycleFeedback.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = setup({ intent: { ...intent(), mission_type: DRONE_ACTION_TYPES.TEST } });
  confirm();
  await screen.findByRole('button', { name: 'Check command' });
  const sent = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  expect(sent.ground_test_safety).toEqual({ mode: 'sitl_not_applicable' });
  expect(readPendingAction(KEY)).toEqual(sent);
  fetchGcsResource.mockRejectedValue({ response: { status: 404 } });
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalledTimes(1));
  expect(readPendingAction(KEY)).toEqual(sent);
  first.unmount();
  setup({ intent: { ...sent, recover: true } });
  fetchGcsResource.mockResolvedValue({ data: receipt });
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(sent, receipt, mockCallbacks));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  expect(fetchGcsResource).toHaveBeenLastCalledWith('/api/v1/commands/lookup', { params: { idempotency_key: sent.idempotency_key } });
});

test('denied persistence fails closed before POST', async () => {
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Denied'); });
  setup(); confirm();
  expect(await screen.findByRole('alert')).toHaveTextContent('Command not sent');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  expect(fetchGcsResource).not.toHaveBeenCalled();
});

test('same-mounted receipt recovery retains the safety-enriched sent payload', async () => {
  submitCommandWithLifecycleFeedback.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  setup({ intent: { ...intent(), mission_type: DRONE_ACTION_TYPES.TEST } });
  confirm();
  const check = await screen.findByRole('button', { name: 'Check command' });
  const sent = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  fetchGcsResource.mockResolvedValue({ data: receipt });
  fireEvent.click(check);
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(sent, receipt, mockCallbacks));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('closing an unsubmitted review never sends or saves a command', () => {
  const { props } = setup();
  fireEvent.click(screen.getByRole('button', { name: 'Close', exact: true }));
  expect(props.onClose).toHaveBeenCalledTimes(1);
  expect(readPendingAction(KEY)).toBeNull();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('cancel mission explains that cancellation is not verified Hold or landing', () => {
  setup({ intent: { ...intent(), mission_type: DRONE_MISSION_TYPES.NONE, uiMeta: { operatorLabel: 'Cancel mission' } } });
  expect(screen.getByText(/Cancellation alone is not verified Hold or landing/)).toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('cleanup failure cannot turn an accepted action into retry or uncertainty', async () => {
  jest.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('Denied'); });
  const { props } = setup(); confirm();
  await waitFor(() => expect(props.onResolved).toHaveBeenCalledTimes(1));
  expect(props.onClose).toHaveBeenCalledTimes(1);
  expect(readPendingAction(KEY)).toBeNull();
  confirm();
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

test('StrictMode effect replay still permits resolution callbacks', async () => {
  const { props } = setup({}, true); confirm();
  await waitFor(() => expect(props.onResolved).toHaveBeenCalledTimes(1));
});

test('unmount during submission does not call closing callbacks or dispatch again', async () => {
  let finish;
  submitCommandWithLifecycleFeedback.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { props, unmount } = setup(); confirm(); unmount();
  await act(async () => finish(receipt));
  expect(props.onClose).not.toHaveBeenCalled();
  expect(props.onResolved).not.toHaveBeenCalled();
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('unknown/changed runtime and ambiguous scopes cannot submit', () => {
  const view = setup({ runtimeMode: 'unknown' });
  expect(screen.getByRole('button', { name: /^Confirm/ })).toBeDisabled();
  view.unmount();
  const next = setup();
  next.rerender(<ActionReview {...next.props} runtimeMode="real" />);
  expect(screen.getByRole('button', { name: /^Confirm/ })).toBeDisabled();
  next.unmount();
  setup({ intent: { ...intent(), target_scope: 'all' } });
  expect(screen.getByRole('button', { name: /^Confirm/ })).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('action storage keys use exact target sets independent of order, parameters, and request identity', () => {
  const prefix = 'scope:real:operator';
  const key = buildActionStorageKey(prefix, intent());
  expect(buildActionStorageKey(prefix, { ...intent(), target_drone_ids: ['7', '2'],
    trigger_time: 900, idempotency_key: 'another', uiMeta: { operatorLabel: 'Changed' } })).toBe(key);
  expect(buildActionStorageKey(prefix, { ...intent(), target_drone_ids: ['2'] })).not.toBe(key);
  expect(buildActionStorageKey(prefix, { ...intent(), mission_type: DRONE_ACTION_TYPES.RETURN_RTL })).not.toBe(key);
  expect(buildActionStorageKey('other:real:operator', intent())).not.toBe(key);
  expect(buildActionStorageKey(prefix, { ...intent(), target_scope: 'all' })).toBeNull();
  expect(buildActionStorageKey(prefix, { ...intent(), target_drone_ids: [] })).toBeNull();
});

test('uncertain LED request remains recoverable while a separate Return can submit', async () => {
  const prefix = 'scope:sitl:operator';
  const led = { ...intent(), mission_type: DRONE_ACTION_TYPES.TEST_LED, uiMeta: { operatorLabel: 'LED test' } };
  const ledKey = buildActionStorageKey(prefix, led);
  submitCommandWithLifecycleFeedback.mockRejectedValueOnce(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = setup({ intent: led, storageKey: ledKey });
  confirm();
  await screen.findByRole('button', { name: 'Check command' });
  const saved = readPendingAction(ledKey);
  first.unmount();
  const returnIntent = { ...intent(), mission_type: DRONE_ACTION_TYPES.RETURN_RTL };
  const returnKey = buildActionStorageKey(prefix, returnIntent);
  const next = setup({ intent: returnIntent, storageKey: returnKey });
  confirm();
  await waitFor(() => expect(next.props.onResolved).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2);
  expect(readPendingActions(prefix)).toEqual([{ storageKey: ledKey, command: saved }]);
  expect(readPendingAction(returnKey)).toBeNull();
  next.unmount();
  // Even a caller opening this as a fresh intent cannot replay the LED command.
  setup({ intent: led, storageKey: ledKey });
  fetchGcsResource.mockResolvedValue({ data: receipt });
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalledWith('/api/v1/commands/lookup', {
    params: { idempotency_key: saved.idempotency_key },
  }));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2);
});

test('busy review can close and late acceptance cannot close a newer review', async () => {
  let finish;
  submitCommandWithLifecycleFeedback.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const first = setup({ storageKey: buildActionStorageKey('scope', intent()) });
  confirm();
  expect(screen.getByText(/Closing this review does not cancel/)).toBeInTheDocument();
  const close = screen.getByRole('button', { name: 'Close', exact: true });
  expect(close).toBeEnabled();
  fireEvent.click(close);
  expect(first.props.onClose).toHaveBeenCalledTimes(1);
  expect(readPendingAction(first.props.storageKey)).not.toBeNull();
  first.unmount();
  const newer = { ...intent(), mission_type: DRONE_ACTION_TYPES.RETURN_RTL, uiMeta: { operatorLabel: 'Return' } };
  const next = setup({ intent: newer, storageKey: buildActionStorageKey('scope', newer) });
  await act(async () => finish(receipt));
  expect(first.props.onClose).toHaveBeenCalledTimes(1);
  expect(first.props.onResolved).not.toHaveBeenCalled();
  expect(next.props.onClose).not.toHaveBeenCalled();
  expect(next.props.onResolved).not.toHaveBeenCalled();
  expect(screen.getByRole('heading', { name: 'Return' })).toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('pending list includes legacy receipt, excludes other contexts and malformed data, and is bounded', () => {
  const prefix = 'bounded';
  const saved = { ...intent(), idempotency_key: 'legacy' };
  sessionStorage.setItem(prefix, JSON.stringify(saved));
  sessionStorage.setItem(`${prefix}:action:invalid`, '{}');
  sessionStorage.setItem('other:action:one', JSON.stringify(saved));
  expect(readPendingActions(prefix)).toEqual([{ storageKey: prefix, command: saved }]);
  for (let index = 0; index < 70; index += 1) {
    const command = { ...saved, target_drone_ids: [String(index)], idempotency_key: `pending-${index}` };
    sessionStorage.setItem(buildActionStorageKey(prefix, command), JSON.stringify(command));
  }
  expect(readPendingActions(prefix)).toHaveLength(64);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  expect(fetchGcsResource).not.toHaveBeenCalled();
});

test('concurrent saved receipt is not overwritten by an already-open review', async () => {
  setup();
  const saved = { ...intent(), idempotency_key: 'another-review' };
  sessionStorage.setItem(KEY, JSON.stringify(saved));
  confirm();
  expect(await screen.findByRole('alert')).toHaveTextContent('already has an unconfirmed receipt');
  expect(readPendingAction(KEY)).toEqual(saved);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('silently dropped persistence fails closed before POST', async () => {
  jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  setup(); confirm();
  expect(await screen.findByRole('alert')).toHaveTextContent('Command not sent');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});
