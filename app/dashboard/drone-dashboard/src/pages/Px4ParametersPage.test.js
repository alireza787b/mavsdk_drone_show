import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import Px4ParametersPage from './Px4ParametersPage';
import useParameterResources from '../features/px4-parameters/useParameterResources';
import * as api from '../services/px4ParamsApiService';

jest.mock('../features/px4-parameters/useParameterResources');
jest.mock('../config/apiConfig', () => ({ getBackendURL: () => 'http://gcs.test' }));
jest.mock('../services/px4ParamsApiService', () => ({
  refreshPx4ParamSnapshots: jest.fn(), getPx4ParamProfile: jest.fn(), diffPx4ParamSnapshot: jest.fn(), importQgcParameterFile: jest.fn(),
  createPx4ParamReview: jest.fn(), applyPx4ParamReview: jest.fn(), getPx4ParamPatchJob: jest.fn(), getPx4ParamJobByIdempotencyKey: jest.fn(),
}));
jest.mock('../features/fleet-overview/ActionReview', () => ({
  __esModule: true, default: ({ intent }) => <div role="dialog" aria-label="Reboot command review">{intent.target_drone_ids.join(',')}</div>,
  buildActionStorageKey: (prefix, command) => `${prefix}:${command.target_drone_ids.join(',')}`,
  readPendingAction: () => null, readPendingActions: () => [],
}));
jest.mock('@mui/x-data-grid', () => ({ DataGrid: ({ rows, columns }) => <div data-testid="parameter-grid">{rows.map(row => <div key={row.id}>{columns[0].renderCell({ row, tabIndex: -1 })}<span>{row.displayValue}</span></div>)}</div> }));

const rows = [{ name: 'MPC_XY_VEL_MAX', component_id: 1, value_type: 'float', value: .123456789, decimal_places: null,
  default_value: 0, writable: true, unit: 'm/s', group: 'Position control', reboot_required: false }];
