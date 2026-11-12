import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FlightLogsWorkspace from './FlightLogsWorkspace';
import UlogTransferActivity from './UlogTransferActivity';
import * as service from '../../services/logService';
jest.mock('../../services/logService', () => ({ getDroneUlogFiles: jest.fn(), getDroneUlogPolicy: jest.fn(), getDroneUlogSummary: jest.fn(), summarizeUploadedUlog: jest.fn(), eraseAllDroneUlogs: jest.fn(), buildDroneUlogDownloadURL: (id, job) => `/fixture/${id}/${job}` }));
const transfers = () => ({ records: [], pending: false, busy: false, prepare: jest.fn(async () => true), check: jest.fn(), remove: jest.fn(), browserRequested: jest.fn() });
beforeEach(() => {
  jest.clearAllMocks();
  service.getDroneUlogFiles.mockResolvedValue({ files: [{ id: 7, size_bytes: 1024, date_utc: '2026-11-12T10:00:00Z' }], ulog_capability: { available: true } });
  service.getDroneUlogPolicy.mockResolvedValue({ policy: { download_supported: true, erase_all_supported: true, download_requires_disarmed: true } });
});
test('viewer can inspect/derive a summary but cannot prepare or erase; absent metrics remain unknown', async () => {
  service.getDroneUlogSummary.mockResolvedValue({ parsed: true, parser: { status: 'ok' }, duration_sec: 42,
    duration_evidence: { source: 'requested_topic_timestamps', lower_bound: true, timestamp_scan_complete: false }, commands: { vehicle_command: { samples: 3 } } });
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="viewer" transfers={transfers()} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect flight log 7' }));
  const inspector = screen.getByRole('dialog', { name: 'Flight log 7' });
  expect(within(inspector).getByRole('button', { name: 'Prepare download' })).toBeDisabled();
  expect(screen.queryByRole('button', { name: 'Erase onboard logs' })).not.toBeInTheDocument();
  fireEvent.click(within(inspector).getByRole('button', { name: 'Summary', exact: true }));
  expect(await screen.findByText('42 s · partial / lower bound')).toBeInTheDocument();
  expect(screen.getByText('Acknowledgment samples').nextElementSibling).toHaveTextContent('Unknown');
  expect(screen.getByText('Command samples').nextElementSibling).toHaveTextContent('3');
});
test('explicit preparation binds the selected file and aircraft, not an inventory index', async () => {
  const ledger = transfers();
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="operator" transfers={ledger} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Inspect flight log 7' }));
  fireEvent.click(screen.getByRole('dialog').querySelector('.operator-confirm-dialog__actions button:last-child'));
  await waitFor(() => expect(ledger.prepare).toHaveBeenCalledWith({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }));
  expect(service.eraseAllDroneUlogs).not.toHaveBeenCalled();
});
test('immediately ready job offers an explicit Save link without claiming local persistence', () => {
  const ledger = { ...transfers(), records: [{ requestId: 'request', droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1', job: { job_id: 'signed', status: 'ready', expires_at: Date.now() + 60000 } }] };
  render(<UlogTransferActivity transfers={ledger} userRole="operator" now={Date.now()} />);
  expect(screen.getByRole('link', { name: 'Save file' })).toHaveAttribute('href', '/fixture/1/signed');
  expect(ledger.browserRequested).not.toHaveBeenCalled();
  expect(screen.queryByText(/safe to power off/i)).not.toBeInTheDocument();
});
test('admin erase is separately confirmed, pending-locked, frozen, and acceptance is not verified empty', async () => {
  let resolve;
  service.eraseAllDroneUlogs.mockImplementation(() => new Promise(done => { resolve = done; }));
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="admin" transfers={transfers()} />);
  await screen.findByRole('button', { name: 'Inspect flight log 7' });
  fireEvent.click(screen.getByText('Maintenance'));
  fireEvent.click(screen.getByRole('button', { name: 'Erase onboard logs', exact: true }));
  const review = screen.getByRole('dialog', { name: 'Erase onboard logs?' });
  expect(within(review).getByRole('button', { name: 'Erase onboard logs' })).toBeDisabled();
  fireEvent.change(within(review).getByRole('textbox', { name: 'Confirm aircraft erase' }), { target: { value: 'ERASE H1' } });
  fireEvent.click(within(review).getByRole('button', { name: 'Erase onboard logs' }));
  expect(service.eraseAllDroneUlogs).toHaveBeenCalledWith('1');
  expect(within(review).getByRole('button', { name: /Working|Erasing|Applying|Erase onboard logs|Processing/ })).toBeDisabled();
  resolve({ status: 'accepted' });
  expect(await screen.findByText(/Empty inventory has not been verified/)).toBeInTheDocument();
  expect(service.eraseAllDroneUlogs).toHaveBeenCalledTimes(1);
});
test('local file uses only the bounded upload summary endpoint', async () => {
  const file = new File(['ULog'], 'example.ulg');
  service.summarizeUploadedUlog.mockResolvedValue({ parsed: false, parser: { status: 'unavailable', error: 'Parser unavailable' } });
  render(<FlightLogsWorkspace droneId={null} sourceLabel="GCS" userRole="operator" transfers={transfers()} />);
  fireEvent.change(screen.getByLabelText('Open local ULog file'), { target: { files: [file] } });
  expect(await screen.findByText('Parser unavailable')).toBeInTheDocument();
  expect(service.summarizeUploadedUlog).toHaveBeenCalledWith(file);
  expect(service.getDroneUlogFiles).not.toHaveBeenCalled();
});
test('an unobserved or failed catalog is never reported as zero onboard files', async () => {
  let reject;
  service.getDroneUlogFiles.mockImplementation(() => new Promise((resolve, fail) => { reject = fail; }));
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="operator" transfers={transfers()} />);
  expect(screen.getByText('Loading inventory')).toBeInTheDocument();
  expect(screen.queryByText(/^0 files/)).not.toBeInTheDocument();
  reject(new Error('Inventory transport unavailable'));
  expect(await screen.findAllByText('Inventory unavailable')).not.toHaveLength(0);
  expect(screen.queryByText(/^0 files/)).not.toBeInTheDocument();
});
