import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

jest.mock('react-toastify', () => ({ toast: { error: jest.fn(), info: jest.fn(), success: jest.fn(), warning: jest.fn() } }));
jest.mock('../components/SwarmRuntimeControls', () => () => <div data-testid="operate-controls" />);
jest.mock('../components/SwarmFormation3D', () => ({ selectedId, onSelect }) => <div data-testid="3d-view"><span>Selected {selectedId}</span><button onClick={() => onSelect('2')}>Select follower in 3D</button></div>);
jest.mock('../components/DroneGraph', () => ({ selectedDroneId, onSelectDrone }) => <div data-testid="graph-view"><span>Selected {selectedDroneId}</span><button onClick={() => onSelectDrone('2')}>Select follower in graph</button></div>);
jest.mock('../services/gcsApiService', () => ({
  getFleetConfigResponse: jest.fn(), getUnifiedGitStatusResponse: jest.fn(), getSwarmConfigResponse: jest.fn(),
  saveSwarmConfigResponse: jest.fn(), getSwarmDesignStatusResponse: jest.fn(), publishSwarmConfigResponse: jest.fn(),
  unwrapSwarmConfigPayload: (payload) => Array.isArray(payload) ? payload : payload?.assignments || [],
}));

const { default: SwarmDesign } = require('./SwarmDesign');
const { getFleetConfigResponse, getUnifiedGitStatusResponse, getSwarmConfigResponse,
  saveSwarmConfigResponse, getSwarmDesignStatusResponse, publishSwarmConfigResponse } = require('../services/gcsApiService');
const { toast } = require('react-toastify');
const { GIT_REPO } = require('../version');
const initialAssignments = [
  { hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' },
  { hw_id: 2, follow: 1, offset_x: 6, offset_y: 0, offset_z: 0, frame: 'ned' },
];
let server;
const renderPage = () => render(<MemoryRouter initialEntries={['/swarm-design?tab=design']}
  future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><SwarmDesign /></MemoryRouter>);
const applyButton = () => screen.getByRole('button', { name: 'Apply plan' });
const publishButton = () => screen.getByRole('button', { name: 'Save to repo' });
async function selectFollower() {
  fireEvent.click(await screen.findByRole('button', { name: 'NET-LEADER, formation position' }));
  return screen.getByRole('spinbutton', { name: 'offset_x metres' });
}
async function editNorth(value = '8') { fireEvent.change(await selectFollower(), { target: { value } }); }
async function confirmApply() {
  fireEvent.click(applyButton());
  const dialog = await screen.findByRole('dialog', { name: 'Apply plan?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply plan' }));
}

beforeEach(() => {
  jest.clearAllMocks(); window.localStorage.clear();
  server = { version: 1, revision: 'revision-1', assignments: initialAssignments.map((entry) => ({ ...entry })) };
  getFleetConfigResponse.mockResolvedValue({ data: [
    { hw_id: 1, pos_id: 1, callsign: 'SCOUT' }, { hw_id: 2, pos_id: 2, callsign: 'NET-LEADER' },
  ] });
  getSwarmConfigResponse.mockImplementation(async () => ({ data: server }));
  getUnifiedGitStatusResponse.mockResolvedValue({ data: { gcs_status: { uncommitted_changes: [] } } });
  getSwarmDesignStatusResponse.mockResolvedValue({ data: { revision: 'revision-1', nodes: [] } });
  saveSwarmConfigResponse.mockImplementation(async (assignments) => {
    server = { version: 1, revision: 'revision-2', assignments };
    return { data: { status: 'success', config: server, application: { revision: 'revision-2', nodes: [] } } };
  });
  publishSwarmConfigResponse.mockResolvedValue({ data: { status: 'success', git_result: { success: true, pushed: true } } });
});

