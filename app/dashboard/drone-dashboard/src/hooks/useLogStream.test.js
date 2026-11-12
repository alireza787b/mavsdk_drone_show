// src/hooks/useLogStream.test.js
import { renderHook, act } from '@testing-library/react';
import useLogStream from './useLogStream';

// Mock EventSource
class MockEventSource {
  constructor(url, options = undefined) {
    this.url = url;
    this.options = options;
    this.onopen = null;
    this.onmessage = null;
    this.onerror = null;
    this.listeners = {};
    MockEventSource.instances.push(this);
  }
  close() { this.closed = true; }
  addEventListener(name, callback) { this.listeners[name] = callback; }
}
MockEventSource.instances = [];

beforeEach(() => {
  MockEventSource.instances = [];
  global.EventSource = MockEventSource;
});

afterEach(() => {
  delete global.EventSource;
});

describe('useLogStream', () => {
  test('connects to SSE when enabled', () => {
    renderHook(() => useLogStream({ enabled: true }));
    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toContain('/api/logs/stream');
    expect(MockEventSource.instances[0].options).toEqual({ withCredentials: true });
  });

  test('does not connect when disabled', () => {
    renderHook(() => useLogStream({ enabled: false }));
    expect(MockEventSource.instances).toHaveLength(0);
  });

  test('closes connection on unmount', () => {
    const { unmount } = renderHook(() => useLogStream({ enabled: true }));
    const es = MockEventSource.instances[0];
    unmount();
    expect(es.closed).toBe(true);
  });

  test('clear empties entries', () => {
    const { result } = renderHook(() => useLogStream({ enabled: false }));
    act(() => { result.current.clear(); });
    expect(result.current.entries).toEqual([]);
  });

  test('preserves repeated messages with distinct native IDs and ignores only duplicate native IDs', () => {
    jest.useFakeTimers();
    const { result, unmount } = renderHook(() => useLogStream({ enabled: true }));
    const es = MockEventSource.instances[0], data = JSON.stringify({ msg: 'Repeated warning', level: 'WARNING' });
    act(() => { es.onopen(); es.onmessage({ data, lastEventId: 'epoch:1' }); es.onmessage({ data, lastEventId: 'epoch:2' }); es.onmessage({ data, lastEventId: 'epoch:2' }); jest.advanceTimersByTime(200); });
    expect(result.current.entries).toHaveLength(2);
    expect(result.current.entries[0]._id).not.toBe(result.current.entries[1]._id);
    unmount(); jest.useRealTimers();
  });

  test('freeze reports bounded pending overflow and resumes without claiming complete history', () => {
    jest.useFakeTimers();
    const { result, rerender, unmount } = renderHook(({ paused }) => useLogStream({ enabled: true, paused }), { initialProps: { paused: true } });
    const es = MockEventSource.instances[0];
    act(() => { for (let index = 0; index < 5002; index += 1) es.onmessage({ data: JSON.stringify({ msg: `row ${index}` }), lastEventId: `epoch:${index}` }); jest.advanceTimersByTime(200); });
    expect(result.current.entries).toHaveLength(0); expect(result.current.pending).toBe(5000); expect(result.current.discarded).toBe(2);
    rerender({ paused: false });
    expect(result.current.entries).toHaveLength(5000);
    unmount(); jest.useRealTimers();
  });

  test('named unavailable/gap metadata is not an invented message or aircraft health', () => {
    const { result } = renderHook(() => useLogStream({ enabled: true }));
    const es = MockEventSource.instances[0];
    act(() => { es.listeners.status({ type: 'status', data: JSON.stringify({ state: 'unavailable', coverage: 'unknown', reason: 'authorization_required' }) }); es.listeners.gap({ type: 'gap', data: JSON.stringify({ reason: 'stream_restarted', lost_count: null, history_complete: false }) }); });
    expect(result.current.status).toBe('offline'); expect(result.current.entries).toEqual([]); expect(result.current.coverage.gapCount).toBe(1);
  });

  test('an obsolete source cannot install new events or resolve the next source inspector identity', () => {
    jest.useFakeTimers();
    const { result, rerender, unmount } = renderHook(({ droneId }) => useLogStream({ enabled: true, droneId }), { initialProps: { droneId: '1' } });
    const old = MockEventSource.instances[0]; rerender({ droneId: '2' });
    act(() => { old.onmessage({ data: JSON.stringify({ msg: 'Old aircraft' }), lastEventId: 'epoch:1' }); jest.advanceTimersByTime(200); });
    expect(result.current.entries).toEqual([]); expect(old.closed).toBe(true);
    unmount(); jest.useRealTimers();
  });
});
