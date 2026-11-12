import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import RuntimeLogsWorkspace from './RuntimeLogsWorkspace';
import useLogStream from '../../hooks/useLogStream';
import useLogSessions from '../../features/log-workspace/useLogSessions';
jest.mock('../../hooks/useLogStream');
jest.mock('../../features/log-workspace/useLogSessions');
jest.mock('./LogTable', () => ({ entries }) => <div data-testid="rows">{entries.map(entry => <p key={entry._id}>{entry.msg}</p>)}</div>);
beforeEach(() => {
  useLogStream.mockReturnValue({ entries: [{ _id: 'one', msg: 'Old warning', ts: '2026-11-12T09:00:00Z' }], connected: true, status: 'connected', pending: 0, discarded: 0, clear: jest.fn() });
  useLogSessions.mockReturnValue({ sessions: [], sessionId: '', listBusy: false, page: { lines: [], status: 'idle' }, pageNumber: 1, refresh: jest.fn(), next: jest.fn(), previous: jest.fn() });
});
test('search, all severities and time filters are accessible without an Ops/Dev mode', () => {
  render(<RuntimeLogsWorkspace tab="live" sourceLabel="GCS" context="test" registry={{}} now={Date.parse('2026-11-12T10:00:00Z')} />);
  expect(screen.queryByText('Developer')).not.toBeInTheDocument();
  expect(screen.getByRole('searchbox', { name: 'Search logs' })).toBeInTheDocument();
  fireEvent.change(screen.getByRole('combobox', { name: 'Minimum severity' }), { target: { value: 'DEBUG' } });
  expect(useLogStream).toHaveBeenLastCalledWith(expect.objectContaining({ level: 'DEBUG' }));
  fireEvent.change(screen.getByLabelText('Live time window'), { target: { value: '5m' } });
  expect(screen.queryByText('Old warning')).not.toBeInTheDocument();
});
test('session UTC range errors stay visible and block export instead of empty successful history', () => {
  render(<RuntimeLogsWorkspace tab="sessions" sourceLabel="GCS" context="test" registry={{}} now={Date.now()} />);
  fireEvent.change(screen.getByLabelText('After UTC'), { target: { value: 'not UTC' } });
  expect(screen.getByText('Invalid UTC range')).toBeInTheDocument();
  expect(useLogSessions).toHaveBeenLastCalledWith(expect.objectContaining({ queryError: expect.stringContaining('UTC') }));
});
