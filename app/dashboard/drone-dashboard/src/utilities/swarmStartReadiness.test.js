import { swarmStartReadiness } from './swarmStartReadiness';
test('only fresh identity-matching node decisions enable the selected roles', () => {
  const d = { '1': { hw_id:'1',status:'ready',valid_for_ms:1000 } };
  expect(swarmStartReadiness(['1'], d, 1000, 1).ready).toBe(true);
  expect(swarmStartReadiness(['1'], d, 1000, 1000).ready).toBe(false);
  expect(swarmStartReadiness(['1','2'], d, 1000, 1).ready).toBe(false);
  expect(swarmStartReadiness(['2'], { '2': d['1'] }, 1000, 1).ready).toBe(false);
});
test('a named unavailable aircraft is not hidden by an expired ready member',()=>{
  const decisions={'1':{hw_id:'1',status:'ready',valid_for_ms:0},
    '3':{hw_id:'3',status:'unavailable',message:'Aircraft offline',valid_for_ms:0}};
  expect(swarmStartReadiness(['1','3'],decisions,1000,2000)).toEqual({ready:false,label:'Aircraft offline · Drone 3'});
});
test('expired all-ready evidence stays disabled and explicitly refreshes',()=>{
  expect(swarmStartReadiness(['1'],{'1':{hw_id:'1',status:'ready',valid_for_ms:1000}},1000,2000))
    .toEqual({ready:false,label:'Refreshing readiness'});
});
