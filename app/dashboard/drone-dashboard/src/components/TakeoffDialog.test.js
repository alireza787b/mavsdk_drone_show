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
const mockRefresh = jest.fn();
const mode = (2 << 24) | (4 << 16);
let mockRows, mockReceivedAt;
const ground = { telemetry_available: true, is_armed: false, landed_state: 1, heartbeat_age_ms: 0,
  landed_state_age_ms: 0, coordinated_takeoff_supported: true };
const report = (can_arm, custom_mode = mode) => ({ source: 'px4_events', custom_mode, mode: custom_mode === mode ? 'Takeoff' : 'Hold',
  can_arm, revision: 'a'.repeat(24), expires_at_gcs_ms: Date.now() + 5000 });
jest.mock('./ui/Px4ArmingStatus', () => {
  const actual = jest.requireActual('./ui/Px4ArmingStatus');
  const { default: useClock } = jest.requireActual('../hooks/useObservationClock');
  return { ...actual, usePx4Fleet: () => ({ rows: mockRows, now: useClock(), receivedAt: mockReceivedAt, refresh: mockRefresh }) };
});
const aircraft = [{ hw_id: '1', callsign: 'Scout' }, { hw_id: '2', callsign: 'Wing' }];

test.each([true, false])('only an applicable native PX4 report colors Takeoff (Position verdict %s)', async (positionVerdict) => {
  mockRows['1'].px4_takeoff_arming_report = report(true);
  mockRows['2'].px4_takeoff_arming_report = report(positionVerdict, 50593792);
  await ready();
  expect(screen.getByRole('img', { name: 'PX4 can arm · Takeoff' })).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: /Hold/ })).not.toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});
beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.clear();
  mockReceivedAt = Date.now();
  mockRows = { 1: { ...ground }, 2: { ...ground } };
  submitCommandWithLifecycleFeedback.mockResolvedValue({ command_id: 'launch-1', accepted_for_tracking: true });
  trackCommandReceipt.mockImplementation((_command, response) => response);
});
async function ready(props = {}) {
  const result = render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} {...props} />);
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  return result;
}

test('accepted scope bookkeeping gets the exact submitted targets, not the initiating roster', async()=>{
  const onAccepted=jest.fn();const beforeSubmit=jest.fn();
  await ready({onAccepted,beforeSubmit});
  fireEvent.click(screen.getByRole('checkbox',{name:/Include Wing/}));
  await waitFor(()=>expect(screen.getByRole('button',{name:/^Arm & take off/})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:/^Arm & take off/}));
  await waitFor(()=>expect(onAccepted).toHaveBeenCalledTimes(1));
  expect(beforeSubmit.mock.calls[0][0].target_drone_ids).toEqual(['1']);
  expect(onAccepted.mock.calls[0][0].target_drone_ids).toEqual(['1']);
});

test('a known rejection never tells the workspace that a different scope was accepted',async()=>{
  const onAccepted=jest.fn();
  submitCommandWithLifecycleFeedback.mockRejectedValue({response:{status:409,data:{detail:'Not ready'}}});
  await ready({onAccepted});
  fireEvent.click(screen.getByRole('button',{name:/^Arm & take off/}));
  await screen.findByText('Not ready');
  expect(onAccepted).not.toHaveBeenCalled();
});

test('review is read-only and multi-aircraft defaults to the armed barrier', async () => {
  await ready();
  expect(screen.getByRole('radio', { name: 'All armed first' })).toBeChecked();
  expect(screen.getByRole('spinbutton', { name: 'Takeoff height' })).toHaveValue(10);
  expect(screen.getAllByText('Reviewed')).toHaveLength(2);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '15' } });
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toEqual(expect.objectContaining({
    target_drone_ids: ['1', '2'], takeoff_altitude: 15, takeoff_mode: 'coordinated', idempotency_key: expect.any(String),
  }));
});

test('blocked aircraft remains visible and prevents group confirmation', async () => {
  mockRows['2'].landed_state = 2;
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findByText('Aircraft must be disarmed and on the ground');
  expect(screen.getByText('Wing')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('unavailable evidence never becomes green or actionable', async () => {
  mockRows = {};
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  expect(fetchGcsResource).not.toHaveBeenCalled();
  expect(screen.getAllByText('Checking')).toHaveLength(2);
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
});

test('Recheck reads shared telemetry and preserves the selected aircraft and height', async () => {
  await ready();
  fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '17' } });
  fireEvent.click(screen.getByRole('button', { name: 'Recheck' }));
  expect(mockRefresh).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeChecked();
  expect(screen.getByRole('spinbutton')).toHaveValue(17);
  expect(fetchGcsResource).not.toHaveBeenCalled();
});

