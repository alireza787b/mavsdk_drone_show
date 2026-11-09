import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Overview from './Overview';
import TakeoffDialog from '../components/TakeoffDialog';
import useFleetResources from '../features/fleet-overview/useFleetResources';
import { getTargetSelectionStorageScope } from '../features/fleet-overview/targetSelection';
import { getBackendURL } from '../config/apiConfig';
import { DRONE_ACTION_TYPES } from '../constants/droneConstants';
import { FleetAlertsProvider } from '../features/fleet-overview/FleetAlertsContext';
import { buildActionStorageKey } from '../features/fleet-overview/ActionReview';

jest.mock('../features/fleet-overview/useFleetResources', () => ({ __esModule: true, default: jest.fn() }));
jest.mock('../config/apiConfig', () => ({ ...jest.requireActual('../config/apiConfig'), getBackendURL: () => 'https://gcs.example.test' }));
jest.mock('../components/TakeoffDialog', () => {
  return { __esModule: true, default: jest.fn() };
});
jest.mock('../components/DroneActions', () => () => null);
jest.mock('../components/PrecisionMoveDialog', () => () => null);
jest.mock('../features/fleet-overview/ActionReview', () => ({ ...jest.requireActual('../features/fleet-overview/ActionReview'), __esModule: true,
  default: ({ intent }) => <output aria-label="General action review">{JSON.stringify(intent)}</output> }));

const NOW = 1780000000000;
const live = (id, extra = {}) => ({ hw_id: id, pos_id: id, update_time: NOW / 1000,
  telemetry_available: true, is_armed: false, landed_state: 1, battery_remaining_percent: 80,
  battery_voltage: 16.1, position_alt: 20, ...extra });
const resources = (drones = [live('1'), live('2'), { hw_id: '3', pos_id: '3' }], configuredIds = drones.map((item) => item.hw_id)) => ({
  drones, configuredIds, nowMs: NOW, loading: false, swarm: [],
  config: { response: { data: configuredIds.map((hw_id) => ({ hw_id })) }, error: null, loading: false },
  telemetry: { response: { data: {} }, error: null, loading: false }, boot: { response: null, error: null },
});
const tree = (runtimeMode = 'sitl', operatorId = '') => <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
  <FleetAlertsProvider key={`${runtimeMode}:${operatorId}`}><Overview runtimeMode={runtimeMode} operatorId={operatorId} /></FleetAlertsProvider>
</MemoryRouter>;
const target = (id) => screen.getByRole('checkbox', { name: `Select Aircraft ${id} · H${id}` });
const inspect = (id) => screen.getByRole('button', { name: `Inspect Aircraft ${id} · H${id}` });
const actionRail = () => screen.getByLabelText('Selected aircraft actions');
const selected = (count) => expect(actionRail().querySelector('strong')).toHaveTextContent(new RegExp(`^${count} selected$`));
const save = (ids, runtimeMode = 'sitl', operatorId = '') => {
  const scope = getTargetSelectionStorageScope({ deploymentId: getBackendURL(), runtimeMode, operatorId, sessionId: 'browser-session' });
  window[`${scope.storage}Storage`].setItem(scope.key, JSON.stringify({ version: 1, ids }));
};

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  useFleetResources.mockReturnValue(resources());
  // CRA resets mock implementations before each test, not only their call history.
  TakeoffDialog.mockImplementation(({ open, command, onClose }) => open
    ? <section aria-label="Takeoff review"><output data-testid="takeoff-command">{JSON.stringify(command)}</output>
      <button type="button" onClick={onClose}>Close takeoff review</button></section> : null);
});

