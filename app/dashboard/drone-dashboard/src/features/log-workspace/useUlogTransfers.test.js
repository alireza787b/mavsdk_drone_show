import { act, renderHook, waitFor } from '@testing-library/react';
import useUlogTransfers from './useUlogTransfers';
import * as service from '../../services/logService';
jest.mock('../../services/logService', () => ({ createDroneUlogDownloadJob: jest.fn(), getDroneUlogDownloadJob: jest.fn(), getDroneUlogDownloadRequest: jest.fn(), deleteDroneUlogDownloadJob: jest.fn() }));
const KEY = 'ulog-test';
const job = status => ({ job_id: 'signed-handle', hw_id: '1', log_id: 7, status, size_bytes: 1024, updated_at: 1, expires_at: Date.now() + 60000 });
beforeEach(() => {
  jest.clearAllMocks(); localStorage.clear();
  Object.defineProperty(window, 'crypto', { configurable: true, value: { randomUUID: () => '11111111-1111-4111-8111-111111111111' } });
});
afterEach(() => { jest.useRealTimers(); });
test('persists request before POST, locks pending creation, and exposes immediately ready handles', async () => {
  let resolve;
  service.createDroneUlogDownloadJob.mockImplementation((id, logId, options) => {
    expect(JSON.parse(localStorage.getItem(KEY))[0].requestId).toBe(options.requestId);
    return new Promise(done => { resolve = done; });
  });
  const { result } = renderHook(() => useUlogTransfers(KEY));
  let pending;
  act(() => { pending = result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  act(() => { result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  expect(service.createDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
  await act(async () => { resolve({ job: job('ready') }); await pending; });
  expect(result.current.records[0].job.status).toBe('ready');
  expect(result.current.pending).toBe(false);
});
test('lost create response survives remount and only GET recovers its original identity', async () => {
  service.createDroneUlogDownloadJob.mockRejectedValue(new Error('response lost'));
  const first = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { await first.result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  const saved = JSON.parse(localStorage.getItem(KEY))[0]; first.unmount();
  service.getDroneUlogDownloadRequest.mockResolvedValue({ request_id: saved.requestId, status: 'accepted', job: job('ready') });
  const second = renderHook(() => useUlogTransfers(KEY));
  await waitFor(() => expect(second.result.current.records).toHaveLength(1));
  await act(async () => { await second.result.current.check(second.result.current.records[0]); });
  expect(service.getDroneUlogDownloadRequest).toHaveBeenCalledWith('1', saved.requestId);
  expect(service.createDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
  expect(second.result.current.records[0].job.status).toBe('ready');
});
test('polling is sequential and expired is terminal', async () => {
  jest.useFakeTimers();
  localStorage.setItem(KEY, JSON.stringify([{ requestId: 'request', droneId: '1', logId: 7, job: job('queued') }]));
  service.getDroneUlogDownloadJob.mockResolvedValue({ job: job('expired') });
  const { result, unmount } = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { jest.advanceTimersByTime(1500); });
  expect(service.getDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
  expect(result.current.records[0].job.status).toBe('expired');
  await act(async () => { jest.advanceTimersByTime(10000); });
  expect(service.getDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
  unmount(); jest.useRealTimers();
});
test('unsupported recovery identity fails before any native create', async () => {
  Object.defineProperty(window, 'crypto', { configurable: true, value: {} });
  const { result } = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { await result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  expect(result.current.error).toContain('cannot create a recovery identity');
  expect(service.createDroneUlogDownloadJob).not.toHaveBeenCalled();
});
test('only request-bound explicit rejection proof releases the creation lock', async () => {
  service.createDroneUlogDownloadJob.mockImplementation(async (id, logId, { requestId }) => {
    throw Object.assign(new Error('Fixture rejection'), { response: { status: 409, data: { detail: { creation_status: 'rejected', request_id: requestId, message: 'No configured endpoint; not handed off.' } } } });
  });
  const { result } = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { await result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  expect(result.current.records[0].creationStatus).toBe('rejected'); expect(result.current.pending).toBe(false);
});
test('generic HTTP rejection is still uncertain until a matching receipt proves otherwise', async () => {
  service.createDroneUlogDownloadJob.mockRejectedValue({ response: { status: 409, data: { detail: 'Conflict without pre-handoff proof' } } });
  const { result } = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { await result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  expect(result.current.pending).toBe(true);
  const record = result.current.records[0];
  service.getDroneUlogDownloadRequest.mockResolvedValue({ request_id: record.requestId, status: 'rejected', job: null, error: 'Proven not handed off.' });
  await act(async () => { await result.current.check(record); });
  expect(result.current.pending).toBe(false); expect(result.current.records[0].creationStatus).toBe('rejected');
  expect(service.createDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
});
test('lost create response can recover a proven Not started receipt without replay', async () => {
  service.createDroneUlogDownloadJob.mockRejectedValue(new Error('Response lost'));
  const { result } = renderHook(() => useUlogTransfers(KEY));
  await act(async () => { await result.current.prepare({ droneId: '1', logId: 7, aircraftLabel: 'ALPHA · H1' }); });
  expect(result.current.pending).toBe(true);
  const record = result.current.records[0];
  service.getDroneUlogDownloadRequest.mockResolvedValue({ request_id: record.requestId, status: 'rejected', job: null, error: 'Pre-handoff endpoint unavailable.' });
  await act(async () => { await result.current.check(record); });
  expect(result.current.pending).toBe(false);
  expect(result.current.records[0].creationStatus).toBe('rejected');
  expect(service.createDroneUlogDownloadJob).toHaveBeenCalledTimes(1);
});
