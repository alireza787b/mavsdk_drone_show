import { act, renderHook } from '@testing-library/react';
import useSwarmCommandScope from './useSwarmCommandScope';

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
