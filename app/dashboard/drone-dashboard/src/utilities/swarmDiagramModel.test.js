import { swarmNodeStatus } from './swarmDiagramModel';
import { memberFlightState } from './swarmOperationModel';

test.each([
  { armed: true, landed_state: 2 },
  { armed: false, landed_state: 1 },
  { armed: undefined, landed_state: undefined },
])('missing telemetry does not claim offline or a current flight state: %j', (lastState) => {
  const member = { hw_id: '2', follow: '1', ...lastState, available: false };
  const status = swarmNodeStatus(member, { phase: 'active', received_at_ms: 1000 }, {
    hasSession: true, now: 1001,
  });
  expect(status).toEqual({ label: 'Telemetry delayed', tone: 'warning', symbol: '?' });
  expect(memberFlightState(member)).toBe('Unknown');
});

test('fresh aircraft telemetry cannot turn an old runtime report into current following', () => {
  const member = { hw_id: '2', follow: '1', available: true };
  expect(swarmNodeStatus(member, { phase: 'active', received_at_ms: 1000 }, {
    hasSession: true, now: 17000,
  }).label).toBe('Unconfirmed');
  expect(swarmNodeStatus(member, { phase: 'active', received_at_ms: 1000 }, {
    hasSession: true, stale: true, now: 1001,
  }).label).toBe('Unconfirmed');
});

test('fresh runtime still shows real controller failure and normal following distinctly', () => {
  const member = { hw_id: '2', follow: '1', available: true };
  const options = { hasSession: true, now: 1001 };
  expect(swarmNodeStatus(member, { phase: 'failed', received_at_ms: 1000 }, options)).toEqual({
    label: 'Failed', tone: 'danger', symbol: '!',
  });
  expect(swarmNodeStatus(member, { phase: 'active', received_at_ms: 1000 }, options).label).toBe('Following');
});

test('an old operation cannot keep a freshly disarmed aircraft permanently unconfirmed',()=>{
  const member={hw_id:'2',follow:'1',available:true,armed:false};
  expect(swarmNodeStatus(member,null,{hasSession:true,stale:true}).label).toBe('Not following');
  expect(swarmNodeStatus({...member,available:false},null,{hasSession:true,stale:true}).label).toBe('Telemetry delayed');
  expect(swarmNodeStatus({...member,armed:undefined},null,{hasSession:true,stale:true}).label).toBe('Unconfirmed');
  expect(swarmNodeStatus(member,{phase:'failed',received_at_ms:1000},{hasSession:true,now:1001}).label).toBe('Failed');
});
