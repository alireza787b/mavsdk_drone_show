import { act, cleanup, renderHook } from '@testing-library/react';
import useFleetResources, { mergeFleetResources, useFleetResource } from './useFleetResources';
import { buildFleetViewModel } from './fleetViewModel';
import { DRONE_RUNTIME_CLOCK_PROP, attachDroneRuntimeClock } from '../../constants/fieldMappings';
import { fetchGcsResource, getFleetConfigResponse, getFleetTelemetryResponse, GCS_ROUTE_KEYS } from '../../services/gcsApiService';

jest.mock('../../services/gcsApiService', () => ({
  ...jest.requireActual('../../services/gcsApiService'),
  fetchGcsResource: jest.fn(), getFleetConfigResponse: jest.fn(), getFleetTelemetryResponse: jest.fn(),
}));

const NOW = 1780000000000;
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve(); }); };
const advance = async (milliseconds) => { await act(async () => { jest.advanceTimersByTime(milliseconds); }); };
let hidden;

beforeEach(() => {
  jest.clearAllMocks();
  jest.useFakeTimers();
  jest.setSystemTime(NOW);
  hidden = jest.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  getFleetConfigResponse.mockReset().mockResolvedValue({ data: [{ hw_id: '1' }] });
  getFleetTelemetryResponse.mockReset().mockResolvedValue({ data: { telemetry: { 1: { hw_id: '1', update_time: NOW / 1000, telemetry_available: true } } }, headers: { 'x-mds-server-time': NOW } });
  fetchGcsResource.mockReset().mockImplementation((route) => Promise.resolve({ data: route === GCS_ROUTE_KEYS.swarmConfig ? { assignments: [] } : { nodes: {} } }));
});

afterEach(() => {
  cleanup();
  hidden.mockRestore();
  jest.useRealTimers();
});