test('independent mode is explicit and does not hide a member', async () => {
  await ready();
  fireEvent.click(screen.getByRole('radio', { name: 'Independent' }));
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toEqual(expect.objectContaining({ takeoff_mode: 'independent', target_drone_ids: ['1', '2'] }));
});

test('older software cannot silently fall back to independent launch', async () => {
  Object.values(mockRows).forEach(row => { row.coordinated_takeoff_supported = false; });
  render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findAllByText('Software update required for coordinated takeoff');
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('radio', { name: 'Independent' }));
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled();
});

test('single-aircraft dialog uses the same height review without the checkbox', async () => {
  await ready({ command: { ...command, target_drone_ids: ['1'] } });
  expect(screen.queryByRole('radio', { name: 'All armed first' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Select all' })).not.toBeInTheDocument();
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

test('only aircraft use checkboxes and group mode survives a single-aircraft selection', async () => {
  await ready();
  expect(screen.getAllByRole('checkbox')).toHaveLength(2);
  expect(screen.getByRole('group', { name: 'Launch mode' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('radio', { name: 'Independent' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  expect(screen.queryByRole('radio')).not.toBeInTheDocument();
  expect(screen.getByText('Single aircraft')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  expect(screen.getByRole('radio', { name: 'Independent' })).toBeChecked();
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

test('short native lease does not flicker review; stalled preview still expires', async () => {
  jest.useFakeTimers();
  try {
    mockReceivedAt = Date.now();
    render(<TakeoffDialog open command={command} aircraft={aircraft} onClose={jest.fn()} />);
    await act(async () => {});
    expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled();
    await act(async () => { jest.advanceTimersByTime(2100); });
    expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled();
    expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
    await act(async () => { jest.advanceTimersByTime(3100); });
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
  expect(screen.queryByRole('radio', { name: 'All armed first' })).not.toBeInTheDocument();
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
  mockRows['2'].landed_state = 2;
  render(<TakeoffDialog open command={{ ...command, takeoff_mode: 'coordinated', uiMeta: { targetLabel: 'Cluster 1' } }} aircraft={aircraft} onClose={jest.fn()} />);
  await screen.findByText('Aircraft must be disarmed and on the ground');
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeChecked();
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Include Wing (H2)' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm & take off · 1 aircraft' })).toBeEnabled());
  expect(screen.getByText('Wing').closest('li')).toHaveClass('takeoff-review__aircraft--excluded');
  expect(screen.getByText('Not included')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Select all' })).toBeEnabled();
  expect(fetchGcsResource).not.toHaveBeenCalled();
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
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
  expect(screen.getByText('Aircraft · 0 of 2')).toBeInTheDocument();
  expect(screen.getAllByText('Not included')).toHaveLength(2);
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  expect(fetchGcsResource).toHaveBeenCalledTimes(calls);
  fireEvent.click(screen.getByRole('button', { name: 'Select all' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Arm & take off · 2 aircraft' })).toBeEnabled());
  expect(screen.getByRole('radio', { name: 'All armed first' })).toBeChecked();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('selection freezes before asynchronous preparation finishes', async () => {
  let finish;
  await ready({ beforeSubmit: () => new Promise((resolve) => { finish = resolve; }) });
  fireEvent.click(screen.getByRole('button', { name: /^Arm & take off/ }));
  expect(screen.getByRole('checkbox', { name: 'Include Wing (H2)' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Select all' })).not.toBeInTheDocument();
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

test('a missing native report stays in Details without a caution badge', async () => {
  await ready();
  const details = screen.getAllByLabelText('PX4 arming report')[0].parentElement;
  details.open = true;
  fireEvent(details, new Event('toggle'));
  expect(await screen.findByText('PX4 report unavailable')).toBeInTheDocument();
  expect(screen.queryByRole('button', { name: /Caution/ })).not.toBeInTheDocument();
});

test('an explicit native red verdict is shown independently of aircraft admission', async () => {
  mockRows['1'].px4_takeoff_arming_report = report(false);
  await ready();
  expect(screen.getByRole('img', { name: 'PX4 cannot arm · Takeoff' })).toBeInTheDocument();
  expect(screen.getByRole('checkbox', { name: 'Include Scout (H1)' })).toBeChecked();
});

test('the native badge survives missed updates and disappears on its original deadline', async () => {
  jest.useFakeTimers();
  try {
    mockReceivedAt = Date.now();
    mockRows['1'].px4_takeoff_arming_report = report(false);
    await ready();
    expect(screen.getByRole('img', { name: 'PX4 cannot arm · Takeoff' })).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(4200); });
    expect(screen.getByRole('img', { name: 'PX4 cannot arm · Takeoff' })).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(1000); });
    expect(screen.queryByRole('img', { name: 'PX4 cannot arm · Takeoff' })).not.toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});