describe('Overview explicit aircraft workflow', () => {
  test('an unrelated uncertain receipt never disables or overwrites a new recovery action', () => {
    const prefix = `mds:fleet-action:v1:${getBackendURL()}:sitl:session`;
    const previous = { mission_type: DRONE_ACTION_TYPES.TEST_LED, trigger_time: 0,
      target_drone_ids: ['1'], idempotency_key: 'uncertain-led' };
    const key = buildActionStorageKey(prefix, previous);
    sessionStorage.setItem(key, JSON.stringify(previous));
    render(tree());
    const returning = within(actionRail()).getByRole('button', { name: 'Return' });
    expect(returning).toBeEnabled();
    fireEvent.click(returning);
    expect(JSON.parse(screen.getByLabelText('General action review').textContent)).toMatchObject({
      mission_type: DRONE_ACTION_TYPES.RETURN_RTL, target_drone_ids: ['1', '2', '3'],
    });
    expect(JSON.parse(sessionStorage.getItem(key))).toEqual(previous);
  });

  test.each(['sitl', 'real'])('initializes all configured %s aircraft, including unavailable ones', (mode) => {
    render(tree(mode));
    ['1', '2', '3'].forEach((id) => expect(target(id)).toBeChecked());
    selected(3);
    expect(screen.getByText(mode.toUpperCase())).toBeInTheDocument();
    expect(inspect('3')).toHaveTextContent('Never seen');
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' })).toBeEnabled();
  });

  test.each([[[]], [['2']]])('restores saved exact selection %j, including deliberately empty', (ids) => {
    save(ids);
    render(tree());
    ['1', '2', '3'].forEach((id) => expect(target(id).checked).toBe(ids.includes(id)));
    selected(ids.length);
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' }).disabled).toBe(ids.length === 0);
  });

  test('unknown remembered IDs remain reviewable and block actions until explicit reconciliation', () => {
    save(['2', 'removed']);
    render(tree());
    expect(screen.getByRole('alert')).toHaveTextContent('Unknown selected aircraft: removed');
    selected(2);
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Remove missing targets' }));
    selected(1);
    expect(target('2')).toBeChecked();
    expect(target('1')).not.toBeChecked();
  });

  test('filter, inspect and list view do not change command membership', () => {
    render(tree());
    fireEvent.click(target('2'));
    selected(2);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find aircraft' }), { target: { value: 'hw 1' } });
    expect(screen.getAllByRole('checkbox')).toHaveLength(1);
    expect(screen.getByText('2 selected · 1 hidden')).toBeInTheDocument();
    fireEvent.click(inspect('1'));
    expect(screen.getByRole('dialog', { name: 'Aircraft 1' })).toBeInTheDocument();
    selected(2);
    fireEvent.click(screen.getByRole('button', { name: 'Close aircraft details' }));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'List', exact: true }));
    expect(target('1')).toBeChecked();
    expect(target('2')).not.toBeChecked();
    expect(target('3')).toBeChecked();
    selected(2);
  });

  test('telemetry loss remains visible and selected instead of disappearing from the board', () => {
    const snapshot = resources([live('1', { is_armed: true, landed_state: 2 })]);
    useFleetResources.mockReturnValue(snapshot);
    const view = render(tree());
    useFleetResources.mockReturnValue({ ...snapshot, nowMs: NOW + 65000, telemetry: { ...snapshot.telemetry, error: new Error('network') } });
    view.rerender(tree());
    expect(target('1')).toBeChecked();
    expect(inspect('1')).toHaveTextContent('Flight state unknown');
    expect(inspect('1')).toHaveTextContent('Offline');
    expect(screen.getByRole('alert')).toHaveTextContent('measurements are aging');
    selected(1);
  });

  test('new configured aircraft do not join an initialized target set', () => {
    useFleetResources.mockReturnValue(resources([live('1')]));
    const view = render(tree());
    useFleetResources.mockReturnValue(resources([live('1'), live('2')]));
    view.rerender(tree());
    expect(target('1')).toBeChecked();
    expect(target('2')).not.toBeChecked();
    selected(1);
    fireEvent.click(screen.getByRole('button', { name: 'All', exact: true }));
    expect(target('2')).toBeChecked();
    selected(2);
  });

  test('takeoff receives an exact frozen ID snapshot, not All or the visible subset', () => {
    save(['1', '3']);
    render(tree());
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'hw 1' } });
    fireEvent.click(within(actionRail()).getByRole('button', { name: 'Takeoff' }));
    const command = JSON.parse(screen.getByTestId('takeoff-command').textContent);
    expect(command).toMatchObject({ mission_type: DRONE_ACTION_TYPES.TAKE_OFF, target_drone_ids: ['1', '3'], takeoff_altitude: 10 });
    expect(command).not.toHaveProperty('target_scope');
    fireEvent.click(screen.getByRole('button', { name: 'None', exact: true }));
    expect(JSON.parse(screen.getByTestId('takeoff-command').textContent)).toEqual(command);
    const props = TakeoffDialog.mock.calls[TakeoffDialog.mock.calls.length - 1][0];
    expect(props.aircraft).toHaveLength(3);
    expect(props.command.target_drone_ids).toEqual(['1', '3']);
  });

  test('inspector resolves the current aircraft by ID and updates without re-opening', () => {
    useFleetResources.mockReturnValue(resources([live('1')]));
    const view = render(tree());
    fireEvent.click(inspect('1'));
    expect(within(screen.getByRole('dialog')).getByText('20.0 m MSL')).toBeInTheDocument();
    useFleetResources.mockReturnValue(resources([live('1', { position_alt: 45, is_armed: true, landed_state: 2 })]));
    view.rerender(tree());
    const dialog = screen.getByRole('dialog', { name: 'Aircraft 1' });
    expect(within(dialog).getByText('45.0 m MSL')).toBeInTheDocument();
    expect(within(dialog).getByText('Airborne', { exact: true })).toBeInTheDocument();
    expect(within(dialog).queryByText('20.0 m MSL')).not.toBeInTheDocument();
    selected(1);
  });

  test('runtime context remounts selection and restores only the matching mode', () => {
    save(['2'], 'real');
    const view = render(tree('sitl'));
    fireEvent.click(screen.getByRole('button', { name: 'None', exact: true }));
    selected(0);
    view.rerender(tree('real'));
    expect(target('2')).toBeChecked();
    expect(target('1')).not.toBeChecked();
    selected(1);
    view.rerender(tree('sitl'));
    selected(0);
    expect(useFleetResources).toHaveBeenCalledWith('real');
  });

  test('unknown runtime disables actions; no mission launcher remains on Overview', () => {
    render(tree('unknown'));
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: /start.*(?:mission|swarm|show)|mission trigger/i })).not.toBeInTheDocument();
    expect(screen.queryByText('Mission Trigger')).not.toBeInTheDocument();
  });

  test('empty configuration offers setup rather than fabricated aircraft', () => {
    useFleetResources.mockReturnValue(resources([]));
    render(tree());
    expect(screen.getByRole('heading', { name: 'No configured aircraft' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Set up aircraft/ })).toHaveAttribute('href', '/fleet-enrollment');
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });
});
