import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SwarmOperations from './SwarmOperations';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
jest.mock('../services/gcsApiService', () => ({ fetchGcsResource: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn() }));
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {}, commandMonitors: [] }) }));
jest.mock('./SequentialReturnControl', () => ({ targetIds, compact }) => <button>Return {compact ? targetIds.join(',') : 'legacy'}</button>);
const preview = { runtime_mode: 'SITL', revision: 'revision', clusters: [{ cluster_id: '1', members: [
  { hw_id: '1', follow: '0', available: true, armed: false, frame: 'ned' },
  { hw_id: '2', follow: '1', available: true, armed: false, frame: 'ned', offset_x: 6 },
], partial_exclusion_hw_ids: [] }] };
beforeEach(() => {
  jest.clearAllMocks(); sessionStorage.clear();
  fetchGcsResource.mockResolvedValue({ data: preview });
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
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm Takeoff' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(expect.objectContaining({ mission_type: 10, takeoff_altitude: 10, target_drone_ids: ['1', '2'] }), expect.anything()));
});
test('reviewed revision changes block dispatch', async () => {
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Start Swarm' }));
  fetchGcsResource.mockResolvedValue({ data: { ...preview, revision: 'changed' } });
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm Start Swarm' }));
  await screen.findAllByText('Formation changed. Review the targets again.');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
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
test('takeoff in mixed state explicitly targets only the grounded drone', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [{ ...preview.clusters[0], members: [
    preview.clusters[0].members[0], { ...preview.clusters[0].members[1], armed: true, relative_altitude_m: 5 },
  ] }] } });
  await mounted(); fireEvent.click(screen.getByRole('button', { name: 'Takeoff' }));
  expect(within(screen.getByRole('dialog')).getByText('Drone 1')).toBeInTheDocument();
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm Takeoff' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(expect.objectContaining({ target_drone_ids: ['1'] }), expect.anything()));
});
test('single-drone recovery requires the explicit advanced selector', async () => {
  await mounted();
  expect(screen.queryByRole('combobox', { name: 'Recovery targets' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Other actions' }));
  fireEvent.change(screen.getByRole('combobox', { name: 'Recovery targets' }), { target: { value: '2' } });
  fireEvent.click(screen.getByRole('button', { name: 'Land here' }));
  expect(within(screen.getByRole('dialog')).getByText('Drone 2')).toBeInTheDocument();
});
