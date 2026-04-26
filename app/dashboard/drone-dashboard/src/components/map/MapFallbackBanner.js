// src/components/map/MapFallbackBanner.js
// Dismissible notification shown when Mapbox -> Leaflet fallback occurs

import React, { useState } from 'react';
import { useMapContext } from '../../contexts/MapContext';
import { buildDocsUrl, getRouteDoc } from '../../config/routeDocs';
import { GIT_BRANCH, GIT_REPO } from '../../version';
import '../../styles/MapCommon.css';

const SESSION_KEY = 'mds_fallback_banner_dismissed';
const MAPBOX_GUIDE_URL = buildDocsUrl(getRouteDoc('/globe-view'), {
  repoUrl: GIT_REPO,
  branch: GIT_BRANCH,
});

const MapFallbackBanner = () => {
  const { provider, isMapboxAvailable, fallbackReason } = useMapContext();
  const [dismissed, setDismissed] = useState(
    () => sessionStorage.getItem(SESSION_KEY) === '1'
  );

  // Only show when we fell back to leaflet and mapbox isn't available
  if (dismissed || provider !== 'leaflet' || isMapboxAvailable) {
    return null;
  }

  const handleDismiss = () => {
    setDismissed(true);
    sessionStorage.setItem(SESSION_KEY, '1');
  };

  return (
    <div className="mds-map-fallback-banner">
      <span className="mds-map-fallback-banner-text">
        Mapbox unavailable — using Leaflet tile fallback.
        {fallbackReason && <small style={{ opacity: 0.7 }}> ({fallbackReason})</small>}
      </span>
      <div className="mds-map-fallback-banner-actions">
        <a
          href={MAPBOX_GUIDE_URL}
          target="_blank"
          rel="noreferrer"
          data-help="Open Mapbox setup guide"
        >
          Setup
        </a>
        <button onClick={handleDismiss} data-help="Dismiss">
          Dismiss
        </button>
      </div>
    </div>
  );
};

export default MapFallbackBanner;
