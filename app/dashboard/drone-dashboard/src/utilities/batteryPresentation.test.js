import { getBatteryPresentation } from './batteryPresentation';

describe('getBatteryPresentation', () => {
  it('uses state of charge and MAVLink charge state without voltage thresholds', () => {
    expect(getBatteryPresentation({
      battery_voltage: 15.3,
      battery_remaining_percent: 42,
      battery_charge_state: 2,
      battery_fault_bitmask: 0,
      battery_age_ms: 250,
    })).toEqual(expect.objectContaining({
      text: '42% · 15.3V',
      class: 'warning',
      tone: 'warning',
      label: 'Low',
    }));
  });

  it('treats fault metadata as critical regardless of voltage', () => {
    const result = getBatteryPresentation({
      battery_voltage: 16.8,
      battery_remaining_percent: 95,
      battery_charge_state: 1,
      battery_fault_bitmask: 4,
    });

    expect(result.class).toBe('critical');
    expect(result.label).toBe('Fault 0x4');
  });

  it('keeps voltage informational when state of charge is unavailable', () => {
    const result = getBatteryPresentation({ battery_voltage: 13.2 });

    expect(result.text).toBe('13.2V');
    expect(result.class).toBe('');
    expect(result.label).toBe('State unavailable');
    expect(result.help).toMatch(/Voltage alone is not used/i);
  });
});
