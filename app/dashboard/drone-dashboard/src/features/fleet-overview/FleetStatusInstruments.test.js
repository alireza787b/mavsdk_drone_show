import React from 'react';
import { render } from '@testing-library/react';
import { BatteryGauge, WifiStrength } from './FleetStatusInstruments';

test.each([[0,0],[1,1],[33,1],[34,2],[67,3],[100,3],[null,'unknown'],[-1,'unknown']])('Wi-Fi%s is level%s without fabricating signal', (percent, level)=>{
  const {container}=render(<WifiStrength percent={percent}/>);
  expect(container.querySelector('svg')).toHaveAttribute('data-level',String(level));
  expect(container.querySelectorAll('[data-active=true]')).toHaveLength(level==='unknown'?0:level);
});
test.each([0,100,null])('battery%s uses reported percentage only', remaining=>{
  const {container}=render(<BatteryGauge battery={{remaining,voltage:24,current:true}}/>);
  expect(container.querySelector('svg')).toHaveAttribute('data-charge',remaining===null?'unknown':String(remaining));
  expect(container.querySelector('svg')).toHaveAttribute('viewBox','0 0 46 22');
  expect(container.querySelector('text')).toHaveTextContent(remaining===null?'—':`${remaining}%`);
  expect(container.querySelectorAll('.fleet-battery-gauge__fill')).toHaveLength(remaining===null?0:1);
});
test.each([[true,0,true],[false,0,false],[true,2,false]])('charging requires current fault-free state', (current,faultBitmask,show)=>{
  const {container}=render(<BatteryGauge battery={{remaining:80,chargeState:7,current,faultBitmask}}/>);
  expect(Boolean(container.querySelector('.fleet-battery-instrument__charging'))).toBe(show);
});
