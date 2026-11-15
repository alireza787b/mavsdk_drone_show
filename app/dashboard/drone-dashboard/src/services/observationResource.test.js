import ObservationResource from './observationResource';

function deferred() { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; }
const flush = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
let resources;
beforeEach(() => { jest.useFakeTimers(); jest.setSystemTime(1800000000000); resources = []; jest.spyOn(document, 'hidden', 'get').mockReturnValue(false); });
afterEach(() => { resources.forEach(resource => resource.stop()); jest.restoreAllMocks(); jest.useRealTimers(); });
function resource(load, options = {}) { const value = new ObservationResource(load, options); resources.push(value); return value; }
function sockets() {
  const created = [];
  return { created, factory: jest.fn(() => {
    const socket = { close: jest.fn(), message(data) { this.onmessage?.({ data: JSON.stringify(data) }); } };
    created.push(socket); return socket;
  }) };
}
const frame = (sequence = 1, stream_id = 'epoch-a') => ({ type: 'telemetry', timestamp: Date.now(),
  protocol_version: 1, stream_id, sequence, data: { 1: { hw_id: '1', update_time: 100 } } });

test('multiple subscribers have one sequential owner, and last detach cancels and clears observations', async () => {
  const request = deferred(), load = jest.fn(() => request.promise);
  const value = resource(load);
  const first = value.subscribe(jest.fn()), second = value.subscribe(jest.fn());
  jest.advanceTimersByTime(4000);
  window.dispatchEvent(new Event('focus'));
  expect(load).toHaveBeenCalledTimes(1);
  first(); expect(load.mock.calls[0][0].signal.aborted).toBe(false);
  second(); expect(load.mock.calls[0][0].signal.aborted).toBe(true);
  request.resolve({ data: { old: true } }); await flush();
  expect(value.getSnapshot().response).toBeNull();
});

test('open socket is not live, valid stream fences late HTTP and suppresses duplicate normal polls', async () => {
  const request = deferred(), load = jest.fn(() => request.promise), ws = sockets();
  const value = resource(load, { streamUrl: () => 'ws://example', socketFactory: ws.factory });
  value.subscribe(jest.fn());
  ws.created[0].onopen(); expect(value.wsHealthy).not.toBe(true);
  ws.created[0].message(frame(2));
  request.resolve({ data: { protocol_version: 1, stream_id: 'epoch-a', sequence: 1, telemetry: {} } });
  await flush();
  expect(value.getSnapshot().response.data.sequence).toBe(2);
  expect(value.getSnapshot().transport).toBe('ws');
  jest.advanceTimersByTime(1000); await flush(); expect(load).toHaveBeenCalledTimes(1);
});

test('silent and malformed sockets expire while HTTP remains effective through reconnect probes', async () => {
  const ws = sockets(), load = jest.fn().mockResolvedValue({ data: { telemetry: {} } });
  const value = resource(load, { streamUrl: () => 'ws://example', socketFactory: ws.factory, idleMs: 2000 });
  value.subscribe(jest.fn()); await flush();
  ws.created[0].onopen();
  ws.created[0].message({ error: 'not useful' });
  jest.advanceTimersByTime(2000); await flush();
  expect(ws.created[0].close).toHaveBeenCalled();
  expect(load.mock.calls.length).toBeGreaterThan(1);
  expect(value.getSnapshot().response.data.telemetry).toEqual({});
});

test('old socket callbacks cannot overwrite a new owner and sequence regression is rejected', async () => {
  const ws = sockets(), value = resource(jest.fn().mockResolvedValue({ data: {} }), { streamUrl: () => 'ws://example', socketFactory: ws.factory });
  const detach = value.subscribe(jest.fn()); await flush();
  ws.created[0].message(frame(5));
  ws.created[0].message(frame(2)); expect(value.getSnapshot().response.data.sequence).toBe(5);
  const obsolete = ws.created[0].onmessage;
  detach(); value.subscribe(jest.fn()); await flush();
  ws.created[1].message(frame(1, 'epoch-b'));
  obsolete({ data: JSON.stringify(frame(99)) });
  expect(value.getSnapshot().response.data.stream_id).toBe('epoch-b');
});

test('HTTP errors retain the original receipt and initial resource can contain a roster array', async () => {
  const load = jest.fn().mockResolvedValueOnce({ data: [{ hw_id: '1' }] }).mockRejectedValue(new Error('offline'));
  const value = resource(load); value.subscribe(jest.fn()); await flush();
  const receipt = value.getSnapshot().receivedAtMs;
  jest.advanceTimersByTime(1000); await flush();
  expect(value.getSnapshot()).toMatchObject({ response: { data: [{ hw_id: '1' }] }, receivedAtMs: receipt, consecutiveFailures: 1 });
});

test('duplicate generations do not renew useful-data liveness', async () => {
  const ws = sockets(), value = resource(jest.fn().mockResolvedValue({ data: {} }), {
    streamUrl: () => 'ws://example', socketFactory: ws.factory, idleMs: 2000,
  });
  value.subscribe(jest.fn()); await flush();
  ws.created[0].message(frame(1));
  jest.advanceTimersByTime(1500);
  ws.created[0].message(frame(1));
  jest.advanceTimersByTime(501); await flush();
  expect(ws.created[0].close).toHaveBeenCalled();
});

test('an HTTP response predating stream takeover cannot install after socket failure', async () => {
  const old = deferred(), ws = sockets();
  const value = resource(jest.fn(() => old.promise), { streamUrl: () => 'ws://example', socketFactory: ws.factory });
  value.subscribe(jest.fn());
  ws.created[0].message(frame(1, 'new-epoch'));
  ws.created[0].onclose({ code: 1006 });
  old.resolve({ data: { protocol_version: 1, stream_id: 'old-epoch', sequence: 100 } });
  await flush();
  expect(value.getSnapshot().response.data.stream_id).toBe('new-epoch');
});

test('visibility closes the stream, keeps bounded background monitoring and resumes one socket', async () => {
  const ws = sockets(), value = resource(jest.fn().mockResolvedValue({ data: {} }), { streamUrl: () => 'ws://example', socketFactory: ws.factory });
  value.subscribe(jest.fn()); await flush();
  jest.spyOn(document, 'hidden', 'get').mockReturnValue(true);
  document.dispatchEvent(new Event('visibilitychange'));
  expect(ws.created[0].close).toHaveBeenCalled();
  jest.spyOn(document, 'hidden', 'get').mockReturnValue(false);
  document.dispatchEvent(new Event('visibilitychange')); window.dispatchEvent(new Event('focus'));
  expect(ws.factory).toHaveBeenCalledTimes(2);
});

test('policy denial is not treated as a reconnecting radio and auth expiry is signalled', async () => {
  const ws = sockets(), expired = jest.fn();
  window.addEventListener('mds:auth-required', expired);
  const value = resource(jest.fn().mockResolvedValue({ data: {} }), { streamUrl: () => 'ws://example', socketFactory: ws.factory });
  value.subscribe(jest.fn()); await flush();
  ws.created[0].onclose({ code: 1008, reason: 'authentication_required' });
  expect(value.getSnapshot().transport).toBe('auth-required');
  expect(expired).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(20000); await flush();
  window.dispatchEvent(new Event('focus'));
  expect(ws.factory).toHaveBeenCalledTimes(1);
  window.removeEventListener('mds:auth-required', expired);
});
