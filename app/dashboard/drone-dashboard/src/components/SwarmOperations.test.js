import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SwarmOperations from './SwarmOperations';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback, trackCommandReceipt } from '../utilities/commandLifecycleFeedback';
jest.mock('../services/gcsApiService', () => ({ fetchGcsResource: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn(), trackCommandReceipt: jest.fn() }));
const mockMonitors = [];
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {}, commandMonitors: mockMonitors }) }));
jest.mock('./SequentialReturnControl', () => ({ targetIds, compact }) => <button>Return {compact ? targetIds.join(',') : 'legacy'}</button>);
const decisions = Object.fromEntries(['1', '2'].map((id) => [id, { hw_id: id, status: 'ready', message: 'Ready', valid_for_ms: 10000 }]));
const takeoffReadiness = { valid_for_ms: 10000, targets: ['1', '2'].map((hw_id) => ({ hw_id, status: 'ready', coordinated_takeoff_supported: true })) };
const preview = { runtime_mode: 'SITL', revision: 'revision', start_admissions: decisions, clusters: [{ cluster_id: '1', members: [
  { hw_id: '1', follow: '0', available: true, armed: false, frame: 'ned' },
  { hw_id: '2', follow: '1', available: true, armed: false, frame: 'ned', offset_x: 6 },
], partial_exclusion_hw_ids: [] }] };
beforeEach(() => {
  jest.clearAllMocks(); sessionStorage.clear();
  mockMonitors.length = 0;
  fetchGcsResource.mockImplementation((path) => Promise.resolve({ data: path.startsWith('/api/v1/commands/takeoff-readiness') ? takeoffReadiness : preview }));
  submitCommandWithLifecycleFeedback.mockResolvedValue({ command_id: 'test' });
});
async function mounted() {
  const result = render(<SwarmOperations />);
  await waitFor(() => expect(screen.getByRole('combobox', { name: 'Swarm formation' })).toHaveValue('1'));
  return result;
}
test('default actions use the whole cluster and Start sends only after confirmation', async () => {
  await mounted();
  expect(screen.getByRole('button', { name: 'Return 1,2' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Drone 1 · Drone 2')).toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ target_drone_ids: ['1', '2'], smart_swarm_start: expect.objectContaining({ cluster_id: '1', revision: 'revision' }) }), expect.anything()));
});
test('takeoff is separate, default 10 m and cancelled confirmation sends nothing', async () => {
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Takeoff' }));
  expect(screen.getByRole('spinbutton', { name: 'Takeoff height' })).toHaveValue(10);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /cancel/i }));
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Takeoff' }));
  await waitFor(() => expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeEnabled());
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /^Arm & take off/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(expect.objectContaining({ mission_type: 10, takeoff_altitude: 10, target_drone_ids: ['1', '2'] }), expect.anything()));
});
test('reviewed revision changes block dispatch', async () => {
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  fetchGcsResource.mockResolvedValue({ data: { ...preview, revision: 'changed' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm Start Swarm' }));
  await screen.findAllByText('Formation changed. Review the targets again.');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('finishing takeoff automatically enables confirmation but never sends Start', async () => {
  jest.useFakeTimers();
  try {
    fetchGcsResource.mockResolvedValue({ data: { ...preview, start_admissions: {
      ...decisions, '1': { hw_id: '1', status: 'waiting', message: 'Finishing takeoff' },
    } } });
    await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
    await screen.findByText('Finishing takeoff · Drone 1');
    expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeDisabled();
    fetchGcsResource.mockResolvedValue({ data: preview });
    await act(async () => { jest.advanceTimersByTime(1100); });
    expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled();
    expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  } finally { jest.useRealTimers(); }
});

test('stale or absent node evidence cannot enable Start', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...preview, start_admissions: {} } });
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await screen.findByText('Checking aircraft');
  expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeDisabled();
});

test('lost response preserves the same confirmed Start across remount', async () => {
  const instance = await mounted();
  fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  submitCommandWithLifecycleFeedback.mockRejectedValueOnce(Object.assign(new Error('Network Error'), { code: 'ERR_NETWORK', request: {} }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check command' })).toBeEnabled());
  const first = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  instance.unmount();
  fetchGcsResource.mockImplementation((url) => Promise.resolve({ data: url === '/api/v1/commands/lookup'
    ? { accepted_for_tracking: true, command_id: 'recovered' } : preview }));
  await mounted();
  fireEvent.click(screen.getByRole('button', { name: 'Check Start command' }));
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(first,
    expect.objectContaining({ command_id: 'recovered' }), expect.anything()));
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
});

test('lookup not found requires fresh confirmation and retains the original identity', async () => {
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  submitCommandWithLifecycleFeedback.mockRejectedValueOnce(Object.assign(new Error('Network Error'), { request: {} }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Check command' })).toBeEnabled());
  const first = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  fetchGcsResource.mockImplementation((url) => url === '/api/v1/commands/lookup'
    ? Promise.reject({ response: { status: 404 } }) : Promise.resolve({ data: preview }));
  fireEvent.click(screen.getByRole('button', { name: 'Check command' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2));
  expect(submitCommandWithLifecycleFeedback.mock.calls[1][0]).toEqual(first);
});

test('a slow Start can be dismissed to access recovery without cancelling or duplicating it', async () => {
  let finish;
  submitCommandWithLifecycleFeedback.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Other actions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Land here' }));
  expect(screen.getByRole('button', { name: 'Confirm Land here' })).toBeEnabled();
  await act(async () => { finish({ command_id: 'started' }); });
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Confirm Land here' })).toBeEnabled();
});

test('an ambiguous proxy error retains the Start identity and cannot leak across runtime modes', async () => {
  jest.useFakeTimers();
  try {
    await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
    submitCommandWithLifecycleFeedback.mockRejectedValueOnce({ response: { status: 502 } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check command' })).toBeEnabled());
    fetchGcsResource.mockResolvedValue({ data: { ...preview, runtime_mode: 'REAL' } });
    await act(async () => { jest.advanceTimersByTime(2100); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Check Start command' })).not.toBeInTheDocument();
    expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  } finally { jest.useRealTimers(); }
});
test('disappeared explicit cluster does not silently become another cluster', async () => {
  jest.useFakeTimers();
  try {
    await mounted();
    fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [{ cluster_id: '3', members: [{ hw_id: '3', follow: '0' }] }] } });
    await act(async () => { jest.advanceTimersByTime(2100); });
    expect(screen.getByRole('combobox', { name: 'Swarm formation' })).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Start Swarm' })).toBeDisabled();
  } finally { jest.useRealTimers(); }
});
test('takeoff never silently removes the airborne member of a reviewed cluster', async () => {
  const mixedPreview = { ...preview, clusters: [{ ...preview.clusters[0], members: [
    preview.clusters[0].members[0], { ...preview.clusters[0].members[1], armed: true, landed_state: 2, relative_altitude_m: -5 },
  ] }] };
  fetchGcsResource.mockImplementation((path) => Promise.resolve({ data: path.startsWith('/api/v1/commands/takeoff-readiness')
    ? { ...takeoffReadiness, targets: [takeoffReadiness.targets[0], { hw_id: '2', status: 'blocked', reason: 'Aircraft already airborne' }] }
    : mixedPreview }));
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Takeoff' }));
  expect(within(screen.getByRole('dialog')).getByText('Aircraft 1')).toBeInTheDocument();
  expect(within(screen.getByRole('dialog')).getByText('Aircraft 2')).toBeInTheDocument();
  await screen.findByText('Aircraft already airborne');
  expect(screen.getByRole('button', { name: /^Arm & take off/ })).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});
test('single-drone recovery requires the explicit advanced selector', async () => {
  await mounted();
  expect(screen.queryByRole('combobox', { name: 'Recovery targets' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Other actions' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Recovery targets' }), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Land here' }));
  expect(within(screen.getByRole('dialog')).getByText('Drone 2')).toBeInTheDocument();
});

test('partial engagement is never labelled full following and Hold remains cluster-scoped', async () => {
  mockMonitors.push({ missionType: 2, targetDrones: ['1'], isTerminal: false,
    updatedAtMs: Date.now(), swarmRuntime: { state: 'active', active_hw_ids: ['1'] } });
  await mounted();
  expect(screen.getByText('Partial · 1/2 engaged')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Other actions' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Recovery targets' }), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ mission_type: 102, target_drone_ids: ['1', '2'] }), expect.anything()));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('Hold is available without a remembered swarm session and bypasses a pending Start receipt', async () => {
  let finish;
  submitCommandWithLifecycleFeedback.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve; }));
  await mounted();
  fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2));
  expect(submitCommandWithLifecycleFeedback.mock.calls[1][0]).toEqual(expect.objectContaining({ mission_type: 102, target_drone_ids: ['1','2'] }));
  await act(async () => { finish({ command_id: 'late-start' }); });
  expect(screen.queryByRole('button', { name: 'Check Start command' })).not.toBeInTheDocument();
});

