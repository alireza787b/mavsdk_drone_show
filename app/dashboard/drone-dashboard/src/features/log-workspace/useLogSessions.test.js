import { act, renderHook, waitFor } from '@testing-library/react';
import useLogSessions from './useLogSessions';
import * as service from '../../services/logService';
jest.mock('../../services/logService', () => ({ getSessions: jest.fn(), getDroneSessions: jest.fn(), getSessionContent: jest.fn(), getDroneSessionContent: jest.fn() }));
const page = (source, index = 0) => ({ lines: [{ ts: '2026-11-12T10:00:00Z', level: 'WARNING', msg: source }], entry_offsets: [index], snapshot_id: `snapshot-${source}`, has_more: index === 0, next_cursor: index === 0 ? 'cursor-1' : null, coverage: { malformed_records: 1 } });
beforeEach(() => {
  jest.clearAllMocks(); service.getSessions.mockResolvedValue({ sessions: [{ session_id: 'gcs-session' }] });
  service.getDroneSessions.mockResolvedValue({ sessions: [{ session_id: 'drone-session' }] });
  service.getSessionContent.mockImplementation(async (id, query) => page('GCS', query.cursor ? 1 : 0));
  service.getDroneSessionContent.mockResolvedValue(page('H2'));
});
test('server filters precede bounded cursor paging and IDs include source/session/snapshot/offset', async () => {
  const { result } = renderHook(() => useLogSessions({ droneId: null, enabled: true, query: { level: 'WARNING', search: 'loss', until: '2026-11-12T12:00:00Z' } }));
  await waitFor(() => expect(result.current.page.status).toBe('loaded'));
  const first = result.current.page.lines[0]._id;
  expect(service.getSessionContent).toHaveBeenLastCalledWith('gcs-session', { level: 'WARNING', search: 'loss', until: '2026-11-12T12:00:00Z', limit: 500 }, expect.any(Object));
  act(() => result.current.next());
  await waitFor(() => expect(result.current.pageNumber).toBe(2));
  await waitFor(() => expect(result.current.page.status).toBe('loaded'));
  expect(service.getSessionContent).toHaveBeenLastCalledWith('gcs-session', expect.objectContaining({ cursor: 'cursor-1', limit: 500 }), expect.any(Object));
  expect(result.current.page.lines).toHaveLength(1); expect(result.current.page.lines[0]._id).not.toBe(first);
});
test('late history and failed replacement never install previous-source rows', async () => {
  let resolve;
  service.getSessionContent.mockImplementation(() => new Promise(done => { resolve = done; }));
  const { result, rerender } = renderHook(({ id }) => useLogSessions({ droneId: id, enabled: true, query: {} }), { initialProps: { id: null } });
  await waitFor(() => expect(service.getSessionContent).toHaveBeenCalled());
  rerender({ id: '2' });
  await waitFor(() => expect(result.current.page.lines[0]?.msg).toBe('H2'));
  act(() => resolve(page('OLD GCS')));
  expect(result.current.page.lines[0].msg).toBe('H2');
  service.getDroneSessionContent.mockRejectedValue(new Error('unavailable'));
  act(() => result.current.refresh());
  await waitFor(() => expect(result.current.page.status).toBe('error'));
  expect(result.current.page.lines).toEqual([]);
});
