import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import CommandAircraftPicker from './CommandAircraftPicker';

const aircraft = (id, available=true) => ({id,label:`ALPHA-${id}`,raw:{hw_id:id,callsign:`ALPHA-${id}`},
  identity:{posId:id},availability:{available,label:available?'Fresh':'Offline',stale:false}});
const setup = (extra={}) => {
  const props={selectedIds:['1','3'],configuredIds:['1','2','3'],aircraft:[aircraft('1'),aircraft('2'),aircraft('3',false)],onApply:jest.fn(),onClose:jest.fn(),...extra};
  return {...render(<CommandAircraftPicker {...props} />),props};
};
const checkbox=id=>screen.getByRole('checkbox',{name:`Include ALPHA-${id} (H${id})`});
const apply=count=>fireEvent.click(screen.getByRole('button',{name:`Use ${count} aircraft`,exact:true}));

test('editing/search are local, Cancel does not publish a draft',()=>{
  const {props}=setup();
  expect(screen.getByRole('searchbox',{name:'Find command aircraft'})).toHaveFocus();
  fireEvent.click(checkbox('2'));
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:'ALPHA-1'}});
  expect(screen.getAllByRole('checkbox')).toHaveLength(1);
  expect(screen.getByRole('button',{name:'Use 3 aircraft'})).toBeEnabled();
  fireEvent.click(screen.getByRole('button',{name:'Cancel',exact:true}));
  expect(props.onClose).toHaveBeenCalledTimes(1);
  expect(props.onApply).not.toHaveBeenCalled();
  expect(props.selectedIds).toEqual(['1','3']);
});

test('Apply publishes the exact draft, including hidden/unavailable choices',()=>{
  const {props}=setup();
  fireEvent.click(checkbox('2'));
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:'ALPHA-1'}});
  apply(3);
  expect(props.onApply).toHaveBeenCalledWith(['1','3','2']);
});

test('available and all-configured presets are explicit unfiltered snapshots',()=>{
  const {props,rerender}=setup();
  fireEvent.change(screen.getByRole('searchbox'),{target:{value:'ALPHA-1'}});
  fireEvent.click(screen.getByRole('button',{name:'Use available now'}));
  rerender(<CommandAircraftPicker {...props} aircraft={[aircraft('1'),aircraft('2',false),aircraft('3')]} />);
  apply(2);
  expect(props.onApply).toHaveBeenLastCalledWith(['1','2']);
  fireEvent.click(screen.getByLabelText('More command aircraft options'));
  fireEvent.click(screen.getByRole('button',{name:'All configured',exact:true}));
  apply(3);
  expect(props.onApply).toHaveBeenLastCalledWith(['1','2','3']);
});

test('clear and an initially empty roster remain legitimate empty selections',()=>{
  const {props}=setup();
  fireEvent.click(screen.getByRole('button',{name:'Clear command aircraft'}));
  apply(0);
  expect(props.onApply).toHaveBeenCalledWith([]);
});

test('removed identities remain included and removable until explicit Apply',()=>{
  const {props}=setup({selectedIds:['1','gone']});
  const missing=screen.getByRole('checkbox',{name:'Include Aircraft gone (Hgone)'});
  expect(missing).toBeChecked();
  expect(screen.getByText('Missing')).toBeInTheDocument();
  fireEvent.click(missing);
  expect(missing).not.toBeChecked();
  apply(1);
  expect(props.onApply).toHaveBeenCalledWith(['1']);
});

test('a new configured aircraft or changed cluster cannot expand the staged set',()=>{
  const groups=[{id:'a',drones:[{hw_id:'1'}]},{id:'b',drones:[{hw_id:'2'},{hw_id:'3'}]}];
  const {props,rerender}=setup({groups});
  fireEvent.change(screen.getByRole('combobox',{name:'Choose command cluster'}),{target:{value:'b'}});
  rerender(<CommandAircraftPicker {...props} configuredIds={['1','2','3','4']} aircraft={[...props.aircraft,aircraft('4')]}
    groups={[groups[0],{id:'b',drones:[{hw_id:'2'},{hw_id:'4'}]}]} />);
  expect(checkbox('4')).not.toBeChecked();
  apply(2);
  expect(props.onApply).toHaveBeenCalledWith(['2','3']);
});

test('Escape cancels without applying; one cluster does not add a cluster selector',()=>{
  const {props}=setup({groups:[{id:'a',drones:[{hw_id:'1'},{hw_id:'2'}]}]});
  expect(screen.queryByRole('combobox',{name:'Choose command cluster'})).not.toBeInTheDocument();
  fireEvent.keyDown(document,{key:'Escape'});
  expect(props.onClose).toHaveBeenCalledTimes(1);
  expect(props.onApply).not.toHaveBeenCalled();
});

test.each([0,1,3,100])('identity list remains complete for %i configured aircraft',count=>{
  const rows=Array.from({length:count},(_,index)=>aircraft(String(index+1)));
  setup({configuredIds:rows.map(row=>row.id),selectedIds:rows.map(row=>row.id),aircraft:rows});
  const roster=screen.getByRole('group',{name:'Aircraft for commands'});
  expect(within(roster).queryAllByRole('checkbox')).toHaveLength(count);
  expect(screen.getByRole('button',{name:`Use ${count} aircraft`})).toBeEnabled();
});
