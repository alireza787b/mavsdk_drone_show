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
    MockEventSource.instances.push(this);
  }
  close() { this.closed = true; }
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
});
