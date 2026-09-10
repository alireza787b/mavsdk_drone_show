import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import DashboardSmartSwarmStart from './DashboardSmartSwarmStart';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';

jest.mock('../services/gcsApiService', () => ({ fetchGcsResource: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ submitCommandWithLifecycleFeedback: jest.fn() }));
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {} }) }));

const preview = {
  revision: 'revision',
  clusters: [{ cluster_id: '1', members: [{ hw_id: '1' }, { hw_id: '2' }],
    available_hw_ids: ['1'], partial_exclusion_hw_ids: ['2'] }],
};

beforeEach(() => {
  jest.clearAllMocks();
  fetchGcsResource.mockResolvedValue({ data: preview });
  submitCommandWithLifecycleFeedback.mockResolvedValue({});
});

test('starts the full saved formation despite stale telemetry without silent exclusions', async () => {
  render(<DashboardSmartSwarmStart />);
  await screen.findByText(/Leader 1 · Drones 1, 2/);
  fireEvent.click(screen.getByRole('button', { name: /^Start Smart Swarm/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ target_drone_ids: ['1', '2'],
      smart_swarm_start: expect.objectContaining({ excluded_hw_ids: [] }) }), expect.anything(),
  ));
});

test('partial formation needs an explicit separate action and confirmation', async () => {
  const confirm = jest.spyOn(window, 'confirm').mockReturnValue(false);
  render(<DashboardSmartSwarmStart />);
  fireEvent.click(await screen.findByRole('button', { name: /Start without 2/ }));
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  confirm.mockReturnValue(true);
  fireEvent.click(screen.getByRole('button', { name: /Start without 2/ }));
  await waitFor(() => expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledWith(
    expect.objectContaining({ target_drone_ids: ['1'],
      smart_swarm_start: expect.objectContaining({ excluded_hw_ids: ['2'] }) }), expect.anything(),
  ));
  confirm.mockRestore();
});

test('shows fetch failure instead of an endless loading label', async () => {
  fetchGcsResource.mockRejectedValue(new Error('offline'));
  render(<DashboardSmartSwarmStart />);
  await screen.findByText('Formation unavailable; retrying…');
  expect(screen.getByRole('button', { name: /^Start Smart Swarm/ })).toBeDisabled();
});

test('does not silently choose the first of multiple clusters', async () => {
  fetchGcsResource.mockResolvedValue({ data: { ...preview, clusters: [...preview.clusters, { cluster_id: '3' }] } });
  render(<DashboardSmartSwarmStart />);
  await screen.findByText(/2 formations/);
  expect(screen.getByRole('button', { name: /^Start Smart Swarm/ })).toBeDisabled();
});
