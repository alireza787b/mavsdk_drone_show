import { swarmReferenceIds, swarmStartQuery, swarmReviewEvidence, swarmNamesSummary } from './swarmCommandScope';

test('large rosters keep the visible summary compact without losing the count',()=>{
  expect(swarmNamesSummary(['One'])).toBe('One');
  expect(swarmNamesSummary(Array.from({length:100},(_,i)=>`H${i+1}`))).toBe('H1 · H2 +98');
});
import { swarmStartValidUntil } from './swarmStartReadiness';
const members=[{hw_id:'1',follow:'0'},{hw_id:'2',follow:'1'},{hw_id:'3',follow:'2'},{hw_id:'4',follow:'0'}];
test('upstream sources are explicit, do not widen recipients, and preserve relay roles',()=>{
  const ids=['3'];
  expect(swarmReferenceIds(members,ids)).toEqual(['1','2']);
  expect(ids).toEqual(['3']);
  expect(swarmReferenceIds(members,['1','2','3'])).toEqual([]);
  expect(swarmReferenceIds(members,['2','3'])).toEqual(['1']);
});
test('native preview query preserves repeated target parameters',()=>{
  expect(swarmStartQuery('1',['2','3']).getAll('target_hw_ids')).toEqual(['2','3']);
});
test('reference proof must match the exact reviewed topology sources',()=>{
  const reviewed={targets:['3'],references:['1','2']};
  expect(swarmReviewEvidence(reviewed,{reference_hw_ids:['1']},1000,swarmStartValidUntil)).toBeNull();
  const row=id=>({hw_id:id,status:'ready',valid_for_ms:5000});
  const result=swarmReviewEvidence(reviewed,{reference_hw_ids:['1','2'],start_admissions:{'3':row('3')},
    reference_admissions:{'1':row('1'),'2':row('2')}},1000,swarmStartValidUntil);
  expect(result.until).toBe(6000);
  expect(Object.keys(result.decisions)).toEqual(['1','2','3']);
});
