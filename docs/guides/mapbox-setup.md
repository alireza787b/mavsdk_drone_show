# Mapbox Setup

MDS works without Mapbox. When no token is configured, map views use the
Leaflet tile fallback. Add a Mapbox token only when you want Mapbox satellite,
terrain, and drawing features.

## Configure The Dashboard

Set the token in the dashboard environment file:

```bash
cd app/dashboard/drone-dashboard
printf 'REACT_APP_MAPBOX_ACCESS_TOKEN=YOUR_MAPBOX_PUBLIC_TOKEN\n' >> .env
```

Then rebuild or restart the dashboard service so the React app receives the
new build-time value.

```bash
npm run build
```

If you use the GCS installer, the interactive setup already prompts for the
same value and writes `REACT_APP_MAPBOX_ACCESS_TOKEN` into the dashboard
`.env`.

## Operational Notes

- Keep Mapbox tokens out of commits.
- Use a token scoped to public styles/tiles, not a broad account token.
- The UI falls back to Leaflet automatically if the token is missing or
  unreachable.
- A missing-token warning in the map view is not a flight blocker; it only
  means Mapbox-specific map features are unavailable.
