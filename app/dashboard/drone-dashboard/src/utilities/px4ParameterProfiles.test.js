import { buildMdsParameterProfileFile } from './px4ParameterProfiles';

describe('px4ParameterProfiles', () => {
  it('builds a typed MDS profile export bundle', () => {
    const result = buildMdsParameterProfileFile({
      profile_id: 'fleet_geofence_guardrail',
      name: 'Fleet Geofence Guardrail',
      description: 'Starter guardrail bundle',
      recommended_scope: 'fleet',
      tags: ['starter', 'geofence'],
      entries: [
        {
          component_id: 1,
          name: 'GF_ACTION',
          value_type: 'int',
          value: 3,
        },
      ],
    });

    expect(result.filename).toBe('fleet_geofence_guardrail.json');
    expect(result.text).toContain('"profile_id": "fleet_geofence_guardrail"');
    expect(result.text).toContain('"recommended_scope": "fleet"');
    expect(result.text).toContain('"name": "GF_ACTION"');
  });
});
