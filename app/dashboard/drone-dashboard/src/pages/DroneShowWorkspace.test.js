import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DroneShowWorkspace from './DroneShowWorkspace';
import { sendDroneCommand } from '../services/droneApiService';

jest.mock('../contexts/CommandActivityContext', () => ({ useCommandActivity: () => ({ commandLifecycleCallbacks: {} }) }));
jest.mock('../services/droneApiService', () => ({ ...jest.requireActual('../services/droneApiService'), sendDroneCommand: jest.fn() }));
jest.mock('../utilities/commandLifecycleFeedback', () => ({ trackCommandReceipt: jest.fn() }));

let mockCount = 1;
jest.mock('../components/DeviationView', () => () => <div>Layout evidence</div>);
jest.mock('../components/VisualizationSection', () => () => <div>Trajectory previews</div>);
jest.mock('../components/ImportSection', () => () => <div>Import</div>);
jest.mock('../components/ExportSection', () => () => <div>Export</div>);
jest.mock('../components/SequentialReturnControl', () => () => <div>Managed Return</div>);
jest.mock('../components/ShowPlotImage', () => () => <div>Paths</div>);
jest.mock('../hooks/useGcsResourcePolling', () => ({ __esModule: true, default: (key) => {
  const fleet = Array.from({ length: mockCount }, (_, index) => ({ hw_id: String(index + 1), pos_id: String(index + 1), name: `Aircraft ${index + 1}`, state: 'Hold', telemetry_fresh: true, ready_to_arm: true, armed: false }));
  if (key === 'showOperationStatus?mission_type=1') return { receivedAt: performance.now(), data: { fleet, state: 'idle', timestamp: Date.now() } };
  if (key === 'showWorkspace') return { receivedAt: performance.now(), data: { package: { available: true, position_ids: fleet.map(d => d.pos_id), drone_count: mockCount }, validation: { validation_status: 'WARNING', findings: [{ title: 'High trajectory speed', detail: '18 m/s; verify aircraft capability.' }] } } };
  if (key === 'origin') return { receivedAt: performance.now(), data: { lat: 1, lon: 2 } };
  return { receivedAt: performance.now(), data: { deviations: Object.fromEntries(fleet.map(d => [d.hw_id, { status: 'ok' }])) } };
} }));

beforeAll(() => { Element.prototype.scrollIntoView = jest.fn(); });
beforeEach(() => { sessionStorage.clear(); jest.clearAllMocks(); sendDroneCommand.mockResolvedValue({ accepted_for_tracking: true, command_id: 'show-1' }); });

test.each([1, 50, 100])('operator evidence remains searchable for %i aircraft', count => {
  mockCount = count;
  render(<MemoryRouter><DroneShowWorkspace runtimeMode="sitl" /></MemoryRouter>);
  expect(screen.getByLabelText('Start timing')).toHaveValue('now');
  expect(screen.getByRole('heading', { name: `Aircraft · ${count}/${count} live` })).toBeInTheDocument();
  expect(screen.getAllByRole('row')).toHaveLength(count + 1);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: `Aircraft ${count}` } });
  expect(screen.getAllByRole('row')).toHaveLength(2);
  fireEvent.click(screen.getByText('View findings'));
  expect(document.getElementById('trajectory-analysis').open).toBe(true);
  expect(screen.getByText('18 m/s; verify aircraft capability.')).toBeInTheDocument();
  expect(screen.queryByText('FAIL · Safety issue: CAUTION')).not.toBeInTheDocument();
});

test('filtering never retargets and a selected subset can review an immediate launch', () => {
  mockCount = 3;
  render(<MemoryRouter><DroneShowWorkspace runtimeMode="sitl" /></MemoryRouter>);
  fireEvent.click(screen.getByRole('checkbox', { name: 'Select Aircraft 3 H3' }));
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Aircraft 3' } });
  expect(screen.getByText('2 selected · 2 hidden')).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Start timing'), { target: { value: 'now' } });
  fireEvent.click(screen.getByRole('button', { name: 'Launch show' }));
  expect(screen.getByText('Aircraft 1 · Aircraft 2')).toBeInTheDocument();
  expect(screen.getAllByText(/Synchronized start after aircraft checks/).length).toBeGreaterThan(0);
  expect(sendDroneCommand).not.toHaveBeenCalled();
});
