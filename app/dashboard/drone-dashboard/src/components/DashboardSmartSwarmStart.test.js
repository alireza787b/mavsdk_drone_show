import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import DashboardSmartSwarmStart from './DashboardSmartSwarmStart';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';

jest.mock('../services/gcsApiService', () => ({ fetchGcsResource: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn() }));
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {} }) }));

const preview = {
  revision: 'revision',
  clusters: [{ cluster_id: '1', members: [
    { hw_id: '1', follow: '0', available: true, armed: false },
    { hw_id: '2', follow: '1', frame: 'ned', offset_x: 6, offset_z: 0, available: false, armed: false },
  ], available_hw_ids: ['1'], partial_exclusion_hw_ids: ['2'] }],
};

beforeEach(() => {
  jest.clearAllMocks();
  fetchGcsResource.mockResolvedValue({ data: preview });
  submitCommandWithLifecycleFeedback.mockResolvedValue({});
});

test('clicking the mission card opens review and never sends a command', async () => {
  const onReview = jest.fn();
  render(<DashboardSmartSwarmStart onReview={onReview} />);
  await screen.findByText(/Leader 1 · Drones 1, 2/);
  fireEvent.click(screen.getByRole('button', { name: /^Smart Swarm/ }));
  expect(onReview).toHaveBeenCalledTimes(1);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

test('review shows the plan and status; Start only opens confirmation', async () => {
  render(<DashboardSmartSwarmStart review onBack={jest.fn()} />);
  await screen.findByText('Follow Drone 1 · 6 m north · same height');
  expect(screen.getByText('Disarmed')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Start Smart Swarm' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText(/Drone 2: Follow Drone 1 · 6 m north/)).toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm start' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ target_drone_ids: ['1', '2'],
      smart_swarm_start: expect.objectContaining({ excluded_hw_ids: [] }) }), expect.anything(),
  ));
});

test('backing out of review or confirmation sends nothing', async () => {
  const onBack = jest.fn();
  render(<DashboardSmartSwarmStart review onBack={onBack} />);
  await screen.findByText(/Follow Drone 1/);
  fireEvent.click(screen.getByRole('button', { name: 'Back' }));
  expect(onBack).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Start Smart Swarm' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Back' }));
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});

test('partial formation is explicitly labelled and only sends after confirmation', async () => {
  render(<DashboardSmartSwarmStart review />);
  fireEvent.click(await screen.findByRole('button', { name: /Start without 2/ }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Partial formation · excludes Drone 2.')).toBeInTheDocument();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm start' }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ target_drone_ids: ['1'],
      smart_swarm_start: expect.objectContaining({ excluded_hw_ids: ['2'] }) }), expect.anything(),
  ));
});

test('shows fetch failure instead of an endless loading label', async () => {
  fetchGcsResource.mockRejectedValue(new Error('offline'));
  render(<DashboardSmartSwarmStart review />);
  await screen.findByText('Formation unavailable; retrying…');
  expect(screen.getByRole('button', { name: 'Start Smart Swarm' })).toBeDisabled();
});

test('does not silently choose the first of multiple clusters', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [...preview.clusters, { cluster_id: '3' }] } });
  render(<DashboardSmartSwarmStart review />);
  await screen.findByText('Choose a formation in Swarm Design');
  expect(screen.getByRole('button', { name: 'Start Smart Swarm' })).toBeDisabled();
});

test('does not submit a confirmation after the reviewed formation changed', async () => {
  jest.useFakeTimers();
  try {
    render(<DashboardSmartSwarmStart review />);
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: 'Start Smart Swarm' }));
    fetchGcsResource.mockResolvedValue({ data: { ...preview, revision: 'changed' } });
    await act(async () => { jest.advanceTimersByTime(2100); });
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Confirm start' }));
    expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  } finally {
    jest.useRealTimers();
  }
});

test('offset description matches runtime: positive vertical offset is above the leader', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [{ ...preview.clusters[0], members: [
    preview.clusters[0].members[0], { ...preview.clusters[0].members[1], frame: 'body', offset_x: -6, offset_z: 2 },
  ] }] } });
  render(<DashboardSmartSwarmStart review />);
  await screen.findByText('Follow Drone 1 · 6 m behind · 2 m above');
});
