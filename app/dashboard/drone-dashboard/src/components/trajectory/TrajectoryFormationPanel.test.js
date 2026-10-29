import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Panel from './TrajectoryFormationPanel';
import { putGcsResource, fetchGcsResource } from '../../services/gcsApiService';
jest.mock('../../services/gcsApiService', () => ({ putGcsResource: jest.fn(), fetchGcsResource: jest.fn() }));
const formation = { revision: 'r1', saved: true, assignments: [
  { hw_id: 1, follow: 0 }, { hw_id: 2, follow: 1, offset_x: 6, frame: 'ned' },
] };
beforeEach(() => { jest.clearAllMocks(); putGcsResource.mockResolvedValue({ data: { success: true } }); });
test('saves a mission revision, never changes live swarm configuration', async () => {
  const saved = jest.fn();
  render(<Panel formation={formation} onSaved={saved} />);
  fireEvent.click(screen.getByText('Formation', { exact: false, selector: 'summary' }));
  fireEvent.change(screen.getByLabelText('H2 offset_x'), { target: { value: '9' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save mission layout' }));
  await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(putGcsResource).toHaveBeenCalledWith('/api/v1/swarm-trajectories/formation',
    expect.objectContaining({ revision: 'r1', assignments: expect.arrayContaining([expect.objectContaining({ hw_id: 2, offset_x: 9 })]) }));
});
test('reset restores inputs without writing', () => {
  render(<Panel formation={formation} />);
  fireEvent.change(screen.getByLabelText('H2 offset_x'), { target: { value: '9' } });
  fireEvent.click(screen.getByRole('button', { name: 'Reset draft' }));
  expect(screen.getByLabelText('H2 offset_x')).toHaveValue(6);
  expect(putGcsResource).not.toHaveBeenCalled();
});

test('first-use default displays the Smart Swarm draft without saving anything', () => {
  render(<Panel formation={{ ...formation, saved: false }} />);
  expect(screen.getByText(/Smart Swarm draft/)).toBeInTheDocument();
  expect(screen.getByLabelText('H2 follows')).toHaveValue('1');
  expect(screen.getByLabelText('H2 offset_x')).toHaveValue(6);
  expect(screen.getByRole('button', { name: 'Save mission layout' })).toBeEnabled();
  expect(putGcsResource).not.toHaveBeenCalled();
});

test('copying Smart Swarm changes only the draft until mission save is confirmed', async () => {
  fetchGcsResource.mockResolvedValue({ data: { assignments: [
    { hw_id: 1, follow: 0 }, { hw_id: 2, follow: 1, offset_x: 12, frame: 'body' },
  ] } });
  render(<Panel formation={formation} />);
  fireEvent.click(screen.getByRole('button', { name: 'Copy Smart Swarm' }));
  await waitFor(() => expect(screen.getByLabelText('H2 offset_x')).toHaveValue(12));
  expect(screen.getByLabelText('H2 frame')).toHaveValue('body');
  expect(fetchGcsResource).toHaveBeenCalledWith('/api/v1/config/swarm');
  expect(putGcsResource).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Save mission layout' }));
  await waitFor(() => expect(putGcsResource).toHaveBeenCalledTimes(1));
  expect(putGcsResource).toHaveBeenCalledWith('/api/v1/swarm-trajectories/formation',
    expect.objectContaining({ revision: 'r1', assignments: expect.arrayContaining([
      expect.objectContaining({ hw_id: 2, offset_x: 12, frame: 'body' }),
    ]) }));
});
