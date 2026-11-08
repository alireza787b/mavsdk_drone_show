import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SwarmCaptureDialog from './SwarmCaptureDialog';
import { previewSwarmCaptureResponse } from '../services/gcsApiService';

jest.mock('../services/gcsApiService', () => ({ previewSwarmCaptureResponse: jest.fn() }));
jest.mock('../hooks/useSwarmCaptureLiveView', () => () => ({ positions: [], freshCount: 0, loading: false }));
const assignments = [
  { hw_id: '1', follow: '0', frame: 'ned', offset_x: 0, offset_y: 0, offset_z: 0 },
  { hw_id: '2', follow: '1', frame: 'ned', offset_x: 5, offset_y: 2, offset_z: 2 },
  { hw_id: '3', follow: '0', frame: 'body', offset_x: 0, offset_y: 0, offset_z: 0 },
  { hw_id: '4', follow: '3', frame: 'body', offset_x: 5, offset_y: 2, offset_z: 2 },
];
const clusters = [{ clusterId: '1', hwIds: ['1', '2'], frame: 'ned' }, { clusterId: '3', hwIds: ['3', '4'], frame: 'body' }];
const request = { assignments, revision: 'reviewed', clusters: [clusters[0]], clusterId: '1' };
const configData = assignments.map(entry => ({ hw_id: entry.hw_id, callsign: `Aircraft ${entry.hw_id}` }));
const snapshot = (ids = ['1', '2']) => ({ capture_id: 'capture', captured_at_ms: Date.now(), revision: 'reviewed',
  flight_state: 'airborne', recommended_height_mode: 'current',
  saved: false, commands_sent: false, current_heights_available: true,
  observations: Object.fromEntries(ids.map((id, index) => [id, {
    north_m: index * 5, east_m: index * 2, planned_up_m: index * 2, current_up_m: index * .7, heading_deg: 90,
  }])), reference: { latitude: 35, longitude: 51, altitude_msl_m: 120 } });
beforeEach(() => { jest.clearAllMocks(); previewSwarmCaptureResponse.mockImplementation(async p => ({ data: snapshot(p.cluster_id === '3' ? ['3', '4'] : ['1', '2']) })); });
const open = (props = {}) => {
  const onUse = jest.fn(), onClose = jest.fn();
  render(<SwarmCaptureDialog request={request} configData={configData} onUse={onUse} onClose={onClose} {...props} />);
  return { onUse, onClose };
};
const ready = async () => waitFor(() => expect(screen.getByRole('button', { name: 'Use capture' })).toBeEnabled());

test('one cluster opens in 3D with Current airborne heights and collapsed adjustments', async () => {
  const { onUse } = open(); await ready();
  expect(screen.queryByRole('combobox', { name: 'Capture formation' })).not.toBeInTheDocument();
  expect(screen.getByRole('group', { name: 'Capture 3D view' })).toBeInTheDocument();
  expect(screen.getByText('Adjust formation').closest('details')).not.toHaveAttribute('open');
  expect(screen.getByRole('radio', { name: 'Current', exact: true })).toBeChecked();
  fireEvent.click(screen.getByText('Adjust formation'));
  expect(screen.getByRole('radio', { name: 'Geographic' })).toBeChecked();
  fireEvent.click(screen.getByRole('radio', { name: 'Current', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Use capture' }));
  expect(onUse.mock.calls[0][0].assignments[1].offset_z).toBe(.7);
  expect(onUse.mock.calls[0][0].assignments.slice(2)).toEqual(assignments.slice(2));
  expect(previewSwarmCaptureResponse).toHaveBeenCalledTimes(1);
});

test('Current is unavailable without native airborne height evidence', async () => {
  previewSwarmCaptureResponse.mockResolvedValue({ data: { ...snapshot(), current_heights_available: false,
    flight_state: 'grounded', recommended_height_mode: 'level',
    current_heights_reason: 'All aircraft must be settled airborne.' } });
  open(); await ready();
  expect(screen.getByRole('radio', { name: 'Current', exact: true })).toBeDisabled();
  expect(screen.getByRole('radio', { name: 'Same height' })).toBeChecked();
  expect(screen.getByRole('radio', { name: 'Keep plan' })).toBeEnabled();
});

test('failed refresh retains the drawing, explicitly invalidates Use and leaves the parent draft untouched', async () => {
  const { onUse } = open(); await ready();
  previewSwarmCaptureResponse.mockRejectedValueOnce(new Error('Aircraft link delayed. Refresh after it returns.'));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
  await screen.findByText('Aircraft link delayed. Refresh after it returns.');
  expect(screen.getByRole('group', { name: 'Capture 3D view' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Use capture' })).toBeDisabled();
  expect(screen.getByText('Refresh needed')).toBeInTheDocument();
  expect(onUse).not.toHaveBeenCalled();
});

test('mixed or unavailable recommendation needs an explicit height choice, not a silent default', async () => {
  previewSwarmCaptureResponse.mockResolvedValue({ data: { ...snapshot(), flight_state: 'mixed', recommended_height_mode: null } });
  open();
  await screen.findByText('Choose height before continuing.');
  expect(screen.getByRole('button', { name: 'Use capture' })).toBeDisabled();
  fireEvent.click(screen.getByRole('radio', { name: 'Keep plan' }));
  await ready();
});

test('a deliberate height choice survives Refresh; automatic default can adapt before a deliberate choice', async () => {
  const result = open(); await ready();
  previewSwarmCaptureResponse.mockResolvedValue({ data: { ...snapshot(), flight_state: 'grounded',
    current_heights_available: false, recommended_height_mode: 'level' } });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); await ready();
  expect(screen.getByRole('radio', { name: 'Same height' })).toBeChecked();
  fireEvent.click(screen.getByRole('radio', { name: 'Keep plan' }));
  previewSwarmCaptureResponse.mockResolvedValue({ data: snapshot() });
  fireEvent.click(screen.getByRole('button', { name: 'Refresh' })); await ready();
  expect(screen.getByRole('radio', { name: 'Keep plan' })).toBeChecked();
  expect(result.onUse).not.toHaveBeenCalled();
});

test('All clusters asks for scope; changing it cannot accept an old in-flight response', async () => {
  let finishOld;
  previewSwarmCaptureResponse.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }));
  const { onUse } = open({ request: { ...request, clusters, clusterId: null } });
  expect(previewSwarmCaptureResponse).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole('combobox', { name: 'Capture formation' }), { target: { value: '1' } });
  await waitFor(() => expect(previewSwarmCaptureResponse).toHaveBeenCalledTimes(1));
  fireEvent.change(screen.getByRole('combobox', { name: 'Capture formation' }), { target: { value: '3' } });
  await ready();
  await act(async () => finishOld({ data: snapshot() }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByRole('combobox', { name: 'Capture formation' })).toHaveValue('3');
  fireEvent.click(within(dialog).getByRole('button', { name: 'Use capture' }));
  expect(onUse.mock.calls[0][0].hwIds).toEqual(['3', '4']);
  expect(onUse.mock.calls[0][0].assignments.slice(0, 2)).toEqual(assignments.slice(0, 2));
});
