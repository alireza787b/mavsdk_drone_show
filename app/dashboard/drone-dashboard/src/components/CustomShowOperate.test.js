import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import CustomShowOperate from './CustomShowOperate';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { sendDroneCommand } from '../services/droneApiService';

jest.mock('../hooks/useGcsResourcePolling');
jest.mock('./SequentialReturnControl', () => props => <div data-testid="managed-return" data-targets={props.targetIds.join(',')} data-names={JSON.stringify(props.targetNames)}>Managed Return</div>);
jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {} }) }));
jest.mock('../services/droneApiService', () => ({ ...jest.requireActual('../services/droneApiService'), sendDroneCommand: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ trackCommandReceipt: jest.fn() }));

const fleet = ['1', '2', '3'].map(hw_id => ({ hw_id, name: `Aircraft ${hw_id}`, pos_id: hw_id,
  telemetry_fresh: true, ready_to_arm: true, armed: false }));
const info = () => ({ data: { exists: true, sha256: 'a'.repeat(64) }, receivedAt: performance.now() });
beforeEach(() => {
  sessionStorage.clear(); jest.clearAllMocks();
  useGcsResourcePolling.mockReturnValue({ data: { fleet, state: 'idle', timestamp: Date.now() }, receivedAt: performance.now() });
  sendDroneCommand.mockResolvedValue({ accepted_for_tracking: true, command_id: 'custom-1' });
});

test('launch reviews exact selected targets and uses native local-only type 3', async () => {
  render(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  fireEvent.click(screen.getAllByRole('checkbox')[2]);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Aircraft 3' } });
  expect(screen.getByText('2 selected · 2 hidden')).toBeInTheDocument();
  expect(screen.getByLabelText('Start timing')).toHaveValue('now');
  expect(screen.getByRole('option', { name: 'When ready' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Launch Custom CSV' }));
  expect(sendDroneCommand).not.toHaveBeenCalled();
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Aircraft 1 (H1) · Aircraft 2 (H2)')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Launch Custom CSV' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(1));
  expect(sendDroneCommand.mock.calls[0][0]).toMatchObject({ mission_type: 3, trigger_time: 0,
    target_drone_ids: ['1', '2'], auto_global_origin: false, use_global_setpoints: false,
    idempotency_key: expect.any(String) });
});

test('stale evidence disables launch but retains selection and unknown runtime cannot submit', () => {
  const snapshot = { data: { fleet, state: 'idle', timestamp: Date.now() }, receivedAt: performance.now() - 6000 };
  useGcsResourcePolling.mockReturnValue(snapshot);
  const view = render(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  expect(screen.getByRole('button', { name: 'Launch Custom CSV' })).toBeDisabled();
  expect(screen.getAllByRole('checkbox').every(input => input.checked)).toBe(true);
  useGcsResourcePolling.mockReturnValue({ ...snapshot, receivedAt: performance.now() });
  view.rerender(<CustomShowOperate infoState={info()} runtimeMode="unknown" />);
  expect(screen.getByRole('button', { name: 'Launch Custom CSV' })).toBeDisabled();
  expect(sendDroneCommand).not.toHaveBeenCalled();
});

test('recovery uses recorded mission targets, never the newly selected launch subset', async () => {
  useGcsResourcePolling.mockReturnValue({ receivedAt: performance.now(), data: { fleet, timestamp: Date.now(),
    state: 'active', phase: 'executing', command_id: 'running', operation_target_ids: ['2'],
    command: { target_drones: ['2'] } } });
  render(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
  fireEvent.click(screen.getByText('Other actions'));
  expect(screen.getByTestId('managed-return')).toHaveAttribute('data-targets', '2');
  expect(screen.getByTestId('managed-return')).toHaveAttribute('data-names', '["Aircraft 2 (H2)"]');
  fireEvent.click(screen.getByRole('button', { name: 'Cancel mission' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Aircraft 2 (H2)')).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel mission' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(1));
  expect(sendDroneCommand.mock.calls[0][0]).toMatchObject({ mission_type: 0, target_drone_ids: ['2'] });
});

test.each(['now', 'delay', 'absolute'])('metadata refresh preserves explicit %s timing and never submits', mode => {
  const view = render(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  fireEvent.change(screen.getByLabelText('Start timing'), { target: { value: mode } });
  if (mode === 'delay') fireEvent.change(screen.getByLabelText('Launch delay'), { target: { value: '47' } });
  if (mode === 'absolute') fireEvent.change(screen.getByLabelText('Execution time'), { target: { value: '2050-01-01T10:00:00' } });
  view.rerender(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  expect(screen.getByLabelText('Start timing')).toHaveValue(mode);
  if (mode === 'delay') expect(screen.getByLabelText('Launch delay')).toHaveValue(47);
  if (mode === 'absolute') expect(screen.getByLabelText('Execution time').value).toMatch(/^2050-01-01T10:00/);
  expect(sendDroneCommand).not.toHaveBeenCalled();
});

test('an open delayed review retains its exact reviewed time through metadata refresh', async () => {
  const view = render(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  fireEvent.change(screen.getByLabelText('Start timing'), { target: { value: 'delay' } });
  fireEvent.change(screen.getByLabelText('Launch delay'), { target: { value: '47' } });
  fireEvent.click(screen.getByRole('button', { name: 'Launch Custom CSV' }));
  const displayed = within(screen.getByRole('dialog')).getByText(/^Local frame/).textContent;
  view.rerender(<CustomShowOperate infoState={info()} runtimeMode="sitl" />);
  expect(within(screen.getByRole('dialog')).getByText(/^Local frame/).textContent).toBe(displayed);
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Launch Custom CSV' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(1));
  expect(sendDroneCommand.mock.calls[0][0].trigger_time).toBeGreaterThan(Math.floor(Date.now() / 1000));
});
