import { act, renderHook } from '@testing-library/react';
import useSwarmCommandScope from './useSwarmCommandScope';
beforeEach(()=>sessionStorage.clear());

test('common first cluster is a full snapshot; polls, roles and new members cannot retarget it',()=>{
  const {result,rerender}=renderHook(({context,ids})=>useSwarmCommandScope(context,ids),{initialProps:{context:'real:1',ids:['1','2']}});
  expect(result.current.ids).toEqual(['1','2']);
  act(()=>result.current.choose(['2']));
  rerender({context:'real:1',ids:['1','2','3']});
  expect(result.current.ids).toEqual(['2']);
  rerender({context:'real:1',ids:['1']});
  expect(result.current.ids).toEqual(['2']);
  expect(result.current.missing).toEqual(['2']);
});

test.each([[['2']],[[]]])('remount preserves an explicit subset or None: %j',ids=>{
  const first=renderHook(()=>useSwarmCommandScope('real:operator-a:1',['1','2']));
  act(()=>first.result.current.choose(ids));first.unmount();
  const second=renderHook(()=>useSwarmCommandScope('real:operator-a:1',['1','2','3']));
  expect(second.result.current.ids).toEqual(ids);
});
test('a corrupt saved scope stays empty rather than commanding the full formation',()=>{
  sessionStorage.setItem('mds:swarm-targets:v1:real:operator-a:1','not json');
  const {result}=renderHook(()=>useSwarmCommandScope('real:operator-a:1',['1','2']));
  expect(result.current.initialized).toBe(true);expect(result.current.ids).toEqual([]);
});
test('another operator has an independent initial scope; late callbacks cannot retarget it',()=>{
  const {result,rerender}=renderHook(({context})=>useSwarmCommandScope(context,['1','2']),{initialProps:{context:'real:operator-a:1'}});
  const oldChoose=result.current.choose;
  rerender({context:'real:operator-b:1'});act(()=>oldChoose(['2']));
  expect(result.current.ids).toEqual(['1','2']);
});

test('empty choices remain empty; explicit cluster/runtime changes initialize a new full scope',()=>{
  const {result,rerender}=renderHook(({context,ids})=>useSwarmCommandScope(context,ids),{initialProps:{context:'real:1',ids:['1','2']}});
  act(()=>result.current.choose([]));
  rerender({context:'real:1',ids:['1','2']});
  expect(result.current.ids).toEqual([]);
  rerender({context:'real:4',ids:['4','5']});
  expect(result.current.ids).toEqual(['4','5']);
  rerender({context:'sitl:1',ids:['1','2']});
  expect(result.current.ids).toEqual(['1','2']);
});
