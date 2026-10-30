import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import TakeoffDialog from './TakeoffDialog';
import { fetchGcsResource, postGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../utilities/commandLifecycleFeedback';

jest.mock('../services/gcsApiService', () => ({ fetchGcsResource: jest.fn(), postGcsResource: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn(), trackCommandReceipt: jest.fn() }));
const mockCallbacks = { onStatusUpdate: jest.fn() };
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: mockCallbacks }) }));
const command = { mission_type: 10, trigger_time: 0, target_drone_ids: ['1', '2'], takeoff_altitude: 10 };
const native = { valid_for_ms: 5000, targets: ['1', '2'].map((hw_id) => ({ hw_id, status: 'ready', coordinated_takeoff_supported: true })) };
const aircraft = [{ hw_id: '1', callsign: 'Scout' }, { hw_id: '2', callsign: 'Wing' }];
beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.clear();
  fetchGcsResource.mockResolvedValue({ data: native });
  submitCommandWithLifecycleFeedback.mockResolvedValue({ command_id: 'launch-1', accepted_for_tracking: true });
  trackCommandReceipt.mockImplementation((_command, response) => response);
});
async function ready(props = {}) {
  const result = render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} {...props} />);
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  return result;
}

test('review is read-only and multi-aircraft defaults to the armed barrier', async () => {
  await ready();
  expect(screen.getByRole('checkbox', { name: 'Wait for all aircraft' })).toBeChecked();
  expect(screen.getByRole('spinbutton', { name: 'Takeoff height' })).toHaveValue(10);
  expect(screen.getAllByText('Ready')).toHaveLength(2);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '15' } });
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toEqual(expect.objectContaining({
    target_drone_ids: ['1', '2'], takeoff_altitude: 15, takeoff_mode: 'coordinated', idempotency_key: expect.any(String),
  }));
});