test('renders real linked canvas and inspector with Operate separate', async () => {
  renderPage();
  expect(await screen.findByRole('button', { name: 'SCOUT, leader origin' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: /smart swarm guide/i })).toHaveAttribute('href', `https://github.com/${GIT_REPO}/blob/main/docs/features/smart-swarm.md`);
  expect(screen.getByRole('group', { name: 'Editable swarm top view' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Links' }));
  fireEvent.click(screen.getByText('Select follower in graph'));
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(6);
  fireEvent.click(screen.getByRole('tab', { name: '3D' }));
  expect(await screen.findByTestId('3d-view')).toHaveTextContent('Selected 2');
  expect(screen.queryByTestId('operate-controls')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Operate' }));
  expect(screen.getByTestId('operate-controls')).toBeInTheDocument();
});

test('numeric edits remain browser-local and undo/redo restore exact offsets', async () => {
  renderPage(); await editNorth('9');
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(9);
  expect(applyButton()).toBeEnabled(); expect(publishButton()).toBeEnabled();
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled(); expect(publishSwarmConfigResponse).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Undo formation edit' }));
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(6);
  fireEvent.click(screen.getByRole('button', { name: 'Redo formation edit' }));
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(9);
});

test('frame conversion preserves preview placement at explicit parent heading', async () => {
  renderPage(); await selectFollower();
  fireEvent.change(screen.getByLabelText(/Preview heading/), { target: { value: '90' } });
  fireEvent.change(screen.getByLabelText('Reference'), { target: { value: 'body' } });
  expect(Number(screen.getByRole('spinbutton', { name: 'offset_x metres' }).value)).toBeCloseTo(0);
  expect(screen.getByRole('spinbutton', { name: 'offset_y metres' })).toHaveValue(-6);
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
});

test('Apply waits for confirmation and carries the loaded revision', async () => {
  renderPage(); await editNorth();
  fireEvent.click(applyButton());
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
  const dialog = await screen.findByRole('dialog', { name: 'Apply plan?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply plan' }));
  await waitFor(() => expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1));
  expect(saveSwarmConfigResponse).toHaveBeenCalledWith(expect.arrayContaining([expect.objectContaining({ hw_id: 2, follow: 1, offset_x: 8 })]),
    { commit: false, revision: 'revision-1', acknowledgedUnavailableIds: [] });
  await waitFor(() => expect(publishButton()).toBeEnabled());
});

test('Publish uses the applied revision without another config write', async () => {
  getUnifiedGitStatusResponse.mockResolvedValue({ data: { gcs_status: { uncommitted_changes: [' M swarm.json'] } } });
  renderPage(); await selectFollower();
  await waitFor(() => expect(publishButton()).toBeEnabled());
  fireEvent.click(publishButton());
  const dialog = await screen.findByRole('dialog', { name: 'Save plan to repository?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save to repo' }));
  await waitFor(() => expect(publishSwarmConfigResponse).toHaveBeenCalledWith('revision-1'));
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
});

test('unreachable aircraft require explicit acknowledgement without silently retrying', async () => {
  saveSwarmConfigResponse.mockRejectedValueOnce({ response: { data: { detail: {
    code: 'unavailable_confirmation_required', unavailable_hw_ids: ['2'],
  } } } });
  renderPage(); await editNorth(); await confirmApply();
  const dialog = await screen.findByRole('dialog', { name: 'Some aircraft are unreachable' });
  expect(within(dialog).getByText(/NET-LEADER/)).toBeInTheDocument();
  expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply anyway' }));
  await waitFor(() => expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(2));
  expect(saveSwarmConfigResponse.mock.calls[1][1]).toEqual({ commit: false, revision: 'revision-1', acknowledgedUnavailableIds: ['2'] });
});

test('revision conflicts retain the draft and do not report success', async () => {
  const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
  saveSwarmConfigResponse.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'Formation changed; refresh and review.' } } });
  renderPage(); await editNorth(); await confirmApply();
  await screen.findAllByText('Formation changed; refresh and review.');
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(8);
  expect(toast.success).not.toHaveBeenCalled(); expect(publishSwarmConfigResponse).not.toHaveBeenCalled();
  consoleError.mockRestore();
});

test('a matching browser draft survives remount without operational writes', async () => {
  const first = renderPage(); await editNorth('11'); first.unmount();
  renderPage(); await selectFollower();
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(11);
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
});

