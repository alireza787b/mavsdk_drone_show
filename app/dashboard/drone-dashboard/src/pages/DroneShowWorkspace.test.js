import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import DroneShowWorkspace from './DroneShowWorkspace';

let mockCount = 1;
jest.mock('../components/DeviationView', () => () => <div>Layout evidence</div>);
jest.mock('../components/VisualizationSection', () => () => <div>Trajectory previews</div>);
jest.mock('../components/ImportSection', () => () => <div>Import</div>);
jest.mock('../components/ExportSection', () => () => <div>Export</div>);
jest.mock('../components/SequentialReturnControl', () => () => <div>Managed Return</div>);
jest.mock('../components/ShowPlotImage', () => () => <div>Paths</div>);
jest.mock('../hooks/useGcsResourcePolling', () => ({ __esModule: true, default: (key) => {
  const fleet = Array.from({ length: mockCount }, (_, index) => ({ hw_id: String(index + 1), pos_id: String(index + 1), name: `Aircraft ${index + 1}`, state: 'Hold', telemetry_fresh: true, ready_to_arm: true, armed: false }));
  if (key === 'showOperationStatus') return { data: { fleet, state: 'idle', timestamp: 1000 } };
  if (key === 'showWorkspace') return { data: { package: { available: true, position_ids: fleet.map(d => d.pos_id), drone_count: mockCount }, validation: { validation_status: 'WARNING', findings: [{ title: 'Ground-level trajectory samples', detail: 'Includes launch/landing.' }] } } };
  if (key === 'origin') return { data: { lat: 1, lon: 2 } };
  return { data: { deviations: Object.fromEntries(fleet.map(d => [d.hw_id, { status: 'ok' }])) } };
} }));

beforeAll(() => { Element.prototype.scrollIntoView = jest.fn(); });

test.each([1, 50, 100])('operator evidence remains searchable for %i aircraft', count => {
  mockCount = count;
  render(<MemoryRouter><DroneShowWorkspace /></MemoryRouter>);
  expect(screen.getByRole('heading', { name: `Aircraft · ${count}/${count} live` })).toBeInTheDocument();
  expect(screen.getAllByRole('row')).toHaveLength(count + 1);
  fireEvent.change(screen.getByRole('searchbox'), { target: { value: `Aircraft ${count}` } });
  expect(screen.getAllByRole('row')).toHaveLength(2);
  fireEvent.click(screen.getByText('View findings'));
  expect(document.getElementById('trajectory-analysis').open).toBe(true);
  expect(screen.getByText('Includes launch/landing.')).toBeInTheDocument();
  expect(screen.queryByText('FAIL · Safety issue: CAUTION')).not.toBeInTheDocument();
});