const snapshot = id => ({ snapshot: { snapshot_id: `snapshot-${id}`, hw_id: id, component_id: 1, created_at: Date.now(), stale_after_ms: 60000 }, rows });
const resources = () => ({ aircraft: ['1', '2'].map(id => ({ id, label: `Aircraft ${id}`, current: true, armed: false,
  runtime: { label: 'Live', level: 'online' }, availability: { available: true }, raw: { hw_id: id, pos_id: id } })),
  clusters: [], now: Date.now(), policy: { docs: { version: 'main' }, mutations: { require_disarmed: true, supported_component_ids: [1] } },
  profiles: [{ profile_id: 'baseline', name: 'Field baseline' }], loading: false,
});
const STORAGE = 'mds:px4-parameters:v2:http://gcs.test:sitl:tester';
const renderPage = () => render(<Px4ParametersPage runtimeMode="sitl" operatorId="tester" />);
async function choose(id) {
  fireEvent.click(screen.getByRole('button', { name: 'Choose aircraft' }));
  fireEvent.click(screen.getByRole('radio', { name: new RegExp(`H${id}`) }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect aircraft' }));
  await waitFor(() => expect(api.refreshPx4ParamSnapshots).toHaveBeenCalledWith({ hwIds: [id], componentId: 1 }));
  await screen.findByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' });
}
async function stageEdit(value = '9.123456789') {
  fireEvent.click(screen.getByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' }));
  fireEvent.click(screen.getByRole('button', { name: 'Edit value' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'New value for MPC_XY_VEL_MAX' }), { target: { value } });
  fireEvent.click(screen.getByRole('button', { name: 'Review change' }));
  await screen.findByRole('button', { name: 'Prepare review' });
}
beforeEach(() => {
  jest.clearAllMocks(); localStorage.clear(); sessionStorage.clear(); window.innerWidth = 1440;
  window.matchMedia = jest.fn(() => ({ matches: false }));
  useParameterResources.mockReturnValue(resources());
  api.refreshPx4ParamSnapshots.mockImplementation(async ({ hwIds }) => ({ data: { snapshots: hwIds.map(snapshot), errors: [] } }));
  api.getPx4ParamProfile.mockResolvedValue({ data: { profile_id: 'baseline', name: 'Field baseline', recommended_scope: 'fleet', entries: rows.map(row => ({ component_id: row.component_id, name: row.name, value_type: row.value_type, value: 10 })) } });
  api.createPx4ParamReview.mockImplementation(async request => ({ data: {
    review_id: 'review-1', review_hash: 'hash-1', hw_ids: request.hwIds, excluded_hw_ids: request.excludedHwIds, blocked: false, verify_readback: true,
    expires_at: Date.now() + 60000, warnings: [], targets: request.hwIds.map(id => ({ hw_id: id, snapshot_id: `snapshot-${id}`,
      blockers: [], warnings: [], unchanged_count: 0, changes: request.entries.map(entry => ({ ...entry, current_value: .123456789, desired_value: entry.value, changed: true })) })),
  } }));
  api.applyPx4ParamReview.mockImplementation(async request => {
    expect(JSON.parse(localStorage.getItem(STORAGE))[0].idempotencyKey).toBe(request.idempotencyKey);
    return { data: { job_id: 'job-1', review_id: 'review-1', review_hash: 'hash-1', idempotency_key: request.idempotencyKey, terminal: true, status: 'completed', unknown_targets: 0,
      results: [{ hw_id: '1', applied: true, verified: true, outcome: 'verified', result: { results: [{ ...rows[0], requested_value: 9.123456789, actual_value: 9.123456789, applied: true, verified: true, outcome: 'verified' }] } }] } };
  });
});

test('starts with no inspection target and does not silently select or write', async () => {
  renderPage();
  expect(screen.getByRole('button', { name: 'Choose aircraft' })).toBeInTheDocument();
  expect(api.refreshPx4ParamSnapshots).not.toHaveBeenCalled();
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
  await choose('1');
  expect(screen.getByText('0.1235 m/s')).toBeInTheDocument();
});

test('uses explicit exact editing, a native review, and a persisted idempotent receipt before apply', async () => {
  renderPage(); await choose('1'); await stageEdit();
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Prepare review' }));
  const apply = await screen.findByRole('button', { name: 'Apply 1 change to 1 aircraft' });
  expect(api.createPx4ParamReview).toHaveBeenCalledWith(expect.objectContaining({ hwIds: ['1'], entries: [expect.objectContaining({ value: 9.123456789 })] }));
  fireEvent.click(apply);
  await waitFor(() => expect(api.applyPx4ParamReview).toHaveBeenCalledTimes(1));
  await waitFor(() => expect(JSON.parse(localStorage.getItem(STORAGE))[0].job?.status).toBe('completed'));
  expect(api.applyPx4ParamReview).toHaveBeenCalledWith({ reviewId: 'review-1', reviewHash: 'hash-1', idempotencyKey: expect.any(String) });
});

test('inspection changes and snapshot refresh never retarget or overwrite a draft', async () => {
  renderPage(); await choose('1'); await stageEdit('8.7654321');
  fireEvent.click(screen.getByRole('button', { name: 'Close', exact: true }));
  await choose('2');
  fireEvent.click(screen.getByRole('button', { name: 'Refresh', exact: true }));
  fireEvent.click(screen.getByRole('button', { name: 'Groups', exact: true }));
  fireEvent.change(screen.getByRole('searchbox', { name: 'Find parameter' }), { target: { value: 'Position control' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review changes' }));
  expect(screen.getByRole('checkbox', { name: /Apply to Aircraft 1 · H1/ })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: /Apply to Aircraft 2 · H2/ })).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Prepare review' }));
  await screen.findByRole('button', { name: 'Apply 1 change to 1 aircraft' });
  expect(api.createPx4ParamReview).toHaveBeenCalledWith(expect.objectContaining({ hwIds: ['1'], entries: [expect.objectContaining({ value: 8.7654321 })] }));
});

test('profile source shares the review pipeline and begins with no mutation targets', async () => {
  renderPage();
  fireEvent.click(screen.getByRole('tab', { name: 'Profiles' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Review for aircraft' }));
  expect(screen.getByRole('button', { name: 'Prepare review' })).toBeDisabled();
  fireEvent.click(screen.getByRole('checkbox', { name: /Apply to Aircraft 2 · H2/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Prepare review' }));
  await screen.findByRole('button', { name: 'Apply 1 change to 1 aircraft' });
  expect(api.createPx4ParamReview).toHaveBeenCalledWith(expect.objectContaining({ hwIds: ['2'], source: 'mds_profile', profileId: 'baseline' }));
});

test('a lost apply response remains uncertain and recovery only looks up its original identity', async () => {
  api.applyPx4ParamReview.mockRejectedValue(new Error('Network interrupted'));
  api.getPx4ParamJobByIdempotencyKey.mockImplementation(async key => ({ data: { job_id: 'found-job', review_id: 'review-1', review_hash: 'hash-1', idempotency_key: key, status: 'unknown', terminal: true, unknown_targets: 1, results: [] } }));
  renderPage(); await choose('1'); await stageEdit();
  fireEvent.click(screen.getByRole('button', { name: 'Prepare review' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Apply 1 change to 1 aircraft' }));
  await screen.findByText(/Outcome unconfirmed: Network interrupted/);
  const saved = JSON.parse(localStorage.getItem(STORAGE))[0];
  fireEvent.click(screen.getByRole('button', { name: 'Check receipt' }));
  await waitFor(() => expect(api.getPx4ParamJobByIdempotencyKey).toHaveBeenCalledWith(saved.idempotencyKey));
  expect(api.applyPx4ParamReview).toHaveBeenCalledTimes(1);
});

test('all imported changes are accessible and stay bound to their originating aircraft', async () => {
  const entries = Array.from({ length: 1200 }, (_, index) => ({ component_id: 1, name: `TEST_${index}`, value_type: 'int', value: index }));
  api.importQgcParameterFile.mockResolvedValue({ data: { entries, skipped_count: 1, warnings: [{ line: 1202, message: 'Unsupported parameter type' }] } });
  renderPage(); await choose('1');
  fireEvent.change(screen.getByLabelText('Import QGC parameter file'), { target: { files: [{ name: 'fleet.params', text: async () => 'mock file' }] } });
  fireEvent.click(await screen.findByRole('button', { name: 'Prepare review' }));
  await screen.findByRole('button', { name: 'Apply 1200 changes to 1 aircraft' }, { timeout: 5000 });
  expect(screen.getByText('TEST_1199')).toBeInTheDocument();
  expect(screen.getByText('Line 1202: Unsupported parameter type')).toBeInTheDocument();
  expect(api.createPx4ParamReview).toHaveBeenCalledWith(expect.objectContaining({ hwIds: ['1'], source: 'qgc_import', entries }));
}, 15000);

test('phone defaults to List and deliberate Groups browsing/search never writes', async () => {
  window.innerWidth = 390;
  renderPage();
  fireEvent.click(screen.getByRole('button', { name: 'Choose aircraft' }));
  fireEvent.click(screen.getByRole('radio', { name: /H1/ })); fireEvent.click(screen.getByRole('button', { name: 'Inspect aircraft' }));
  await screen.findByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' });
  expect(screen.getByRole('button', { name: 'List', exact: true })).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(screen.getByRole('button', { name: 'Groups', exact: true }));
  const group = await screen.findByRole('button', { name: /Position control/ });
  expect(screen.queryByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' })).not.toBeInTheDocument();
  fireEvent.click(group);
  expect(screen.getByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' })).toBeInTheDocument();
  fireEvent.change(screen.getByRole('searchbox', { name: 'Find parameter' }), { target: { value: 'MPC_XY' } });
  expect(screen.queryByRole('button', { name: /Position control/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' })).toBeInTheDocument();
  expect(api.createPx4ParamReview).not.toHaveBeenCalled();
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
});

test('failed first read offers retry without pretending no aircraft was chosen', async () => {
  api.refreshPx4ParamSnapshots.mockRejectedValueOnce(new Error('Aircraft unavailable'));
  renderPage();
  fireEvent.click(screen.getByRole('button', { name: 'Choose aircraft' }));
  fireEvent.click(screen.getByRole('radio', { name: /H1/ }));
  fireEvent.click(screen.getByRole('button', { name: 'Inspect aircraft' }));
  await screen.findByRole('button', { name: 'Retry read' });
  expect(screen.queryByText('Choose an aircraft to read its parameters.')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Retry read' }));
  await screen.findByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' });
  expect(api.refreshPx4ParamSnapshots).toHaveBeenCalledTimes(2);
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
});

test('cached snapshot stays inspectable offline and is described as a stale snapshot', async () => {
  const state = resources();
  state.now += 120000;
  state.aircraft[0].runtime = { label: 'Offline', level: 'offline' };
  useParameterResources.mockReturnValue(state);
  renderPage(); await choose('1');
  fireEvent.click(screen.getByRole('button', { name: 'Inspect MPC_XY_VEL_MAX' }));
  const dialog = screen.getByRole('dialog', { name: 'MPC_XY_VEL_MAX' });
  expect(within(dialog).getByText(/Snapshot stale/)).toBeInTheDocument();
  expect(within(dialog).getByText(/snapshot values from aircraft/)).toBeInTheDocument();
  expect(within(dialog).queryByText(/live values/i)).not.toBeInTheDocument();
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
});

test('reboot uses a separate exact-target shared command review', async () => {
  renderPage(); await choose('2');
  fireEvent.click(screen.getAllByRole('button', { name: 'Reboot PX4' })[0]);
  const review = screen.getByRole('dialog', { name: 'Reboot command review' });
  expect(within(review).getByText('2')).toBeInTheDocument();
  expect(api.createPx4ParamReview).not.toHaveBeenCalled();
  expect(api.applyPx4ParamReview).not.toHaveBeenCalled();
});
