import {
  buildGlobeDroneViewModels,
} from './globeTelemetryViewModel';
import { attachDroneRuntimeClock } from '../constants/fieldMappings';

describe('globeTelemetryViewModel', () => {
  it('keeps configured address without filling missing velocity or follow role with zero', () => {
    const [row] = buildGlobeDroneViewModels({ 2: { hw_id: '2', velocity_north: null, velocity_east: null, velocity_down: null } },
      [{ hw_id: '2', pos_id: '7', ip: '192.0.2.2' }]);
    expect(row.ip).toBe('192.0.2.2');
    expect(row.speed_mps).toBeNull();
    expect(row.follow_mode).toBeNull();
  });
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
      [{ hw_id: '2', pos_id: '7', marker_color: '#ffaa00', callsign: 'SCOUT-2' }]
    );

    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({
      hw_id: '2',
      pos_id: '7',
      position: [35.1, 51.2, 103.5],
      marker_color: '#ffaa00',
      operator_alias: 'SCOUT-2',
      battery_voltage: 16.44,
      distance_to_home_m: 12.5,
    });
    expect(result[0].speed_mps).toBe(3);
  });

  it('marks GPS-only telemetry without valid global position as no-map-fix', () => {
    const result = buildGlobeDroneViewModels({
      1: {
        hw_id: 1,
        position_lat: 0,
        position_long: 0,
        position_alt: 0,
        global_position_valid: false,
        position_unavailable_reason: 'GPS fix present, waiting for valid PX4 global position.',
        gps_fix_type: 3,
        satellites_visible: 5,
      },
    });

    expect(result[0]).toMatchObject({
      hw_id: '1',
      position: [0, 0, 0],
      noMapFix: true,
      global_position_valid: false,
      position_unavailable_reason: 'GPS fix present, waiting for valid PX4 global position.',
    });
  });

  it('keeps raw GPS MSL altitude available even when map coordinates are invalid', () => {
    const result = buildGlobeDroneViewModels({
      1: {
        hw_id: 1,
        position_lat: 0,
        position_long: 0,
        position_alt: 0,
        gps_raw_altitude_m: 1280.4,
        global_position_valid: false,
        gps_fix_type: 3,
      },
    });

    expect(result[0]).toMatchObject({
      noMapFix: true,
      altitude: 1280.4,
      altitude_source: 'absolute_msl',
      altitude_label: 'MSL',
      altitude_available: true,
    });
  });

  it('uses LOCAL_POSITION_NED height when operating without a GPS/global map fix', () => {
    const result = buildGlobeDroneViewModels({
      1: {
        hw_id: 1,
        position_lat: 0,
        position_long: 0,
        position_alt: 0,
        global_position_valid: false,
        local_position_ok: true,
        local_position_down: -4.25,
        local_position_time_boot_ms: 12345,
      },
    });

    expect(result[0]).toMatchObject({
      noMapFix: true,
      altitude: 4.25,
      altitude_source: 'local_ned',
      altitude_label: 'LCL',
      altitude_available: true,
    });
  });

  it('uses the same receipt clock and current-position aging as Overview during silence', () => {
    const server = 1800000000000, browser = server + 3600000;
    const row = attachDroneRuntimeClock({ hw_id: '1', update_time: server / 1000,
      position_lat: 35, position_long: 51, global_position_valid: true,
      global_position_age_ms: 0, global_position_timestamp_ms: server },
    { receivedAtMs: browser, serverNowMs: server });
    expect(buildGlobeDroneViewModels({ 1: row }, [], browser)[0].noMapFix).toBe(false);
    expect(buildGlobeDroneViewModels({ 1: row }, [], browser + 11000)[0].noMapFix).toBe(true);
  });
});
