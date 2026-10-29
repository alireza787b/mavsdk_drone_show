import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Workspace from './SwarmTrajectoryWorkspace';
import useGcsResourcePolling from '../hooks/useGcsResourcePolling';
import { sendDroneCommand } from '../services/droneApiService';

jest.mock('../hooks/useGcsResourcePolling');
jest.mock('../services/droneApiService', () => ({ sendDroneCommand: jest.fn(), createCommandIdempotencyKey: () => 'request-123' }));
jest.mock('./SwarmTrajectory', () => () => <div>Route editor</div>);
jest.mock('../components/SequentialReturnControl', () => () => <div>Managed Return</div>);
let workspace, operation;
function mount(path='/swarm-trajectory') {
  return render(<MemoryRouter initialEntries={[path]}><Workspace /></MemoryRouter>);
}
beforeEach(() => {
  sessionStorage.clear(); jest.clearAllMocks();
  workspace = { simulation_mode: true, launch_identity: { revision: 'r1', files: { '1': 'a'.repeat(64), '2': 'b'.repeat(64) } },
    status: { clusters: [{ leader_id: 1, follower_ids: [2] }], package_stats: { mission_clock_s: 60 } },
    validation: { ready: true, blockers: [] }, preview: { drones: [] } };
  operation = { state: 'idle', phase: 'idle', timestamp: Date.now(), fleet: [1,2].map((id) => ({
    hw_id: String(id), name: `Drone ${id}`, telemetry_fresh: true, ready_to_arm: true,
    armed: false, landed_state: 1, state: 'Hold', readiness_summary: 'Ready',
  })) };
  useGcsResourcePolling.mockImplementation((route) => ({ data: route.endsWith('workspace') ? workspace : operation,
    loading: false, error: null, receivedAt: performance.now() }));
  sendDroneCommand.mockResolvedValue({ accepted_for_tracking: true, command_id: 'cmd-1' });
});

test('defaults to whole first cluster, requires review and binds reviewed hashes', async () => {
  mount();
  expect(sendDroneCommand).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Start mission' }));
  const dialog = screen.getByRole('dialog');
  expect(within(dialog).getByText('Drone 1 · Drone 2')).toBeInTheDocument();
  expect(within(dialog).getByText(/Launch from the ground in/)).toBeInTheDocument();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Start mission' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(1));
  expect(sendDroneCommand.mock.calls[0][0]).toMatchObject({ mission_type: 4, target_drone_ids: ['1','2'],
    swarm_trajectory: workspace.launch_identity });
});

test('missing validation and stale aircraft do not enable start', () => {
  workspace.validation = null;
  operation.fleet[1].telemetry_fresh = false;
  mount();
  expect(screen.getByRole('button', { name: 'Start mission' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Immediate Return' })).toBeEnabled();
});

test('unconfirmed start survives refresh and recovers only the same request', async () => {
  sendDroneCommand.mockRejectedValueOnce(new Error('Network lost'));
  const first = mount();
  fireEvent.click(screen.getByRole('button', { name: 'Start mission' }));
  fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start mission' }));
  await screen.findByText('Start receipt unconfirmed');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Recover receipt' })).toBeEnabled());
  const original = sendDroneCommand.mock.calls[0][0];
  first.unmount();
  mount();
  expect(sendDroneCommand).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Recover receipt' }));
  await waitFor(() => expect(sendDroneCommand).toHaveBeenCalledTimes(2));
  expect(sendDroneCommand.mock.calls[1][0]).toEqual(original);
});

test('Plan does not dispatch and Hold describes terminal route behavior', () => {
  const first = mount('/swarm-trajectory?tab=plan');
  expect(screen.getByText('Route editor')).toBeInTheDocument();
  expect(sendDroneCommand).not.toHaveBeenCalled();
  first.unmount(); mount();
  fireEvent.click(screen.getByRole('button', { name: 'Hold' }));
  expect(within(screen.getByRole('dialog')).getByText(/ends the current route/)).toBeInTheDocument();
});