test('Hold fences a delayed readiness reply before Start can be posted', async () => {
  await mounted();
  fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Start Swarm' })).toBeEnabled());
  let finishReview;
  fetchGcsResource.mockImplementationOnce(() => new Promise((resolve) => { finishReview = resolve; }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm Start Swarm' }));
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  await act(async () => { finishReview({ data: preview }); });
  expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1);
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].mission_type).toBe(102);
});

test('an uncertain Hold retry reuses identity and does not claim Held from the receipt', async () => {
  await mounted();
  submitCommandWithLifecycleFeedback.mockRejectedValueOnce({ request: {} });
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await screen.findByRole('alert');
  const first = submitCommandWithLifecycleFeedback.mock.calls[0][0];
  expect(screen.getAllByText('Hold unconfirmed')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(2));
  expect(submitCommandWithLifecycleFeedback.mock.calls[1][0]).toEqual(first);
});

test('a terminal swarm cannot keep displaying Following after recovery', async () => {
  mockMonitors.push({ missionType: 2, targetDrones: ['1', '2'], isTerminal: true,
    updatedAtMs: Date.now(), swarmRuntime: { state: 'active', active_hw_ids: ['1', '2'] } });
  await mounted();
  expect(screen.queryByText('Following')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Start Swarm' })).toBeEnabled();
});

test('navigation links are in the overflow, not repeated on the main surface', async () => {
  await mounted();
  expect(screen.queryByRole('link', { name: 'Globe' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Other actions' }));
  expect(screen.getByRole('link', { name: 'Globe' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Design Swarm' })).toBeInTheDocument();
});

test('a newer mission removes an old Hold receipt presentation', async () => {
  const { rerender } = await mounted();
  fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalled());
  expect(screen.getAllByText('Hold unconfirmed')).toHaveLength(2);
  mockMonitors.push({ commandId: 'later-start', missionType: 2, targetDrones: ['1', '2'],
    updatedAtMs: Date.now() + 1000, isTerminal: false, swarmRuntime: { state: 'active', active_hw_ids: ['1', '2'] } });
  rerender(<SwarmOperations />);
  expect(screen.queryByText('Hold unconfirmed')).not.toBeInTheDocument();
  expect(screen.getByText('Following')).toBeInTheDocument();
});

test('native returning telemetry takes precedence over a Hold receipt', async () => {
  jest.useFakeTimers();
  try {
    await mounted();
    fireEvent.click(screen.getByRole('button', { name: 'Hold Swarm' }));
    await act(async () => {});
    fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [{ ...preview.clusters[0], members:
      preview.clusters[0].members.map((m) => ({ ...m, armed: true, landed_state: 2, flight_mode: 0x05040000 })) }] } });
    await act(async () => { jest.advanceTimersByTime(3000); });
    expect(screen.queryByText('Hold unconfirmed')).not.toBeInTheDocument();
    expect(screen.getAllByText(/Returning/).length).toBeGreaterThan(0);
  } finally { jest.useRealTimers(); }
});
