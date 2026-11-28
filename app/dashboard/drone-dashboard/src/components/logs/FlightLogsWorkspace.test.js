import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import FlightLogsWorkspace from './FlightLogsWorkspace';
import UlogTransferActivity from './UlogTransferActivity';
import { UlogTransferCenter, UlogTransferProvider } from './UlogTransferCenter';
import { getBackendURL } from '../../config/apiConfig';
import { useUlogTransferContext } from '../../features/log-workspace/UlogTransferContext';
import * as service from '../../services/logService';
jest.mock('../../services/logService', () => ({
  getDroneUlogFiles: jest.fn(), getDroneUlogPolicy: jest.fn(), getDroneUlogSummary: jest.fn(), getVerifiedUlogSummary: jest.fn(),
  summarizeUploadedUlog: jest.fn(), eraseAllDroneUlogs: jest.fn(),
  listVerifiedUlogCopies: jest.fn(), getDroneUlogDownloadRequest: jest.fn(),
  createDroneUlogDownloadJob: jest.fn(), deleteDroneUlogDownloadJob: jest.fn(),
  buildDroneUlogDownloadURL: (id, job) => `/fixture/${id}/${job}`,
}));
const STORAGE_KEY = `mds:ulog-transfers:v1:${getBackendURL()}:test:browser-session`;
const transfers = () => ({ records: [], pending: false, busy: false, start: jest.fn(async () => true), check: jest.fn(), remove: jest.fn(), browserRequested: jest.fn() });
beforeEach(() => {
  jest.clearAllMocks();
  localStorage.clear();
  service.listVerifiedUlogCopies.mockResolvedValue([]);
  service.getDroneUlogFiles.mockResolvedValue({ files: [{ id: 7, size_bytes: 1024, date_utc: '2026-11-12T10:00:00Z' }], ulog_capability: { available: true } });
  service.getDroneUlogPolicy.mockResolvedValue({ policy: { download_supported: true, erase_all_supported: true, download_requires_disarmed: true } });
});
function FlightLogs(props) {
  const ledger = useUlogTransferContext();
  return <><UlogTransferCenter userRole={props.userRole} /><FlightLogsWorkspace {...props} transfers={ledger} /></>;
}

const renderWithTransfers = props => render(<UlogTransferProvider runtimeMode="test" userRole={props.userRole}><FlightLogs {...props} /></UlogTransferProvider>);

