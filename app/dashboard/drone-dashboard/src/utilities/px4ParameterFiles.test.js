import { buildQgcParameterFile } from './px4ParameterFiles';

describe('px4ParameterFiles', () => {
  it('builds a QGC-compatible export for int/float rows and reports skipped custom params', () => {
    const result = buildQgcParameterFile({
      snapshot: {
        snapshot_id: 'snap-1',
        hw_id: '7',
        component_id: 1,
      },
      rows: [
        { component_id: 1, name: 'MAV_SYS_ID', value_type: 'int', value: 7 },
        { component_id: 1, name: 'MPC_XY_VEL_MAX', value_type: 'float', value: 12.5 },
        { component_id: 1, name: 'SYS_AUTOSTART', value_type: 'custom', value: 'foo' },
      ],
    });

    expect(result.filename).toBe('px4-params-7-snap-1.params');
    expect(result.skippedRows).toEqual(['SYS_AUTOSTART']);
    expect(result.text).toContain('7\t1\tMAV_SYS_ID\t7\t6');
    expect(result.text).toContain('7\t1\tMPC_XY_VEL_MAX\t12.5\t9');
  });
});
