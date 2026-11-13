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
jest.mock('../features/fleet-overview/FleetMap', () => ({ __esModule: true,
  default: () => <section aria-label="Aircraft map" /> }));
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
  heartbeat_last_seen: NOW / 1000,
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
const recipient = id => screen.queryByLabelText(`Command recipient: Aircraft ${id} · H${id}`);
const inspect = (id) => screen.getByRole('button', { name: `Inspect Aircraft ${id} · H${id}` });
const actionRail = () => screen.getByLabelText('Selected aircraft actions');
const showAll = () => fireEvent.change(screen.getByRole('combobox', { name: 'Show aircraft' }), { target: { value: 'all' } });
const selected = count => expect(within(actionRail()).getByRole('button',{name:'Choose command aircraft'})).toHaveAttribute('data-recipient-count',String(count));
const openPicker = () => { fireEvent.click(screen.getByRole('button',{name:'Choose command aircraft'})); return within(screen.getByRole('dialog',{name:'Command aircraft'})); };
const changeRecipients = ids => {
  const picker=openPicker();
  fireEvent.click(picker.getByRole('button',{name:'Clear command aircraft'}));
  ids.forEach(id=>fireEvent.click(picker.getByRole('checkbox',{name:`Include Aircraft ${id} (H${id})`})));
  fireEvent.click(picker.getByRole('button',{name:`Use ${ids.length} aircraft`}));
};
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
  test('card checkbox shares To without inspecting or dispatching, and locks during a flight review', () => {
    render(tree());
    const box=screen.getByRole('checkbox',{name:'Include Aircraft 1 (H1)'});
    selected(2);
    fireEvent.click(box);selected(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('General action review')).not.toBeInTheDocument();
    fireEvent.click(box);selected(2);
    fireEvent.click(within(actionRail()).getByRole('button',{name:'Takeoff'}));
    expect(box).toBeDisabled();
    expect(JSON.parse(screen.getByTestId('takeoff-command').textContent).target_drone_ids).toContain('1');
  });
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
      mission_type: DRONE_ACTION_TYPES.RETURN_RTL, target_drone_ids: ['1', '2'],
    });
    expect(JSON.parse(sessionStorage.getItem(key))).toEqual(previous);
  });

  test.each(['sitl', 'real'])('initializes available %s aircraft, not every configured aircraft', (mode) => {
    render(tree(mode));
    ['1', '2'].forEach(id => expect(recipient(id)).toBeInTheDocument());
    expect(screen.getAllByRole('checkbox')).toHaveLength(2);
    selected(2);
    expect(screen.getByText(mode.toUpperCase())).toBeInTheDocument();
    showAll();
    expect(recipient('3')).not.toBeInTheDocument();
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' })).toBeEnabled();
  });

  test.each([[[]], [['2']]])('restores saved exact selection %j, including deliberately empty', (ids) => {
    save(ids);
    render(tree());
    showAll();
    ['1', '2', '3'].forEach(id => expect(Boolean(recipient(id))).toBe(ids.includes(id)));
    selected(ids.length);
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' }).disabled).toBe(ids.length === 0);
  });

  test('unknown remembered IDs remain reviewable and block actions until explicit reconciliation', () => {
    save(['2', 'removed']);
    render(tree());
    expect(screen.getByRole('button',{name:'Review missing command aircraft'})).toHaveTextContent('1 missing');
    selected(2);
    expect(within(actionRail()).getByRole('button', { name: 'Takeoff' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button',{name:'Review missing command aircraft'}));
    const picker=within(screen.getByRole('dialog',{name:'Command aircraft'}));
    fireEvent.click(picker.getByRole('checkbox',{name:'Include Aircraft removed (Hremoved)'}));
    fireEvent.click(picker.getByRole('button',{name:'Use 1 aircraft'}));
    selected(1);
    expect(recipient('2')).toBeInTheDocument();
    expect(recipient('1')).not.toBeInTheDocument();
  });

  test('filter, inspect and list view do not change command membership', () => {
    save(['1', '2', '3']);
    render(tree());
    showAll();
    changeRecipients(['1','3']);
    selected(2);
    fireEvent.change(screen.getByRole('searchbox', { name: 'Find aircraft' }), { target: { value: 'hw 1' } });
    expect(screen.getByRole('checkbox', { name: 'Include Aircraft 1 (H1)' })).toBeChecked();
    expect(screen.getByRole('button',{name:'Show 1 command aircraft outside this view'})).toBeInTheDocument();
    fireEvent.click(inspect('1'));
    expect(screen.getByRole('dialog', { name: 'Aircraft 1' })).toBeInTheDocument();
    selected(2);
    fireEvent.click(screen.getByRole('button', { name: 'Close aircraft details' }));
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'List', exact: true }));
    expect(recipient('1')).toBeInTheDocument();
    expect(recipient('2')).not.toBeInTheDocument();
    expect(recipient('3')).toBeInTheDocument();
    selected(2);
  });

  test('heartbeat loss becomes stale, then leaves Available without dropping selected targets', () => {
    const snapshot = resources([live('1', { is_armed: true, landed_state: 2 })]);
    useFleetResources.mockReturnValue(snapshot);
    const view = render(tree());
    useFleetResources.mockReturnValue({ ...snapshot, nowMs: NOW + 11000 });
    view.rerender(tree());
    expect(recipient('1')).toBeInTheDocument();
    expect(inspect('1').closest('article')).toHaveAttribute('data-availability', 'stale');
    useFleetResources.mockReturnValue({ ...snapshot, nowMs: NOW + 65000, telemetry: { ...snapshot.telemetry, error: new Error('network') } });
    view.rerender(tree());
    expect(recipient('1')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('measurements are aging');
    selected(1);
    fireEvent.click(screen.getByRole('button', { name: 'Show 1 command aircraft outside this view' }));
    expect(recipient('1')).toBeInTheDocument();
    expect(inspect('1')).toHaveTextContent('Unknown');
    expect(inspect('1').closest('article')).toHaveAttribute('data-availability', 'offline');
  });

  test('new configured aircraft do not join an initialized target set', () => {
    useFleetResources.mockReturnValue(resources([live('1')]));
    const view = render(tree());
    useFleetResources.mockReturnValue(resources([live('1'), live('2')]));
    view.rerender(tree());
    expect(recipient('1')).toBeInTheDocument();
    expect(recipient('2')).not.toBeInTheDocument();
    selected(1);
    const picker=openPicker();
    fireEvent.click(picker.getByRole('button',{name:'Use available now'}));
    selected(1);
    fireEvent.click(picker.getByRole('button',{name:'Use 2 aircraft'}));
    expect(recipient('2')).toBeInTheDocument();
    selected(2);
  });

  test('takeoff receives an exact frozen ID snapshot, not All or the visible subset', () => {
    save(['1', '3']);
    const view=render(tree());
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'hw 1' } });
    fireEvent.click(within(actionRail()).getByRole('button', { name: 'Takeoff' }));
    const command = JSON.parse(screen.getByTestId('takeoff-command').textContent);
    expect(command).toMatchObject({ mission_type: DRONE_ACTION_TYPES.TAKE_OFF, target_drone_ids: ['1', '3'], takeoff_altitude: 10 });
    expect(command).not.toHaveProperty('target_scope');
    expect(screen.getByRole('button',{name:'Choose command aircraft'})).toBeDisabled();
    useFleetResources.mockReturnValue(resources([live('1'),live('2'),live('3'),live('4')]));
    view.rerender(tree());
    expect(JSON.parse(screen.getByTestId('takeoff-command').textContent)).toEqual(command);
    const props = TakeoffDialog.mock.calls[TakeoffDialog.mock.calls.length - 1][0];
    expect(props.aircraft).toHaveLength(4);
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
    changeRecipients([]);
    selected(0);
    view.rerender(tree('real'));
    expect(recipient('2')).toBeInTheDocument();
    expect(recipient('1')).not.toBeInTheDocument();
    selected(1);
    view.rerender(tree('sitl'));
    selected(0);
    expect(useFleetResources).toHaveBeenCalledWith('real');
  });

  test('first telemetry failure does not persist an empty default or widen to configured', () => {
    useFleetResources.mockReturnValue({ ...resources(), telemetry: { response: null, error: new Error('offline'), loading: false } });
    const view = render(tree());
    selected(0);
    expect(within(actionRail()).getByRole('button', { name: 'Return' })).toBeDisabled();
    useFleetResources.mockReturnValue(resources());
    view.rerender(tree());
    selected(2);
  });

  test('a positionless selected aircraft is counted outside the map, without changing command scope',async()=>{
    useFleetResources.mockReturnValue(resources([live('1',{position_lat:35.7,position_long:51.4,global_position_valid:true}),live('2')]));
    render(tree());
    fireEvent.click(screen.getByRole('button',{name:'Map',exact:true}));
    await screen.findByLabelText('Aircraft map');
    selected(2);
    fireEvent.click(screen.getByRole('button',{name:'Show 1 command aircraft outside this map'}));
    expect(screen.getByRole('button',{name:'List',exact:true})).toHaveAttribute('aria-pressed','true');
    expect(recipient('1')).toBeInTheDocument();
    expect(recipient('2')).toBeInTheDocument();
    selected(2);
  });

  test('Cancel keeps the saved recipient set and focus returns to its control',()=>{
    render(tree());
    const control=screen.getByRole('button',{name:'Choose command aircraft'});
    control.focus();
    const picker=openPicker();
    fireEvent.click(picker.getByRole('button',{name:'Clear command aircraft'}));
    fireEvent.click(picker.getByRole('button',{name:'Cancel',exact:true}));
    selected(2);
    expect(control).toHaveFocus();
    fireEvent.click(within(actionRail()).getByRole('button',{name:'Hold'}));
    expect(JSON.parse(screen.getByLabelText('General action review').textContent).target_drone_ids).toEqual(['1','2']);
  });

  test('inspector More freezes that aircraft only, independent of the bulk selection', () => {
    render(tree());
    fireEvent.click(inspect('2'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: /More/ }));
    const panel = screen.getByRole('dialog', { name: 'More actions' });
    expect(panel).toHaveTextContent('1 aircraft');
    expect(panel).toHaveTextContent('Aircraft 2 · H2');
    expect(screen.queryByRole('dialog', { name: 'Aircraft 2' })).not.toBeInTheDocument();
    selected(2);
    fireEvent.click(within(panel).getByRole('button', { name: 'Close more actions' }));
    selected(2);
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
