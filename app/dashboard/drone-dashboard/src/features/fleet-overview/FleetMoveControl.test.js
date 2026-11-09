import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import FleetMoveControl from './FleetMoveControl';
import { DRONE_ACTION_TYPES } from '../../constants/droneConstants';
import { fetchGcsResource, getPrecisionMovePolicyResponse } from '../../services/gcsApiService';
import { sendDroneCommand } from '../../services/droneApiService';
import { trackCommandReceipt } from '../../utilities/commandLifecycleFeedback';

jest.mock('../../services/gcsApiService', () => ({ ...jest.requireActual('../../services/gcsApiService'),
  fetchGcsResource: jest.fn(), getPrecisionMovePolicyResponse: jest.fn() }));
jest.mock('../../services/droneApiService', () => ({ ...jest.requireActual('../../services/droneApiService'), sendDroneCommand: jest.fn() }));
jest.mock('../../utilities/commandLifecycleFeedback', () => ({ trackCommandReceipt: jest.fn() }));
const mockMonitors = [];
jest.mock('../../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandMonitors: mockMonitors, commandLifecycleCallbacks: {} }) }));
const receipt = { accepted_for_tracking: true, command_id: 'move-1' };
const forward = () => screen.getByRole('button', { name: /^forward/ });
function setup(overrides = {}) {
  const props = { targetId: '7', targetLabel: 'Scout', runtimeMode: 'sitl', operatorId: 'pilot', onClose: jest.fn(), ...overrides };
  return { ...render(<FleetMoveControl {...props} />), props };
}
beforeEach(() => {
  jest.restoreAllMocks(); jest.clearAllMocks(); sessionStorage.clear(); mockMonitors.length = 0;
  getPrecisionMovePolicyResponse.mockResolvedValue({ data: {} });
  sendDroneCommand.mockResolvedValue(receipt);
});

test('Planned stages without a POST, then dispatches once and closes on acceptance', async () => {
  const { props } = setup();
  fireEvent.click(forward());
  expect(sendDroneCommand).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch Planned Move' }));
  await waitFor(() => expect(props.onClose).toHaveBeenCalledTimes(1));
  expect(sendDroneCommand.mock.calls[0][0]).toMatchObject({ mission_type: DRONE_ACTION_TYPES.PRECISION_MOVE,
    target_drone_ids: ['7'], trigger_time: 0, precision_move: { frame: 'body', translation_m: { forward: 1, right: 0, up: 0 } } });
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
});

test('Live Jog sends each tap immediately, stays open and Hold stays immediate', async () => {
  const { props } = setup();
  fireEvent.click(screen.getByRole('button', { name: /Live Jog Each tap sends now/ }));
  fireEvent.click(forward());
  await waitFor(() => expect(forward()).toBeEnabled());
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
  expect(props.onClose).not.toHaveBeenCalled();
  expect(screen.getByText('Live jog armed')).toBeInTheDocument();
  fireEvent.click(forward());
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.getByRole('button', { name: 'Dispatch Hold' })).toBeEnabled());
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch Hold' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(3));
  expect(sendDroneCommand.mock.calls[2][0]).toMatchObject({ mission_type: DRONE_ACTION_TYPES.HOLD, target_drone_ids: ['7'], trigger_time: 0 });
  expect(props.onClose).not.toHaveBeenCalled();
  expect(sendDroneCommand.mock.calls[0][0].idempotency_key).not.toBe(sendDroneCommand.mock.calls[1][0].idempotency_key);
});

test('uncertain movement survives remount and only GET recovery is offered; Hold remains available', async () => {
  sendDroneCommand.mockRejectedValueOnce(Object.assign(new Error('Network error'), { code: 'ERR_NETWORK' }));
  const first = setup();
  fireEvent.click(screen.getByRole('button', { name: /Live Jog Each tap sends now/ }));
  fireEvent.click(forward());
  await screen.findByRole('button', { name: 'Check receipt' });
  const sent = sendDroneCommand.mock.calls[0][0];
  first.unmount(); setup();
  expect(screen.getByRole('button', { name: 'Hold now' })).toBeEnabled();
  fetchGcsResource.mockResolvedValue({ data: receipt });
  fireEvent.click(screen.getByRole('button', { name: 'Check receipt' }));
  await waitFor(() => expect(fetchGcsResource).toHaveBeenCalledWith('/api/v1/commands/lookup', { params: { idempotency_key: sent.idempotency_key } }));
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(trackCommandReceipt).toHaveBeenCalledWith(sent, receipt, {}));
});

test('changing target while open cannot retarget or close a newer scope after a late result', async () => {
  let finish;
  sendDroneCommand.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const { props, rerender } = setup();
  fireEvent.click(forward());
  fireEvent.click(screen.getByRole('button', { name: 'Dispatch Planned Move' }));
  rerender(<FleetMoveControl {...props} targetId="9" />);
  await act(async () => finish(receipt));
  expect(props.onClose).not.toHaveBeenCalled();
  expect(sendDroneCommand.mock.calls[0][0].target_drone_ids).toEqual(['7']);
  expect(screen.getByRole('button', { name: 'Back to move' })).toBeDisabled();
});
