// src/components/map/LeafletMapBase.js
// Reusable Leaflet map wrapper with a single controlled tile layer.

import React, { useEffect, useId, useState } from 'react';
import { MapContainer, TileLayer, useMapEvents } from 'react-leaflet';
import {
  LEAFLET_DEFAULTS,
  getUserTilePreference,
  setUserTilePreference,
  getLeafletTileLayerConfig,
  resolveTileLayerKey,
  TILE_LAYERS,
} from '../../config/mapConfig';
import '../../styles/MapCommon.css';

const LeafletMapEventBridge = ({ eventHandlers = {} }) => {
  useMapEvents(eventHandlers);
  return null;
};

const LeafletMapBase = ({
  center = [35.6895, 139.6917],
  zoom = 13,
  style,
  children,
  showLayerControl = true,
  defaultLayer,
  onClick,
  className = '',
  ...rest
}) => {
  const { eventHandlers: providedEventHandlers = {}, ...mapContainerProps } = rest;
  const selectId = useId();
  const [activeLayerKey, setActiveLayerKey] = useState(() =>
    resolveTileLayerKey(defaultLayer || getUserTilePreference())
  );
  const [tileFallbackNotice, setTileFallbackNotice] = useState('');

  useEffect(() => {
    setActiveLayerKey(resolveTileLayerKey(defaultLayer || getUserTilePreference()));
    setTileFallbackNotice('');
  }, [defaultLayer]);

  const resolvedActiveLayer = getLeafletTileLayerConfig(activeLayerKey);

  const handleLayerChange = (event) => {
    const nextKey = resolveTileLayerKey(event.target.value);
    setActiveLayerKey(nextKey);
    setTileFallbackNotice('');
    setUserTilePreference(nextKey);
  };

  const handleTileError = () => {
    if (resolvedActiveLayer.key === 'osm') {
      return;
    }
    setActiveLayerKey('osm');
    setTileFallbackNotice(`${resolvedActiveLayer.name} tiles are unavailable. Showing OpenStreetMap fallback.`);
  };

  const mapEventHandlers = {
    ...providedEventHandlers,
    ...(onClick ? { click: onClick } : {}),
  };

  return (
    <div className={`mds-map-container ${className}`} style={style}>
      {showLayerControl && (
        <div className="mds-map-overlay mds-tile-layer-control">
          <label htmlFor={selectId}>Tile Layer</label>
          <select
            id={selectId}
            value={resolvedActiveLayer.key}
            onChange={handleLayerChange}
          >
            {Object.entries(TILE_LAYERS).map(([key, cfg]) => (
              <option key={key} value={key}>
                {cfg.name}
              </option>
            ))}
          </select>
        </div>
      )}
      {tileFallbackNotice && (
        <div className="mds-map-overlay mds-tile-fallback-notice" role="status">
          {tileFallbackNotice}
        </div>
      )}

      <MapContainer
        center={center}
        zoom={zoom}
        minZoom={LEAFLET_DEFAULTS.minZoom}
        maxZoom={LEAFLET_DEFAULTS.maxZoom}
        maxBounds={LEAFLET_DEFAULTS.maxBounds}
        maxBoundsViscosity={LEAFLET_DEFAULTS.maxBoundsViscosity}
        worldCopyJump={LEAFLET_DEFAULTS.worldCopyJump}
        scrollWheelZoom
        style={{ width: '100%', height: '100%' }}
        {...mapContainerProps}
      >
        <LeafletMapEventBridge eventHandlers={mapEventHandlers} />
        <TileLayer
          key={resolvedActiveLayer.key}
          url={resolvedActiveLayer.url}
          attribution={resolvedActiveLayer.attribution}
          subdomains={resolvedActiveLayer.subdomains}
          maxNativeZoom={resolvedActiveLayer.maxNativeZoom}
          maxZoom={LEAFLET_DEFAULTS.maxZoom}
          noWrap={true}
          eventHandlers={{ tileerror: handleTileError }}
        />

        {children}
      </MapContainer>
    </div>
  );
};

export default LeafletMapBase;
