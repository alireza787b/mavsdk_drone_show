# PX4 Parameter Profiles

Repo-backed PX4 parameter profiles live here.

Design rules:

- one JSON file per profile
- filename must match `profile_id`
- entries use the same typed `component_id/name/value_type/value` contract as the
  `px4-params` APIs
- GCS is the source of truth for listing/loading profiles
- drones never read these files directly

Current usage:

- operators can review these profiles in the dashboard `PX4 Parameters` page
- profiles can be exported as typed MDS JSON
- batch apply uses the same tracked `px4-params` patch-job path as manual writes

Minimal shape:

```json
{
  "profile_id": "fleet_geofence_guardrail",
  "name": "Fleet Geofence Guardrail",
  "description": "Starter fleet safety baseline for geofence and RC exception handling.",
  "recommended_scope": "fleet",
  "tags": ["starter", "safety", "geofence"],
  "entries": [
    {
      "component_id": 1,
      "name": "GF_ACTION",
      "value_type": "int",
      "value": 3
    }
  ]
}
```