test('viewer can inspect/derive a summary but cannot prepare or erase; absent metrics remain unknown', async () => {
  service.getDroneUlogSummary.mockResolvedValue({ parsed: true, parser: { status: 'ok' }, duration_sec: 42,
    duration_evidence: { source: 'requested_topic_timestamps', lower_bound: true, timestamp_scan_complete: false }, commands: { vehicle_command: { samples: 3 } } });
  renderWithTransfers({ droneId: '1', sourceLabel: 'ALPHA · H1', userRole: 'viewer' });
  const summary = await screen.findByRole('button', { name: 'View summary for log 7' });
  expect(screen.queryByRole('button', { name: 'Get log 7' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Erase onboard logs' })).not.toBeInTheDocument();
  fireEvent.click(summary);
  expect(await screen.findByText('42 s · partial / lower bound')).toBeInTheDocument();
  const metrics = within(screen.getByRole('region', { name: 'Flight log summary' }));
  const terms = metrics.getAllByRole('term');
  const values = metrics.getAllByRole('definition');
  expect(values[terms.indexOf(metrics.getByText('Acknowledgment samples'))]).toHaveTextContent('Unknown');
  expect(values[terms.indexOf(metrics.getByText('Command samples'))]).toHaveTextContent('3');
});
test('explicit preparation binds the selected file and aircraft, not an inventory index', async () => {
  const ledger = transfers();
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="operator" transfers={ledger} />);
  fireEvent.click(await screen.findByRole('button', { name: 'Get log 7' }));
  expect(ledger.start).toHaveBeenCalledWith({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1',
    expectedSize: 1024, logDate: '2026-11-12T10:00:00Z', wantsSummary: false });
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
  await screen.findByRole('button', { name: 'Get log 7' });
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
  renderWithTransfers({ droneId: null, sourceLabel: "GCS", userRole: "operator" });
  fireEvent.change(screen.getByLabelText('Open local ULog file'), { target: { files: [file] } });
  expect(await screen.findByText('Parser unavailable')).toBeInTheDocument();
  expect(service.summarizeUploadedUlog).toHaveBeenCalledWith(file);
  expect(service.getDroneUlogFiles).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Log transfers' }));
  expect(await screen.findByText('Parser unavailable')).toBeInTheDocument();
});
test('an unobserved or failed catalog is never reported as zero onboard files', async () => {
  let reject;
  service.getDroneUlogFiles.mockImplementation(() => new Promise((resolve, fail) => { reject = fail; }));
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="operator" transfers={transfers()} />);
  expect(screen.getByText('Loading logs…')).toBeInTheDocument();
  expect(screen.queryByText(/^0 files/)).not.toBeInTheDocument();
  reject(new Error('Inventory transport unavailable'));
  expect(await screen.findAllByText('Aircraft logs unavailable')).not.toHaveLength(0);
  expect(screen.queryByText(/^0 files/)).not.toBeInTheDocument();
});

test('a verified copy replaces Get log with one-click Save file', async () => {
  const ledger = { ...transfers(), records: [{
    requestId: 'request', droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1',
    logDate: '2026-11-12T10:00:00Z', verified: true,
    job: { job_id: 'signed', status: 'ready', expires_at: Date.now() + 60000 },
  }] };
  render(<FlightLogsWorkspace droneId="1" sourceLabel="ALPHA · H1" userRole="operator" transfers={ledger} />);
  expect(await screen.findByRole('link', { name: 'Save file' })).toHaveAttribute('href', '/fixture/1/signed');
  expect(screen.queryByRole('button', { name: 'Get log 7' })).not.toBeInTheDocument();
});

test('Remove GCS copy waits for confirmation before deleting', async () => {
  const record = {
    requestId: 'request', droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1', verified: true,
    job: { job_id: 'signed', status: 'ready', expires_at: Date.now() + 60000 },
  };
  const ledger = { ...transfers(), records: [record] };
  render(<UlogTransferActivity transfers={ledger} userRole="operator" now={Date.now()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Remove GCS copy' }));
  expect(ledger.remove).not.toHaveBeenCalled();
  fireEvent.click(within(screen.getByRole('dialog', { name: 'Remove GCS copy?' })).getByRole('button', { name: 'Remove' }));
  expect(ledger.remove).toHaveBeenCalledWith(record);
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

test('dismissed retained notices stay hidden after remount and copies remain available through Flight Logs', async () => {
  const copy = id => ({
    request_id: `receipt-${id}`,
    job: { job_id: `copy-${id}`, hw_id: '1', log_id: id, status: 'ready', expires_at: Date.now() + 60000 },
  });
  const copies = [copy(7), copy(8)];
  service.listVerifiedUlogCopies.mockResolvedValue(copies);
  const props = { droneId: null, sourceLabel: 'GCS', userRole: 'operator' };
  const { unmount } = renderWithTransfers(props);
  fireEvent.click(await screen.findByRole('button', { name: 'ULog transfers' }));
  const save = screen.getAllByRole('link', { name: 'Save file' })[0];
  save.addEventListener('click', event => event.preventDefault(), { once: true });
  fireEvent.click(save);
  expect(screen.getByRole('button', { name: 'ULog transfers' })).toHaveTextContent('Save started');
  const recovery = localStorage.getItem(STORAGE_KEY);

  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  expect(localStorage.getItem(STORAGE_KEY)).toBe(recovery);
  expect(service.deleteDroneUlogDownloadJob).not.toHaveBeenCalled();
  unmount();

  renderWithTransfers(props);
  const open = screen.getByRole('button', { name: 'Log transfers' });
  fireEvent.click(open);
  const panel = screen.getByRole('region', { name: 'ULog transfers' });
  expect(within(panel).getByRole('link', { name: 'Save again' })).toHaveAttribute('href', '/fixture/1/copy-7');
  expect(await within(panel).findByRole('link', { name: 'Save file' })).toHaveAttribute('href', '/fixture/1/copy-8');
  fireEvent.click(open);
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();

  service.listVerifiedUlogCopies.mockResolvedValue([copy(9), ...copies]);
  fireEvent(window, new Event('focus'));
  expect(await screen.findByRole('button', { name: 'ULog transfers' })).toHaveTextContent('Ready to save');
  expect(service.createDroneUlogDownloadJob).not.toHaveBeenCalled();
});

test('dismiss hides settled notices while unconfirmed receipts and newly observed failures stay visible', async () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify([
    { requestId: 'unconfirmed', droneId: '1', logId: 7, aircraftLabel: 'H1', verified: true,
      job: null, creationStatus: 'unknown', error: 'Waiting for receipt' },
    { requestId: 'rejected', droneId: '1', logId: 8, aircraftLabel: 'H1', verified: true,
      job: null, creationStatus: 'rejected', error: 'Could not read log' },
  ]));
  service.getDroneUlogDownloadRequest.mockResolvedValue({
    request_id: 'unconfirmed',
    status: 'accepted',
    job: { job_id: 'failed-job', hw_id: '1', log_id: 7, status: 'failed', error: 'Aircraft disconnected' },
  });
  renderWithTransfers({ droneId: null, sourceLabel: 'GCS', userRole: 'operator' });

  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  const widget = screen.getByRole('button', { name: 'ULog transfers' });
  expect(widget).toHaveTextContent('Reconnecting');
  expect(screen.queryByRole('button', { name: 'Dismiss transfer notice' })).not.toBeInTheDocument();
  fireEvent.click(widget);
  fireEvent.click(screen.getByRole('button', { name: 'Check now' }));
  await waitFor(() => expect(widget).toHaveTextContent('Transfer failed'));
  expect(service.getDroneUlogDownloadRequest).toHaveBeenCalledWith('1', 'unconfirmed');

  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Log transfers' }));
  expect(await screen.findAllByRole('button', { name: 'Retry aircraft read' })).toHaveLength(2);
  expect(service.createDroneUlogDownloadJob).not.toHaveBeenCalled();
});

test('dismissed summary-first transfers do not replay summaries after remount', async () => {
  const report = id => ({
    requestId: `receipt-${id}`, droneId: '1', logId: id, aircraftLabel: 'H1', verified: true, wantsSummary: true,
    job: { job_id: `copy-${id}`, hw_id: '1', log_id: id, status: 'ready', expires_at: Date.now() + 60000 },
  });
  const setReports = reports => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(reports));
    service.listVerifiedUlogCopies.mockResolvedValue(reports.map(({ requestId, job }) => ({ request_id: requestId, job })));
  };
  const dismissed = report(7);
  setReports([dismissed]);
  service.getVerifiedUlogSummary.mockResolvedValue({ parsed: false, parser: { status: 'unavailable', error: 'Example summary' } });
  const props = { droneId: null, sourceLabel: 'GCS', userRole: 'operator' };
  const { unmount } = renderWithTransfers(props);
  await waitFor(() => expect(service.getVerifiedUlogSummary).toHaveBeenCalledWith('1', 'copy-7'));
  const widget = screen.getByRole('button', { name: 'ULog transfers' });
  await waitFor(() => expect(widget).toHaveTextContent('Ready to save'));
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  unmount();

  const { unmount: closeReopened } = renderWithTransfers(props);
  await waitFor(() => expect(service.listVerifiedUlogCopies).toHaveBeenCalledTimes(2));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  expect(service.getVerifiedUlogSummary).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Log transfers' }));
  fireEvent.click(await screen.findByRole('button', { name: 'View summary' }));
  expect(await screen.findByText('Example summary')).toBeInTheDocument();
  expect(service.getVerifiedUlogSummary).toHaveBeenCalledTimes(2);
  closeReopened();

  setReports([dismissed, report(8)]);
  renderWithTransfers(props);
  await waitFor(() => expect(service.getVerifiedUlogSummary).toHaveBeenLastCalledWith('1', 'copy-8'));
  expect(service.getVerifiedUlogSummary).toHaveBeenCalledTimes(3);
});

test('a standalone recovery error can be dismissed without changing the stored receipts', async () => {
  const invalid = 'unreadable receipts';
  localStorage.setItem(STORAGE_KEY, invalid);
  renderWithTransfers({ droneId: null, sourceLabel: 'GCS', userRole: 'operator' });
  expect(await screen.findByRole('button', { name: 'ULog transfers' })).toHaveTextContent('Transfer issue');
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss transfer notice' }));
  expect(screen.queryByRole('button', { name: 'ULog transfers' })).not.toBeInTheDocument();
  expect(localStorage.getItem(STORAGE_KEY)).toBe(invalid);
});
