import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import FleetOpsPage from './FleetOpsPage';
import useFetch from '../hooks/useFetch';
import { applyFleetGitSyncResponse, dryRunFleetGitSyncResponse, getFleetGitOperationResponse } from '../services/gcsApiService';

jest.mock('../hooks/useFetch');
jest.mock('../services/gcsApiService', () => ({
  ...jest.requireActual('../services/gcsApiService'),
  applyFleetGitSyncResponse: jest.fn(), dryRunFleetGitSyncResponse: jest.fn(), getFleetGitOperationResponse: jest.fn(),
}));

const gcs = { branch: 'main', commit: 'abcde123456', remote_url: 'https://github.com/demo/demo' };
function props() {
  const nodes = [
    { pos_id: 1, hw_id: '21', branch: 'field', commit: gcs.commit, status: 'synced', in_sync_with_gcs: true },
    { pos_id: 2, hw_id: '22', branch: 'main', commit: '111111111', status: 'synced', in_sync_with_gcs: false },
    { pos_id: 3, hw_id: '23', status: 'unknown', commit: 'unknown', in_sync_with_gcs: false },
    { pos_id: 4, hw_id: '24', status: 'synced', commit: gcs.commit, in_sync_with_gcs: true },
  ];
  return { gitStatusOverride: { gcs_status: gcs, git_status: Object.fromEntries(nodes.map(n => [n.hw_id, n])) },
    heartbeatOverride: { timestamp: Date.now(), heartbeats: nodes.map(n => ({ ...n, last_heartbeat: Date.now(), online: n.pos_id < 4, runtime_mode: 'real' })) },
    nodeBootStatusOverride: { nodes: {} }, operatorId: 'pilot' };
}
function status(phase = 'review', eligible = ['21','22'], blocked = []) {
  const byState = { review: 'ready', applying: 'applying', verifying: 'verifying', completed: 'verified', failed: 'unconfirmed' };
  return { operation_id: 'git-sync-1', preview_id: 'git-sync-1', target_branch: 'main', target_commit: gcs.commit, phase,
    started_at: 1000, updated_at: 2000, completed_at: phase === 'completed' ? 2000 : null,
    target_counts: { total: eligible.length + blocked.length, ready: eligible.length, blocked: blocked.length,
      verified: phase === 'completed' ? eligible.length : 0, unconfirmed: phase === 'failed' ? eligible.length : 0 },
    per_aircraft_state: Object.fromEntries([...eligible, ...blocked].map(id => [id, { hw_id: id, pos_id: Number(id) - 20,
      state: blocked.includes(id) ? 'blocked' : byState[phase], error_code: blocked.includes(id) ? 'offline' : null }])) };
}
function view(route = '/fleet-ops', override = props()) {
  return render(<MemoryRouter initialEntries={[route]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
    <FleetOpsPage {...override} /></MemoryRouter>);
}
function eligiblePreview(eligible = ['21','22'], blocked = []) {
  dryRunFleetGitSyncResponse.mockResolvedValue({ data: { ...status('review',eligible,blocked), job_id: 'git-sync-1', confirmation_token: 'one-use-proof' } });
}
const btn = name => screen.getByRole('button', {name});
const click = name => fireEvent.click(btn(name));
const checkedStorage = () => Object.values(window.sessionStorage);
beforeEach(() => {
  jest.resetAllMocks();
  window.sessionStorage.clear();
  useFetch.mockReturnValue({ loading:false, data:null, error:null });
  dryRunFleetGitSyncResponse.mockImplementation(async ({hw_ids}) => ({data: {
    ...status('review', hw_ids), confirmation_token:'one-use-proof', job_id:'git-sync-1',
  }}));
});

test('inspects one aircraft, explains the branch difference on request and restores focus', () => {
  view();
  expect(screen.getByRole('link', {name:'Maintenance'})).toHaveAttribute('href', '/maintenance');
  expect(screen.getByRole('link', {name:/fleet ops guide/i})).toHaveAttribute('href', 'https://github.com/demo/demo/blob/main/docs/guides/fleet-ops.md');
  expect(screen.queryByText('field')).not.toBeInTheDocument();
  const opener = btn('Inspect aircraft 1');
  opener.focus();
  fireEvent.click(opener);
  const details = screen.getByRole('complementary', {name:'Details for aircraft 1'});
  expect(within(details).getByText('field')).toBeVisible();
  expect(within(details).queryByText(/Same revision as GCS/)).not.toBeInTheDocument();
  expect(btn('Close aircraft details')).toHaveFocus();
  const hint = btn('About update branch');
  act(() => hint.focus());
  expect(within(details).getByRole('tooltip')).toHaveTextContent('Same revision as GCS');
  fireEvent.keyDown(hint, { key: 'Escape' });
  expect(within(details).queryByRole('tooltip')).not.toBeInTheDocument();
  expect(details).toBeVisible();
  fireEvent.keyDown(hint, { key: 'Escape' });
  expect(screen.queryByRole('complementary')).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
});

test('reports roster connection and software states alongside each aircraft identity', () => {
  view();
  const roster = screen.getByRole('region', {name:'Aircraft roster'});
  expect(within(roster).getByRole('list', {name:'Aircraft'})).toBeVisible();
  expect(btn('Inspect aircraft 1')).toHaveAccessibleDescription(/^H21\. Connection: Live\. Software: Synced\./);
  expect(btn('Inspect aircraft 3')).toHaveAccessibleDescription('H23. Connection: Live. Software: Unknown.');
  expect(btn('Inspect aircraft 4')).toHaveAccessibleDescription('H24. Connection: Recent loss. Software: Last synced.');
});

test('software review follows ground-station reviewability and all aircraft retains stale reports', () => {
  const override = props();
  override.gitStatusOverride.git_status['22'].reviewable = true;
  Object.assign(override.gitStatusOverride.git_status['24'], {
    commit: '222222222', in_sync_with_gcs: false, reviewable: false,
  });
  override.heartbeatOverride.heartbeats[3].last_heartbeat -= 90_000;
  view('/fleet-ops?filter=drift', override);
  expect(btn('Inspect aircraft 2')).toBeVisible();
  expect(btn('Inspect aircraft 3')).toBeVisible();
  expect(screen.queryByRole('button', {name:'Inspect aircraft 4'})).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox'), {target:{value:'all'}});
  expect(btn('Inspect aircraft 4')).toBeVisible();
});

test('Sync online previews all eligible hardware identities even with a search or filter active', async () => {
  view();
  fireEvent.change(screen.getByRole('searchbox'), {target:{value:'H22'}});
  expect(screen.queryByRole('button', {name:'Inspect aircraft 1'})).not.toBeInTheDocument();
  click('Sync online');
  await screen.findByText('Review sync');
  expect(dryRunFleetGitSyncResponse).toHaveBeenCalledWith({hw_ids:['21','22']});
  expect(screen.getByText('2 ready · 0 excluded')).toBeVisible();
  expect(applyFleetGitSyncResponse).not.toHaveBeenCalled();
  click('Cancel');
  expect(checkedStorage()).toEqual([]);
});

test('explicit empty selection cannot broaden, and offline or unknown aircraft cannot be selected', async () => {
  view();
  click('Select aircraft');
  expect(btn('Sync selected')).toBeDisabled();
  expect(screen.getByRole('checkbox',{name:'Select aircraft 3'})).toBeDisabled();
  expect(screen.getByRole('checkbox',{name:'Select aircraft 4'})).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox',{name:'Select aircraft 2'}));
  fireEvent.change(screen.getByRole('combobox'),{target:{value:'offline'}});
  click('Sync selected');
  await screen.findByText('Review sync');
  expect(dryRunFleetGitSyncResponse).toHaveBeenCalledWith({hw_ids:['22']});
});

test('a missing explicitly named maintenance target stays scoped', () => {
  view('/fleet-ops?hw_id=absent');
  expect(btn('Sync selected')).toBeDisabled();
  expect(dryRunFleetGitSyncResponse).not.toHaveBeenCalled();
});
test('legacy drift bookmark only previews the online drifted subset once', async () => {
  view('/fleet-ops?tab=sync&filter=drift&scope=needs-sync&autoplan=1');
  await screen.findByText('Review sync');
  expect(dryRunFleetGitSyncResponse.mock.calls).toEqual([[{hw_ids:['22']}]]);
  expect(applyFleetGitSyncResponse).not.toHaveBeenCalled();
});

test('apply sends the reviewed proof once, shows real verification progress and restores by lookup after reload', async () => {
  eligiblePreview(['21'], ['22']);
  const updateReceipt = {};
  applyFleetGitSyncResponse.mockImplementation(() => new Promise(resolve => { updateReceipt.resolve = resolve; }));
  getFleetGitOperationResponse.mockResolvedValue({data:status('verifying',['21'],['22'])});
  const { unmount } = view();
  click('Sync online');
  await screen.findByText('Review sync');
  expect(screen.getByText('1 ready · 1 excluded')).toBeVisible();
  expect(screen.getByText(/Excluded/)).toBeVisible();
  click('Apply sync');
  expect(btn('Apply sync')).toBeDisabled();
  expect(applyFleetGitSyncResponse.mock.calls).toEqual([[{
    dry_run_id: 'git-sync-1', confirmation: { acknowledged_risks: true, confirmation_token:'one-use-proof' },
  }, { params:{background:true} }]]);
  await act(async () => updateReceipt.resolve({data:status('applying',['21'],['22'])}));
  await screen.findByText('Verifying software');
  expect(checkedStorage()).toEqual(['git-sync-1']);
  unmount();
  getFleetGitOperationResponse.mockResolvedValue({data:status('completed',['21'],['22'])});
  view();
  await screen.findByText('Sync verified');
  expect(screen.getByText('1 of 1 verified')).toBeVisible();
  expect(applyFleetGitSyncResponse).toHaveBeenCalledTimes(1);
  expect(dryRunFleetGitSyncResponse).toHaveBeenCalledTimes(1);
});

test('reopening an unsubmitted preview requires a fresh review scoped to its original identities including exclusions', async () => {
  const { unmount } = view();
  click('Sync online');
  await screen.findByText('Review sync');
  unmount();
  getFleetGitOperationResponse.mockResolvedValue({ data: status('review',['22'],['21']) });
  view();
  await screen.findByRole('button', {name:'Refresh preview'});
  expect(screen.queryByRole('button', {name:'Apply sync'})).not.toBeInTheDocument();
  click('Refresh preview');
  await screen.findByRole('button', {name:'Apply sync'});
  expect(dryRunFleetGitSyncResponse).toHaveBeenLastCalledWith({hw_ids:['21','22']});
  expect(applyFleetGitSyncResponse).not.toHaveBeenCalled();
});

test('an uncertain apply reconciles by GET without replay, including after a temporarily lost response', async () => {
  applyFleetGitSyncResponse.mockRejectedValue(new Error('connection lost'));
  getFleetGitOperationResponse.mockRejectedValueOnce(new Error('ground station offline'))
    .mockResolvedValue({data:status('completed')});
  view();
  click('Sync online');
  await screen.findByText('Review sync');
  click('Apply sync');
  await screen.findByText(/Waiting for the ground station/i);
  expect(btn('Apply sync')).toBeDisabled();
  click('Refresh sync status');
  await screen.findByText('Sync verified');
  expect(applyFleetGitSyncResponse).toHaveBeenCalledTimes(1);
});

test('preview auth failure is visible and allows a new preview', async () => {
  dryRunFleetGitSyncResponse.mockRejectedValueOnce({response:{data:{message:'Login required.'}}});
  view();
  click('Sync online');
  expect(await screen.findByRole('alert')).toHaveTextContent('Login required.');
  expect(btn('Sync online')).toBeEnabled();
  click('Sync online');
  await screen.findByText('Review sync');
  expect(applyFleetGitSyncResponse).not.toHaveBeenCalled();
});

test('technical bookmarks open maintenance and preserve the aircraft identity', async () => {
  function Destination() { return <p>{useLocation().search}</p>; }
  render(<MemoryRouter initialEntries={['/fleet-ops?tab=access&hw_id=22']} future={{v7_startTransition:true,v7_relativeSplatPath:true}}>
    <Routes><Route path="/fleet-ops" element={<FleetOpsPage />} /><Route path="/maintenance" element={<Destination />} /></Routes></MemoryRouter>);
  await waitFor(() => expect(screen.getByText('?section=access&hw_id=22')).toBeVisible());
});

test('a server preview with a substituted hardware identity never offers Apply', async () => {
  eligiblePreview(['21','24']);
  view();
  click('Sync online');
  expect(await screen.findByRole('alert')).toHaveTextContent('Aircraft changed during preview');
  expect(screen.queryByRole('button',{name:'Apply sync'})).not.toBeInTheDocument();
  expect(checkedStorage()).toEqual([]);
});

test('different operators on the same browser have independent operation pointers', async () => {
  const { unmount } = view();
  click('Sync online');
  await screen.findByText('Review sync');
  unmount();
  view('/fleet-ops', {...props(), operatorId:'instructor'});
  expect(screen.queryByText('Retrieving sync status')).not.toBeInTheDocument();
  expect(getFleetGitOperationResponse).not.toHaveBeenCalled();
});

test('partial verification shows each unconfirmed aircraft and re-previews just those identities', async () => {
  const result = status('completed');
  result.phase = 'partial';
  result.target_counts.verified = 1;
  result.target_counts.unconfirmed = 1;
  result.per_aircraft_state['22'].state = 'unconfirmed';
  result.per_aircraft_state['22'].error_code = 'verification_timeout';
  result.message = 'Verified 1 of 2 aircraft';
  applyFleetGitSyncResponse.mockResolvedValue({data:result});
  view();
  click('Sync online');
  await screen.findByText('Review sync');
  click('Apply sync');
  await screen.findByText('Partially verified');
  const progress = screen.getByRole('region', {name:'Software sync progress'});
  expect(within(progress).getByText('1 of 2 verified')).toBeVisible();
  expect(within(progress).queryByText(result.message)).not.toBeInTheDocument();
  const issues = within(progress).getByRole('list', {name:'Aircraft needing review'});
  expect(within(issues).getByText('Aircraft 2')).toBeVisible();
  expect(within(issues).getByText(/Verification timed out/)).toBeVisible();
  click(/Review unconfirmed/);
  await screen.findByText('Review sync');
  expect(dryRunFleetGitSyncResponse).toHaveBeenLastCalledWith({hw_ids:['22']});
  expect(applyFleetGitSyncResponse).toHaveBeenCalledTimes(1);
});