test('cluster overview and view changes do not change flight scope or save', async () => {
  renderPage(); await selectFollower();
  fireEvent.click(screen.getByRole('button', { name: /All clusters/ }));
  expect(screen.getByText(/Open formation/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('tab', { name: 'Side' }));
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled(); expect(publishSwarmConfigResponse).not.toHaveBeenCalled();
});

test('aircraft acknowledgements distinguish unreachable from applied', async () => {
  getSwarmDesignStatusResponse.mockResolvedValue({ data: { revision: 'revision-1', nodes: [
    { hw_id: '1', status: 'applied' }, { hw_id: '2', status: 'not_reachable' },
  ] } });
  renderPage();
  const status = await screen.findByLabelText('Aircraft formation acknowledgement');
  expect(status).toHaveTextContent('SCOUT · Applied');
  expect(status).toHaveTextContent('NET-LEADER · Unreachable');
  expect(status).not.toHaveTextContent('NET-LEADER · Applied');
});

test('Save to repo applies the draft and publishes the returned revision', async () => {
  renderPage(); await editNorth('8.25');
  fireEvent.click(publishButton());
  const dialog = await screen.findByRole('dialog', { name: 'Save plan to repository?' });
  fireEvent.click(within(dialog).getByRole('button', { name: 'Save to repo' }));
  await waitFor(() => expect(publishSwarmConfigResponse).toHaveBeenCalledWith('revision-2'));
  expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1);
  expect(saveSwarmConfigResponse.mock.invocationCallOrder[0]).toBeLessThan(publishSwarmConfigResponse.mock.invocationCallOrder[0]);
});

test('unreachable acknowledgement continues the entire Save to repo workflow', async () => {
  saveSwarmConfigResponse.mockRejectedValueOnce({ response: { data: { detail: {
    code: 'unavailable_confirmation_required', unavailable_hw_ids: ['2'],
  } } } });
  renderPage(); await editNorth(); fireEvent.click(publishButton());
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Save plan to repository?' })).getByRole('button', { name: 'Save to repo' }));
  const dialog = await screen.findByRole('dialog', { name: 'Some aircraft are unreachable' });
  expect(publishSwarmConfigResponse).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole('button', { name: 'Apply anyway' }));
  await waitFor(() => expect(publishSwarmConfigResponse).toHaveBeenCalledWith('revision-2'));
});

test('Reset draft is confirmed, local-only and undoable', async () => {
  renderPage(); await editNorth('9'); fireEvent.click(screen.getByRole('button', { name: 'Reset draft' }));
  const dialog = await screen.findByRole('dialog', { name: 'Reset draft?' });
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(9);
  fireEvent.click(within(dialog).getByRole('button', { name: 'Reset draft' }));
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(6);
  fireEvent.click(screen.getByRole('button', { name: 'Undo formation edit' }));
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(9);
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
});

test('Four views share the selected draft without dispatching or publishing', async () => {
  renderPage(); await editNorth('7');
  fireEvent.click(screen.getByRole('button', { name: 'Four views' }));
  for (const title of ['Top', 'Front', 'Side', '3D']) expect(screen.getByLabelText(`${title} panel`)).toBeVisible();
  expect(screen.getByRole('spinbutton', { name: 'offset_x metres' })).toHaveValue(7);
  fireEvent.click(screen.getByRole('button', { name: 'Expand Top view' }));
  expect(screen.getByLabelText('Front panel')).not.toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Restore four views' }));
  expect(screen.getByLabelText('Front panel')).toBeVisible();
  expect(saveSwarmConfigResponse).not.toHaveBeenCalled();
});

test('repository failure after Apply leaves a publication-only retry', async () => {
  const consoleError = jest.spyOn(console, 'error').mockImplementation(() => {});
  publishSwarmConfigResponse.mockRejectedValueOnce(new Error('Repository offline'));
  renderPage(); await editNorth('8'); fireEvent.click(publishButton());
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Save plan to repository?' })).getByRole('button', { name: 'Save to repo' }));
  await screen.findByText('Plan applied · Repository save failed');
  expect(applyButton()).toBeDisabled();
  fireEvent.click(publishButton());
  fireEvent.click(within(await screen.findByRole('dialog', { name: 'Save plan to repository?' })).getByRole('button', { name: 'Save to repo' }));
  await waitFor(() => expect(publishSwarmConfigResponse).toHaveBeenCalledTimes(2));
  expect(saveSwarmConfigResponse).toHaveBeenCalledTimes(1);
  consoleError.mockRestore();
});

test('missing names use hardware IDs and never invent a position ID', async () => {
  getFleetConfigResponse.mockResolvedValue({ data: [{ hw_id: 1 }, { hw_id: 2, pos_id: 9 }] });
  renderPage();
  expect(await screen.findByRole('button', { name: 'H1, leader origin' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'H2, formation position' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'H2, formation position' }));
  expect(screen.getByLabelText('Aircraft spacing')).toHaveTextContent('H2 · P9');
  fireEvent.click(screen.getByRole('button', { name: 'H1, leader origin' }));
  expect(screen.getByLabelText('Aircraft spacing')).not.toHaveTextContent('P1');
});