test('blocked aircraft remains visible and prevents group confirmation', async () => {
  fetchGcsResource.mockResolvedValue({ data: { valid_for_ms: 5000, targets: [native.targets[0], { hw_id: '2', status: 'blocked', reason: 'Heading estimate unstable' }] } });
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findByText('Heading estimate unstable');
  expect(screen.getByText('Wing')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('unavailable evidence never becomes green or actionable', async () => {
  fetchGcsResource.mockRejectedValue(new Error('Offline'));
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalled());
  expect(screen.getAllByText('Checking')).toHaveLength(2);
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
});

test('native probe processing is not subtracted twice from the returned freshness lease', async () => {
  const clock = jest.spyOn(Date, 'now');
  let current = 10000;
  clock.mockImplementation(() => current);
  fetchGcsResource.mockImplementation(async () => {
    current += 2000;
    return { data: { ...native, valid_for_ms: 900, server_processing_ms: 1990 } };
  });
  try {
    await ready();
    expect(screen.getAllByText('Ready')).toHaveLength(2);
  } finally { clock.mockRestore(); }
});

test('independent mode is explicit and does not hide a member', async () => {
  await ready();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Wait for all aircraft' }));
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toEqual(expect.objectContaining({ takeoff_mode: 'independent', target_drone_ids: ['1', '2'] }));
});

test('older software cannot silently fall back to independent launch', async () => {
  fetchGcsResource.mockResolvedValue({ data: { valid_for_ms: 5000, targets: native.targets.map((row) => ({ ...row, coordinated_takeoff_supported: false })) } });
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findAllByText('Software update required for coordinated takeoff');
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Wait for all aircraft' }));
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled();
});

test('single-aircraft dialog uses the same height review without the checkbox', async () => {
  await ready({ command: { ...command, target_drone_ids: ['1'] } });
  expect(screen.queryByRole('checkbox', { name: 'Wait for all aircraft' })).not.toBeInTheDocument();
  expect(screen.queryByRole('checkbox', { name: 'Select all aircraft' })).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Include Scout (H1)' })).toBeChecked();
  expect(screen.queryByText('Wing')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].takeoff_mode).toBeUndefined();
});

test('closing review sends no command', async () => {
  const onClose = jest.fn();
  await ready({ onClose });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(onClose).toHaveBeenCalled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('progress reuses the tracked command and Cancel launch is separate from Close', async () => {
  const onClose = jest.fn();
  await ready({ onClose });
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  const lifecycle = submitCommandWithLifecycleFeedback.mock.calls[0][1];
  await act(async () => lifecycle.onStatusUpdate({ isTerminal: false }, { coordinated_takeoff: {
    phase: 'arming', armed_count: 1, total: 2, targets: { '1': { state: 'armed' }, '2': { state: 'arming' } },
  } }));
  expect(screen.getByText('Arming 1/2')).toBeInTheDocument();
  expect(mockCallbacks.onStatusUpdate).toHaveBeenCalled();
  postGcsResource.mockResolvedValue({ data: { coordinated_takeoff: { phase: 'aborted', reason: 'Cancelled by operator' } } });
  fireEvent.click(screen.getByRole('button', { name: 'Cancel launch' }));
  await waitFor(() => expect(postGcsResource).toHaveBeenCalledWith('/api/v1/commands/launch-1/cancel-launch', {}));
  await screen.findByText('Cancelling', { selector: '.takeoff-review__progress' });
  expect(screen.queryByRole('button', { name: 'Done' })).not.toBeInTheDocument();
  expect(screen.queryByText('Launch cancelled')).not.toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  expect(onClose).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole('dialog')).getAllByRole('button', { name: 'Close' })[0]);
  expect(onClose).toHaveBeenCalled();
});

test('cancelled cleanup is shown confirmed only from terminal aircraft evidence', async () => {
  await ready();
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  const lifecycle = submitCommandWithLifecycleFeedback.mock.calls[0][1];
  await act(async () => lifecycle.onStatusUpdate({ isTerminal: false }, {
    coordinated_takeoff: { phase: 'aborted' },
    executions: { details: { '1': { action_result: { final_vehicle_state: { armed: false } } } } },
  }));
  expect(screen.getByText('Cancelling', { selector: '.takeoff-review__progress' })).toBeInTheDocument();
  expect(screen.getByText('disarmed')).toBeInTheDocument();
  expect(screen.getByText('checking aircraft')).toBeInTheDocument();
  await act(async () => lifecycle.onTrackingComplete({ isTerminal: true, outcome: 'failed' }, {
    coordinated_takeoff: { phase: 'aborted' },
    executions: { details: { '1': { action_result: { final_vehicle_state: { armed: false } } },
      '2': { action_result: { final_vehicle_state: { armed: true, recovery_status: 'disarm_unconfirmed' } } } } },
  }));
  expect(screen.getByText('Check aircraft')).toBeInTheDocument();
  expect(screen.getByText('recovery unconfirmed')).toBeInTheDocument();
  await act(async () => lifecycle.onTrackingComplete({ isTerminal: true, outcome: 'failed' }, {
    coordinated_takeoff: { phase: 'aborted' },
    executions: { details: Object.fromEntries(['1', '2'].map((id) => [id, { action_result: { final_vehicle_state: { armed: false } } }])) },
  }));
  expect(screen.getByText('Launch cancelled')).toBeInTheDocument();
  expect(screen.getAllByText('disarmed')).toHaveLength(2);
});

test('expired readiness becomes Checking even if the next request never resolves', async () => {
  jest.useFakeTimers();
  try {
    fetchGcsResource.mockResolvedValueOnce({ data: { ...native, valid_for_ms: 2000 } })
      .mockImplementation(() => new Promise(() => {}));
    render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
    await act(async () => {});
    expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled();
    await act(async () => { jest.advanceTimersByTime(2100); });
    expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
    expect(screen.queryByText('Ready')).not.toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('StrictMode remount still receives progress without duplicate submission', async () => {
  render(<React.StrictMode><TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} /></React.StrictMode>);
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  await act(async () => submitCommandWithLifecycleFeedback.mock.calls[0][1].onStatusUpdate({}, {
    coordinated_takeoff: { phase: 'arming', armed_count: 1, total: 2 },
  }));
  expect(screen.getByText('Arming 1/2')).toBeInTheDocument();
});

test('uncertain receipt survives close/reopen and is recovered without resubmission', async () => {
  submitCommandWithLifecycleFeedback.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = await ready();
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await screen.findByRole('button', { name: 'Check command' });
  const sent = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  first.unmount();
  fetchGcsResource.mockResolvedValue({ data: { accepted_for_tracking: true, command_id: 'recovered-1' } });
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  expect(screen.queryByRole('checkbox', { name: 'Wait for all aircraft' })).not.toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Include Scout (H1)' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(expect.objectContaining({
    idempotency_key: sent.idempotency_key, takeoff_altitude: 10, takeoff_mode: 'coordinated',
  }), expect.anything(), expect.anything()));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('incoming scope is selected by default, without adding aircraft outside that scope', async () => {
  await ready({ command: { ...command, target_drone_ids: ['2'] } });
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeChecked();
  expect(screen.queryByText('Scout')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Arm & take off · 1 aircraft' })).toBeEnabled();
});

test('zero group lease preserves the blocked reason; explicit exclusion changes only Takeoff targets', async () => {
  fetchGcsResource.mockResolvedValue({ data: { valid_for_ms: 0, targets: [
    { ...native.targets[0], valid_for_ms: 5000 },
    { hw_id: '2', status: 'blocked', valid_for_ms: 0, reason: 'Heading estimate unstable' },
  ] } });
  render(<TakeoffDialog open command={{ ...command, takeoff_mode: 'coordinated', uiMeta: { targetLabel: 'Cluster 1' } }} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findByText('Heading estimate unstable');
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeChecked();
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm & take off · 1 aircraft' })).toBeEnabled());
  expect(screen.getByText('Wing').closest('li')).toHaveClass('takeoff-review__aircraft--excluded');
  expect(screen.getByText('Not included')).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Select all aircraft' })).toBePartiallyChecked();
  expect(fetchGcsResource).toHaveBeenLastCalledWith('/api/v1/commands/takeoff-readiness?target_drone_ids=1');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  const sent = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  expect(sent.target_drone_ids).toEqual(['1']);
  expect(sent.takeoff_mode).toBeUndefined();
  expect(sent.uiMeta.targetLabel).toBe('1 aircraft');
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeDisabled();
  expect(screen.getByText('Not included')).toBeInTheDocument();
});

test('select all supports none and restore, with no launch or empty readiness request', async () => {
  await ready();
  const calls = fetchGcsResource.mock.calls.length;
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select all aircraft' }));
  expect(screen.getByText('0 of 2 aircraft')).toBeInTheDocument();
  expect(screen.getAllByText('Not included')).toHaveLength(2);
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  expect(fetchGcsResource).toHaveBeenCalledTimes(calls);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select all aircraft' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm & take off · 2 aircraft' })).toBeEnabled());
  expect(screen.getByRole('checkbox', { name: 'Wait for all aircraft' })).toBeChecked();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('selection freezes before asynchronous preparation finishes', async () => {
  let finish;
  await ready({ beforeSubmit: () => new Promise((resolve) => { finish = resolve; }) });
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeDisabled();
  expect(screen.getByRole('checkbox', { name: 'Select all aircraft' })).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  await act(async () => finish());
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].target_drone_ids).toEqual(['1', '2']);
});

