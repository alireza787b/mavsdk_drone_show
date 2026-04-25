import {
  buildGlobeDroneViewModels,
  calculateGlobeTelemetryIntervalMs,
} from './globeTelemetryViewModel';

describe('globeTelemetryViewModel', () => {
  it('merges live telemetry with fleet config marker color and slot identity', () => {
    const result = buildGlobeDroneViewModels(
      {
        2: {
          hw_id: 2,
          position_lat: 35.1,
          position_long: 51.2,
          position_alt: 103.5,
          state: 2,
          battery_voltage: 16.44,
          velocity_north: 1,
          velocity_east: 2,
          velocity_down: 2,
          distance_to_home_m: 12.5,
        },
      },
      [{ hw_id: '2', pos_id: '7', marker_color: '#ffaa00' }]
    );

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      hw_id: '2',
      pos_id: '7',
      position: [35.1, 51.2, 103.5],
      marker_color: '#ffaa00',
      battery_voltage: 16.44,
      distance_to_home_m: 12.5,
    });
    expect(result[0].speed_mps).toBe(3);
  });

  it('backs off the tactical telemetry interval for hidden tabs, constrained links, and large fleets', () => {
    expect(calculateGlobeTelemetryIntervalMs(4, { hidden: false, connection: {} })).toBe(1000);
    expect(calculateGlobeTelemetryIntervalMs(40, { hidden: false, connection: {} })).toBe(1500);
    expect(calculateGlobeTelemetryIntervalMs(100, { hidden: false, connection: {} })).toBe(2500);
    expect(calculateGlobeTelemetryIntervalMs(4, { hidden: true, connection: {} })).toBe(6000);
    expect(calculateGlobeTelemetryIntervalMs(4, { hidden: false, connection: { saveData: true } })).toBe(3000);
  });
});
