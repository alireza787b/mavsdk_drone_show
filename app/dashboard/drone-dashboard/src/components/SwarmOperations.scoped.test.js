import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import SwarmOperations from './SwarmOperations';
import { fetchGcsResource } from '../services/gcsApiService';
import { submitCommandWithLifecycleFeedback } from '../utilities/commandLifecycleFeedback';
jest.mock('../services/gcsApiService',()=>({fetchGcsResource:jest.fn()}));
jest.mock('../utilities/commandLifecycleFeedback',()=>({submitCommandWithLifecycleFeedback:jest.fn(),trackCommandReceipt:jest.fn()}));
const mockMonitors=[];
jest.mock('../contexts/CommandActivityContext',()=>({useCommandActivity:()=>({commandMonitors:mockMonitors,commandLifecycleCallbacks:{}})}));
jest.mock('./SequentialReturnControl',()=>({targetIds,buttonLabel})=><button data-targets={targetIds.join(',')}>{buttonLabel}</button>);
const members=['1','2','3'].map(hw_id=>({hw_id,follow:hw_id==='1'?'0':'1',available:true,armed:true,landed_state:2,frame:'body'}));
const ready=id=>({hw_id:id,status:'ready',valid_for_ms:10000,scoped_start_supported:true});
let referenceBlocked;
beforeEach(()=>{
  jest.clearAllMocks();sessionStorage.clear();mockMonitors.length=0;referenceBlocked=false;
  submitCommandWithLifecycleFeedback.mockResolvedValue({command_id:'retry'});
  fetchGcsResource.mockImplementation((_path,options)=>{
    const targets=options?.params?.getAll?.('target_hw_ids') || ['1','2','3'];
    const references=targets.includes('1')?[]:['1'];
    return Promise.resolve({data:{runtime_mode:'SITL',revision:'same',clusters:[{cluster_id:'1',members}],
      start_admissions:Object.fromEntries(targets.map(id=>[id, id==='1' && mockMonitors.length
        ? {...ready(id),status:'blocked',message:'Another action is active'}:ready(id)])),
      reference_hw_ids:references,reference_admissions:{'1':referenceBlocked
        ? {...ready('1'),status:'blocked',message:'PX4 RTL active'}:ready('1')}}});
  });
});
async function mount(){render(<SwarmOperations/>);await waitFor(()=>expect(screen.getByRole('button',{name:'Choose command aircraft'})).toHaveAttribute('data-recipient-count','3'));}
function choose(ids){
  fireEvent.click(screen.getByRole('button',{name:'Choose command aircraft'}));
  const picker=within(screen.getByRole('dialog',{name:'Command aircraft'}));
  fireEvent.click(picker.getByRole('button',{name:'Clear command aircraft'}));
  ids.forEach(id=>fireEvent.click(picker.getByRole('checkbox',{name:`Include Drone ${id} (H${id})`})));
  fireEvent.click(picker.getByRole('button',{name:`Use ${ids.length} aircraft`}));
}
test('one follower can be retried while its existing leader remains untouched',async()=>{
  mockMonitors.push({commandId:'original-leader',missionType:2,targetDrones:['1'],updatedAtMs:Date.now(),
    swarmRuntime:{state:'active',active_hw_ids:['1']}});
  await mount();choose(['2']);
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Start Swarm'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Confirm Start Swarm'})).toBeEnabled());
  expect(screen.getByText('Leader reference: H1')).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'Choose command aircraft'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Confirm Start Swarm'}));
  await waitFor(()=>expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0]).toMatchObject({target_drone_ids:['2'],smart_swarm_start:{target_hw_ids:['2']}});
  expect(mockMonitors[0].commandId).toBe('original-leader');
  expect(members.map(m=>m.follow)).toEqual(['0','1','1']);
});
test('an intentional healthy subset is not restricted to the availability preset',async()=>{
  await mount();choose(['1','2']);
  fireEvent.click(screen.getByRole('button',{name:'Start Swarm'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Confirm Start Swarm'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'Confirm Start Swarm'}));
  await waitFor(()=>expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].target_drone_ids).toEqual(['1','2']);
});
test('a recovering reference blocks the selected Start without commanding it',async()=>{
  referenceBlocked=true;await mount();choose(['2']);
  fireEvent.click(screen.getByRole('button',{name:'Start Swarm'}));
  await screen.findByText(/Leader reference: PX4 RTL active/);
  expect(screen.getByRole('button',{name:'Confirm Start Swarm'})).toBeDisabled();
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});
test('empty To stays explicit; Hold all and Return all keep their named full-cluster scope',async()=>{
  await mount();choose([]);
  expect(screen.getByRole('button',{name:'Start Swarm'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Takeoff'})).toBeDisabled();
  expect(screen.getByRole('button',{name:'Return all'})).toHaveAttribute('data-targets','1,2,3');
  fireEvent.click(screen.getByRole('button',{name:'Hold all'}));
  await waitFor(()=>expect(submitCommandWithLifecycleFeedback).toHaveBeenCalledTimes(1));
  expect(submitCommandWithLifecycleFeedback.mock.calls[0][0].target_drone_ids).toEqual(['1','2','3']);
});

test.each([1,100])('%i aircraft default to the whole formation with controls before the roster',async count=>{
  const roster=Array.from({length:count},(_,i)=>({...members[0],hw_id:String(i+1),follow:i?'1':'0'}));
  fetchGcsResource.mockResolvedValue({data:{runtime_mode:'SITL',revision:'same',clusters:[{cluster_id:'1',members:roster}]}});
  render(<SwarmOperations/>);
  await waitFor(()=>expect(screen.getByRole('button',{name:'Choose command aircraft'})).toHaveAttribute('data-recipient-count',String(count)));
  expect(screen.queryByRole('combobox',{name:'Swarm formation'})).not.toBeInTheDocument();
  const diagram=screen.getByRole('list',{name:'Cluster aircraft'});
  expect(within(diagram).getAllByRole('button')).toHaveLength(count);
  expect(screen.getByRole('button',{name:'Hold all'}).compareDocumentPosition(diagram)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

test('a deliberate cluster change selects only that cluster, not the entire fleet',async()=>{
  fetchGcsResource.mockResolvedValue({data:{runtime_mode:'SITL',revision:'same',clusters:[
    {cluster_id:'1',members}, {cluster_id:'4',members:[{...members[0],hw_id:'4'}]},
  ]}});
  await mount();choose(['2']);
  fireEvent.change(screen.getByRole('combobox',{name:'Swarm formation'}),{target:{value:'4'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'Choose command aircraft'})).toHaveAttribute('data-recipient-count','1'));
  expect(screen.getByRole('button',{name:'Choose command aircraft'})).toHaveAttribute('title','Command recipients: Drone 4');
  expect(submitCommandWithLifecycleFeedback).not.toHaveBeenCalled();
});