test('uncertain subset survives close/reopen with exactly the reviewed payload and no resubmit', async () => {
  submitCommandWithLifecycleFeedback.mockRejectedValue(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = await ready();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await screen.findByRole('button', { name: 'Check command' });
  const sent = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  first.unmount();
  fetchGcsResource.mockResolvedValue({ data: { command_id: 'recovered-1', accepted_for_tracking: true } });
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  expect(screen.getByRole('checkbox', { name: 'Include Scout (H1)' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).not.toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(sent, expect.anything(), expect.anything()));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('after a definite rejection an edited selection gets a new identity and ambiguous recovery uses that identity', async () => {
  submitCommandWithLifecycleFeedback.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Review required' } } })
    .mockRejectedValueOnce(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  await ready();
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await screen.findByText('Review required');
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await screen.findByRole('button', { name: 'Check command' });
  const first = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  const second = submitCommandWithLifecycleFeedback.mock.calls[1][0];
  expect(second.idempotency_key).not.toBe(first.idempotency_key);
  expect(second.target_drone_ids).toEqual(['1']);
  fetchGcsResource.mockResolvedValue({ data: { command_id: 'recovered-2', accepted_for_tracking: true } });
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(fetchGcsResource).toHaveBeenLastCalledWith('/api/v1/commands/lookup', {
    params: { idempotency_key: second.idempotency_key },
  }));
  expect(trackCommandReceipt).toHaveBeenCalledWith(second, expect.anything(), expect.anything());
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2);
});
