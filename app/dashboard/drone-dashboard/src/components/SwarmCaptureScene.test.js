import React from 'react';
import { fireEvent,render,screen } from '@testing-library/react';
import SwarmCaptureScene from './SwarmCaptureScene';
const entries=[{hw_id:'1',follow:'0',offset_x:0,offset_y:0,offset_z:0,frame:'ned'},
  {hw_id:'2',follow:'1',offset_x:6,offset_y:2,offset_z:1,frame:'ned'}];
test('3D is default, view/camera interactions never edit input; all axes and aircraft inspection are accessible',()=>{
  const onSelect=jest.fn(), before=JSON.stringify(entries);
  render(<SwarmCaptureScene entries={entries} headings={{}} overlays={[]} labels={{1:'Leader',2:'Wing'}} selectedId="1" onSelect={onSelect} frame="ned" heading={0} captureId="snapshot"/>);
  expect(screen.getByRole('button',{name:'3D',exact:true})).toHaveAttribute('aria-pressed','true');
  expect(screen.getByRole('group',{name:'Capture 3D view'})).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole('group',{name:'Capture 3D view'}),{key:'ArrowRight'});
  for(const view of ['Top','Front','Side','3D']) fireEvent.click(screen.getByRole('button',{name:view,exact:true}));
  fireEvent.click(screen.getByRole('button',{name:'Zoom in'}));
  fireEvent.click(screen.getByRole('button',{name:'Fit formation'}));
  fireEvent.click(screen.getByRole('button',{name:'Wing, follower'}));
  expect(onSelect).toHaveBeenCalledWith('2');
  expect(JSON.stringify(entries)).toBe(before);
});

test('large formations limit labels, preserve selectable aircraft and never masquerade ghost samples as targets',()=>{
  const many=[entries[0],...Array.from({length:49},(_,i)=>({...entries[1],hw_id:String(i+2),offset_x:i+1,offset_y:i%7}))];
  const {container}=render(<SwarmCaptureScene entries={many} headings={{}} overlays={[{id:'2',north:1,east:2,up:0,stale:true}]}
    labels={{}} selectedId="2" onSelect={()=>{}} frame="ned" heading={0} captureId="many"/>);
  expect(container.querySelectorAll('.capture-scene__aircraft')).toHaveLength(50);
  expect(container.querySelectorAll('.capture-scene__aircraft text')).toHaveLength(2);
  expect(screen.getByRole('img',{name:'H2, delayed estimated position'})).toHaveClass('is-stale');
  fireEvent.click(screen.getByRole('button',{name:'Front',exact:true}));
  expect(container.querySelectorAll('.capture-scene__aircraft text')).toHaveLength(1);
});

test('dragging from an aircraft or background always orbits the read-only camera, never selects after a drag',()=>{
  const previous=window.PointerEvent; window.PointerEvent=MouseEvent;
  try{
    const onSelect=jest.fn();
    render(<SwarmCaptureScene entries={entries} headings={{}} overlays={[]} labels={{1:'Leader',2:'Wing'}} selectedId="1" onSelect={onSelect} frame="ned" heading={0} captureId="drag"/>);
    const node=screen.getByRole('button',{name:'Wing, follower'}),scene=screen.getByRole('group',{name:'Capture 3D view'});
    const before=node.getAttribute('transform');
    fireEvent.pointerDown(node,{button:0,clientX:100,clientY:100});
    fireEvent.pointerMove(scene,{clientX:140,clientY:130});
    fireEvent.pointerUp(scene,{clientX:140,clientY:130});
    fireEvent.click(node);
    expect(node.getAttribute('transform')).not.toBe(before);
    expect(onSelect).not.toHaveBeenCalled();
  }finally{window.PointerEvent=previous;}
});
