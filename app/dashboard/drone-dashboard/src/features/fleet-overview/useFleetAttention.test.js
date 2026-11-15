import { act, renderHook } from '@testing-library/react';
import useFleetAttention, { fleetAttentionSnapshot } from './useFleetAttention';

const NOW = 1780000000000;
const link = { key: 'telemetry', tone: 'warning', label: 'Telemetry unavailable' };
const critical = { key: 'battery', tone: 'danger', label: 'Battery: Critical' };
const model = (issues = [], current = !issues.includes(link)) => ({ aircraft: [{ id:'1', current, issues, attention:!!issues.length }], summary:{ current:current?1:0 }, byId:new Map() });
const resources = (nowMs=NOW,error=null) => ({ nowMs, telemetry:{response:{},error},config:{response:{},error:null} });
const step = (previous, issues, elapsed=0, error=null) => fleetAttentionSnapshot(previous?.state,model(issues),resources(NOW+elapsed,error));

test('one missed poll has no warning episode, but never changes raw state or age',()=>{
  const initial=step(null,[]);
  const missed=step(initial,[link],1000);
  expect(missed.model.aircraft[0]).toMatchObject({ current:false,linkAttention:'pending',issues:[],rawIssues:[link] });
  expect(step(missed,[],2000).model.aircraft[0]).toMatchObject({ current:true,linkAttention:'clear',issues:[] });
});

test('normal heartbeat-boundary jitter gets a neutral cue, not a new warning or a false Fresh label',()=>{
  const input=model();input.aircraft[0].availability={stale:true,label:'Stale'};
  const first=fleetAttentionSnapshot(null,input,resources());
  expect(first.model.aircraft[0]).toMatchObject({current:true,availability:{label:'Stale'},linkAttention:'pending',issues:[]});
  input.aircraft[0].availability={stale:false,label:'Fresh'};
  expect(fleetAttentionSnapshot(first.state,input,resources(NOW+1000)).model.aircraft[0])
    .toMatchObject({linkAttention:'clear',issues:[]});
});
test('sustained loss promotes at3s; recovery requires2s and a flap retains the same episode',()=>{
  const first=step(null,[link]);
  expect(step(first,[link],2999).model.aircraft[0].attention).toBe(false);
  const active=step(first,[link],3000);
  expect(active.model.aircraft[0].issues).toEqual([link]);
  const recovering=step(active,[],4000);
  expect(recovering.model.aircraft[0]).toMatchObject({ current:true,linkAttention:'recovering',issues:[{key:'telemetry',label:'Link recovering'}] });
  expect(step(recovering,[link],5000).model.aircraft[0].linkAttention).toBe('active');
  expect(step(recovering,[],6000).model.aircraft[0].attention).toBe(false);
});
test('urgent battery/PX4 and already-offline evidence are never delayed',()=>{
  expect(step(null,[link,critical]).model.aircraft[0].issues).toEqual([critical]);
  expect(step(null,[{...link,tone:'danger',label:'Offline'}]).model.aircraft[0].attention).toBe(true);
});
test('GCS source is quiet for short failures, unavailable initial load is immediate; config error is separate',()=>{
  const first=step(null,[],0,new Error('network'));
  expect(first.telemetry.active).toBe(false);
  const active=step(first,[],3000,new Error('network'));
  expect(active.telemetry.active).toBe(true);
  expect(step(active,[],4000).telemetry.phase).toBe('recovering');
  const input=resources();input.telemetry={response:null,error:new Error('initial load')};
  expect(fleetAttentionSnapshot(null,model(),input).telemetry.active).toBe(true);
  const config=resources();config.config.error=new Error('config');
  expect(fleetAttentionSnapshot(null,model(),config).telemetry.active).toBe(false);
});
test('history is bounded by current identities, raw objects are immutable, and clock rollback resets pending state',()=>{
  const input=model([link]);const first=fleetAttentionSnapshot(null,input,resources());
  expect(input.aircraft[0].issues).toEqual([link]);expect(input.aircraft[0]).not.toHaveProperty('rawIssues');
  expect(fleetAttentionSnapshot(first.state,{...model(),aircraft:[]},resources(NOW+1000)).state.links.size).toBe(0);
  expect(step(first,[link],-1000).model.aircraft[0].linkAttention).toBe('pending');
});

test('a lone failed low-rate configuration refresh does not become a lasting outage',()=>{
  const input=resources();input.config={response:{},error:new Error('config'),consecutiveFailures:1};
  const first=fleetAttentionSnapshot(null,model(),input);
  const later=fleetAttentionSnapshot(first.state,model(),{...input,nowMs:NOW+20000});
  expect(later.config.active).toBe(false);
  input.config.consecutiveFailures=2;
  expect(fleetAttentionSnapshot(later.state,model(),{...input,nowMs:NOW+30000}).config.active).toBe(true);
});
test('provider rerenders with equivalent resource wrappers cannot restart the presentation clock or loop',()=>{
  const input=model([link]);
  const view=renderHook(({now})=>useFleetAttention(input,resources(now)),{initialProps:{now:NOW}});
  const original=view.result.current;
  act(()=>view.rerender({now:NOW}));
  // Response identity may vary, but no state update is scheduled by the hook.
  expect(view.result.current.state.links.get('1').since).toBe(original.state.links.get('1').since);
  act(()=>view.rerender({now:NOW+3000}));expect(view.result.current.model.aircraft[0].attention).toBe(true);
});
