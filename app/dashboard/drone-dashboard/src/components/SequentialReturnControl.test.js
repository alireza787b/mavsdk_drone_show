import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SequentialReturnControl from './SequentialReturnControl';
import { fetchGcsResource, postGcsResource } from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({
  fetchGcsResource: jest.fn(), postGcsResource: jest.fn(),
}));

const props = { targetIds: ['1', '2'], targetNames: ['Leader', 'Follower'] };
const waiting = {
  return_id: 'return-1', state: 'waiting', target_drone_ids: ['1', '2'],
  delay_sec: 10, next_hw_id: '2', commands: [{ hw_id: '1', command_id: 'rtl-1' }],
};

beforeEach(() => {
  jest.clearAllMocks();
  fetchGcsResource.mockResolvedValue({ data: null });
  postGcsResource.mockResolvedValue({ data: waiting });
});

test('defaults to 10 seconds, opening sends nothing, confirmation names order', async () => {
  render(<SequentialReturnControl {...props} />);
  expect(screen.getByLabelText('Seconds between RTL commands')).toHaveValue(10);
  fireEvent.click(screen.getByRole('button', { name: /managed return/i }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Leader · first')).toBeInTheDocument();
  expect(within(dialog).getByText('Follower · +10 s')).toBeInTheDocument();
  expect(postGcsResource).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Start return' }));
  await waitFor(() => expect(postGcsResource).toHaveBeenCalledWith(
    '/api/v1/swarm/runtime/sequential-return',
    expect.objectContaining({ target_drone_ids: ['1', '2'], delay_sec: 10 }),
  ));
  expect(await screen.findByText('1/2 RTL commands issued')).toBeInTheDocument();
});

test('editable interval and changed targets require a fresh review', async () => {
  const { rerender } = render(<SequentialReturnControl {...props} />);
  fireEvent.change(screen.getByLabelText('Seconds between RTL commands'), { target: { value: '20' } });
  fireEvent.click(screen.getByRole('button', { name: /managed return/i }));
  expect(within(screen.getByRole('dialog')).getByText('Follower · +20 s')).toBeInTheDocument();
  rerender(<SequentialReturnControl targetIds={['2']} targetNames={['Follower']} />);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start return' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Selection changed');
  expect(postGcsResource).not.toHaveBeenCalled();
});

test('refresh recovers the running queue and cancellation targets its identity', async () => {
  fetchGcsResource.mockResolvedValue({ data: waiting });
  render(<SequentialReturnControl {...props} />);
  const cancel = await screen.findByRole('button', { name: 'Cancel remaining' });
  expect(screen.getByRole('button', { name: /managed return/i })).toBeDisabled();
  fireEvent.click(cancel);
  await waitFor(() => expect(postGcsResource).toHaveBeenCalledWith(
    '/api/v1/swarm/runtime/sequential-return/return-1/cancel',
  ));
});

test('a lost response reuses the same request identity on retry', async () => {
  postGcsResource.mockRejectedValueOnce(new Error('lost response')).mockResolvedValueOnce({ data: waiting });
  render(<SequentialReturnControl {...props} />);
  for (let attempt = 0; attempt < 2; attempt += 1) {
    fireEvent.click(screen.getByRole('button', { name: /managed return/i }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start return' }));
    await waitFor(() => expect(postGcsResource).toHaveBeenCalledTimes(attempt + 1));
    if (attempt === 0) await screen.findByRole('alert');
  }
  expect(postGcsResource.mock.calls[0][1].idempotency_key).toBe(postGcsResource.mock.calls[1][1].idempotency_key);
});

test('invalid interval cannot dispatch', async () => {
  render(<SequentialReturnControl {...props} />);
  fireEvent.change(screen.getByLabelText('Seconds between RTL commands'), { target: { value: '0' } });
  expect(screen.getByRole('button', { name: /managed return/i })).toBeDisabled();
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalled());
});

test('compact Return reviews interval and rejects a changed formation', async () => {
  const { rerender } = render(<SequentialReturnControl {...props} compact contextKey="old" />);
  fireEvent.click(screen.getByRole('button', { name: 'Managed Return' }));
  expect(screen.getByRole('spinbutton', { name: 'Return interval' })).toHaveValue(10);
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Return interval' }), { target: { value: '0' } });
  fireEvent.click(screen.getByRole('button', { name: 'Start return' }));
  expect(postGcsResource).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('spinbutton', { name: 'Return interval' }), { target: { value: '10' } });
  rerender(<SequentialReturnControl {...props} compact contextKey="new" />);
  fireEvent.click(screen.getByRole('button', { name: 'Start return' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Selection changed');
  expect(postGcsResource).not.toHaveBeenCalled();
});

test('historical terminal return is not shown on initial poll', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...waiting, state: 'dispatched' } });
  render(<SequentialReturnControl {...props} compact />);
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalled());
  expect(screen.queryByText('RTL commands started')).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Managed Return' })).toBeEnabled();
});

test.each([null, {}])('empty queue response %p does not render a queue or crash', async (data) => {
  fetchGcsResource.mockResolvedValue({ data });
  render(<SequentialReturnControl {...props} compact />);
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalled());
  expect(screen.queryByRole('status')).not.toBeInTheDocument();
  if (data === null) expect(screen.getByRole('button', { name: 'Managed Return' })).toBeEnabled();
  else expect(await screen.findByRole('alert')).toHaveTextContent('Return status unavailable');
});

test('active queue stays visible across poll failure and selection change offers explicit details', async () => {
  jest.useFakeTimers();
  try {
    fetchGcsResource.mockResolvedValueOnce({ data: waiting }).mockRejectedValue(new Error('offline'));
    const { rerender } = render(<SequentialReturnControl {...props} compact />);
    await act(async () => {});
    expect(screen.getByRole('button', { name: 'Cancel remaining' })).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(1500); });
    expect(screen.getByRole('alert')).toHaveTextContent('Return status unavailable');
    expect(screen.getByRole('button', { name: 'Cancel remaining' })).toBeInTheDocument();
    rerender(<SequentialReturnControl targetIds={['3']} targetNames={['Other']} compact contextKey="other" />);
    expect(screen.queryByRole('button', { name: 'Cancel remaining' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Return active for other aircraft/ }));
    expect(screen.getByRole('button', { name: 'Cancel remaining' })).toBeInTheDocument();
  } finally { jest.useRealTimers(); }
});

test('new dispatched notice expires after 10 seconds, failures need acknowledgement only', async () => {
  jest.useFakeTimers();
  try {
    fetchGcsResource.mockResolvedValue({ data: waiting });
    render(<SequentialReturnControl {...props} compact />);
    await act(async () => {});
    fetchGcsResource.mockResolvedValue({ data: { ...waiting, state: 'dispatched' } });
    await act(async () => { jest.advanceTimersByTime(1500); });
    expect(screen.getByText('RTL commands started')).toBeInTheDocument();
    await act(async () => { jest.advanceTimersByTime(10000); });
    expect(screen.queryByText('RTL commands started')).not.toBeInTheDocument();
    fetchGcsResource.mockResolvedValue({ data: { ...waiting, state: 'failed', message: 'Drone 2 rejected RTL' } });
    await act(async () => { jest.advanceTimersByTime(1500); });
    expect(screen.getByText('Drone 2 rejected RTL')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notice' }));
    expect(screen.queryByText('Drone 2 rejected RTL')).not.toBeInTheDocument();
    expect(postGcsResource).not.toHaveBeenCalled();
  } finally { jest.useRealTimers(); }
});