describe('sequential resource ownership', () => {
  test('polling and repeated focus cannot overlap a pending request; unmount aborts it', async () => {
    const request = deferred();
    const load = jest.fn(() => request.promise);
    const view = renderHook(() => useFleetResource(load, 1000, 'sitl'));
    const options = load.mock.calls[0][0];
    expect(options.timeout).toBe(10000);
    expect(options.signal.aborted).toBe(false);
    await advance(50000);
    act(() => { window.dispatchEvent(new Event('focus')); window.dispatchEvent(new Event('focus')); });
    expect(load).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(options.signal.aborted).toBe(true);
    await act(async () => { request.resolve({ data: 'too late' }); });
    await advance(5000);
    expect(load).toHaveBeenCalledTimes(1);
  });

  test('hidden pages pause polling and visibility/focus resume without duplication', async () => {
    const next = deferred();
    const load = jest.fn().mockResolvedValueOnce({ data: 'first' }).mockReturnValue(next.promise);
    const { result } = renderHook(() => useFleetResource(load, 1000, 'sitl'));
    await flush();
    hidden.mockReturnValue(true);
    act(() => document.dispatchEvent(new Event('visibilitychange')));
    await advance(5000);
    expect(load).toHaveBeenCalledTimes(1);
    expect(result.current.response.data).toBe('first');
    hidden.mockReturnValue(false);
    act(() => { document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus')); });
    expect(load).toHaveBeenCalledTimes(2);
    await act(async () => { next.resolve({ data: 'second' }); });
    expect(result.current.response.data).toBe('second');
  });

  test('mode/session changes clear evidence and fence obsolete responses even if abort is ignored', async () => {
    const old = deferred(), fresh = deferred();
    const load = jest.fn().mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result, rerender } = renderHook(({ context }) => useFleetResource(load, 1000, context), { initialProps: { context: 'sitl:operator-a' } });
    const oldSignal = load.mock.calls[0][0].signal;
    rerender({ context: 'real:operator-b' });
    expect(oldSignal.aborted).toBe(true);
    expect(result.current.response).toBeNull();
    await act(async () => { fresh.resolve({ data: 'current-context' }); });
    await act(async () => { old.resolve({ data: 'obsolete-context' }); });
    expect(result.current.response.data).toBe('current-context');
    expect(load).toHaveBeenCalledTimes(2);
  });

  test('refresh failure preserves the previous sample and received-at clock, not refreshed freshness', async () => {
    const failure = new Error('offline');
    const load = jest.fn().mockResolvedValueOnce({ data: 'first' }).mockRejectedValue(failure);
    const { result } = renderHook(() => useFleetResource(load, 1000, 'sitl'));
    await flush();
    expect(result.current.receivedAtMs).toBe(NOW);
    await advance(1000);
    expect(result.current).toMatchObject({ response: { data: 'first' }, receivedAtMs: NOW, error: failure, loading: false });
  });
});

describe('shared fleet resources', () => {
  test('independent configuration, telemetry, boot and swarm owners do not block one another', async () => {
    getFleetConfigResponse.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useFleetResources('sitl'));
    await flush();
    expect(result.current.drones.map((item) => item.hw_id)).toEqual(['1']);
    expect(result.current.config.loading).toBe(true);
    expect(result.current.loading).toBe(false);
    await advance(1000);
    expect(getFleetTelemetryResponse).toHaveBeenCalledTimes(2);
    expect(getFleetConfigResponse).toHaveBeenCalledTimes(1);
    expect(fetchGcsResource).toHaveBeenCalledTimes(2);
    expect(new Set(fetchGcsResource.mock.calls.map(([route]) => route))).toEqual(new Set([GCS_ROUTE_KEYS.fleetNodeBootStatus, GCS_ROUTE_KEYS.swarmConfig]));
  });

  test('live evidence expires on the shared clock while the next telemetry request hangs', async () => {
    getFleetTelemetryResponse.mockResolvedValueOnce({ data: { telemetry: { 1: { hw_id: '1', update_time: NOW / 1000, telemetry_available: true, is_armed: true, landed_state: 2 } } }, headers: { 'x-mds-server-time': NOW } })
      .mockImplementation(() => new Promise(() => {}));
    const { result } = renderHook(() => useFleetResources('sitl'));
    await flush();
    expect(buildFleetViewModel(result.current.drones, { nowMs: result.current.nowMs }).summary.current).toBe(1);
    await advance(65000);
    const aircraft = buildFleetViewModel(result.current.drones, { nowMs: result.current.nowMs }).byId.get('1');
    expect(result.current.nowMs).toBe(NOW + 65000);
    expect(getFleetTelemetryResponse).toHaveBeenCalledTimes(2);
    expect(aircraft).toMatchObject({ current: false, armed: null, flightState: 'Unknown' });
    expect(aircraft.runtime.label).toBe('Offline');
  });

  test('context changes abort all owners and cannot install telemetry from the previous mode', async () => {
    const old = deferred(), fresh = deferred();
    getFleetTelemetryResponse.mockReturnValueOnce(old.promise).mockReturnValueOnce(fresh.promise);
    const { result, rerender } = renderHook(({ context }) => useFleetResources(context), { initialProps: { context: 'sitl' } });
    await flush();
    const signal = getFleetTelemetryResponse.mock.calls[0][0].signal;
    rerender({ context: 'real' });
    expect(signal.aborted).toBe(true);
    await act(async () => { fresh.resolve({ data: { telemetry: { 2: { hw_id: '2', update_time: NOW / 1000 } } }, headers: {} }); });
    await act(async () => { old.resolve({ data: { telemetry: { 99: { hw_id: '99', update_time: NOW / 1000 } } }, headers: {} }); });
    expect(result.current.drones.map((item) => item.hw_id)).toEqual(['1', '2']);
    expect(getFleetConfigResponse).toHaveBeenCalledTimes(2);
    expect(fetchGcsResource).toHaveBeenCalledTimes(4);
  });
});

describe('resource merge identity and clock', () => {
  test('merges configured, telemetry-only and boot-only IDs without losing a hidden calibrated clock', () => {
    const sample = attachDroneRuntimeClock({ hw_id: '1', update_time: NOW / 1000 }, { receivedAtMs: NOW + 40000, serverNowMs: NOW });
    const rows = mergeFleetResources([{ hw_id: '01', callsign: 'Scout' }, { hw_id: '2' }], { 1: sample, 3: { hw_id: '3' } }, { nodes: { 4: { hw_id: '4', message: 'Starting' } } });
    expect(rows.map((item) => item.hw_id)).toEqual(['1', '2', '3', '4']);
    expect(rows[0].callsign).toBe('Scout');
    expect(rows[0][DRONE_RUNTIME_CLOCK_PROP]).toBe(sample[DRONE_RUNTIME_CLOCK_PROP]);
    expect(Object.keys(rows[0])).not.toContain(DRONE_RUNTIME_CLOCK_PROP);
    expect(rows[3].node_boot_status.message).toBe('Starting');
    expect(rows[1]).not.toHaveProperty('position_lat');
    expect(buildFleetViewModel(rows, { nowMs: NOW + 40000 }).byId.get('1').current).toBe(true);
  });

  test.each([1, 3, 100])('keeps all %s configured IDs even with no telemetry', (count) => {
    const config = Array.from({ length: count }, (_, i) => ({ hw_id: String(i + 1) }));
    const rows = mergeFleetResources(config);
    expect(rows).toHaveLength(count);
    expect(new Set(rows.map((item) => item.hw_id)).size).toBe(count);
    expect(buildFleetViewModel(rows, { nowMs: NOW }).summary).toMatchObject({ current: 0, unavailable: count });
  });
});
