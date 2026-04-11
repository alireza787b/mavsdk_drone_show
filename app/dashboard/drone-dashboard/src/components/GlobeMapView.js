// src/components/GlobeMapView.js
// 2D map view for drone visualization — dual-provider (Mapbox + Leaflet fallback)

import React, { useEffect, useMemo, useRef } from 'react';
import PropTypes from 'prop-types';
import { useMapContext } from '../contexts/MapContext';
import LeafletMapBase from './map/LeafletMapBase';
import MapFallbackBanner from './map/MapFallbackBanner';
import MapProviderToggle from './map/MapProviderToggle';
import { MAP_PROVIDERS } from '../config/mapConfig';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { Marker as LeafletMarker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import '../styles/GlobeView.css';

// Conditional Mapbox imports
let MapboxMap, MapboxMarker;
let mapboxAvailable = false;
let mapboxToken = '';

try {
  const rgl = require('react-map-gl');
  MapboxMap = rgl.Map || rgl.default;
  MapboxMarker = rgl.Marker;
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxToken = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN || '';
  mapboxAvailable = !!mapboxToken;
} catch (e) {
  // Mapbox not available — Leaflet fallback will be used
}

// Note: divIcon HTML must use inline styles — Leaflet injects outside React's CSS scope
const createDroneIcon = (identityLabel) =>
  L.divIcon({
    html: `<div style="min-width:24px;height:24px;padding:0 6px;background:var(--color-primary,#00d4ff);border-radius:999px;border:2px solid #fff;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:700;color:#000">${identityLabel}</div>`,
    className: '',
    iconSize: [48, 24],
    iconAnchor: [24, 12],
  });

const LeafletInvalidateSize = () => {
  const map = useMap();

  useEffect(() => {
    const resize = () => map.invalidateSize(false);
    const animationFrame = requestAnimationFrame(resize);
    const timeoutId = window.setTimeout(resize, 150);

    return () => {
      cancelAnimationFrame(animationFrame);
      window.clearTimeout(timeoutId);
    };
  }, [map]);

  return null;
};

const GlobeMapView = ({ drones }) => {
  const { provider, isMapboxAvailable: ctxMapboxAvailable } = useMapContext();
  const useLeaflet = provider === MAP_PROVIDERS.LEAFLET || !ctxMapboxAvailable || !mapboxAvailable;
  const mapboxRef = useRef(null);

  // Compute center and valid drones from average drone position
  const { center, validDrones } = useMemo(() => {
    const valid = drones.filter(d => d.position[0] !== 0 || d.position[1] !== 0);
    if (valid.length === 0) return { center: { lat: 0, lng: 0 }, validDrones: valid };
    const avgLat = valid.reduce((sum, d) => sum + d.position[0], 0) / valid.length;
    const avgLng = valid.reduce((sum, d) => sum + d.position[1], 0) / valid.length;
    return { center: { lat: avgLat, lng: avgLng }, validDrones: valid };
  }, [drones]);

  useEffect(() => {
    if (useLeaflet || !mapboxRef.current) {
      return undefined;
    }

    const resize = () => {
      mapboxRef.current?.resize?.();
    };

    const animationFrame = requestAnimationFrame(resize);
    const timeoutId = window.setTimeout(resize, 150);

    return () => {
      cancelAnimationFrame(animationFrame);
      window.clearTimeout(timeoutId);
    };
  }, [useLeaflet, center.lat, center.lng, validDrones.length]);

  return (
    <div className="globe-map-container">
      {useLeaflet && <MapFallbackBanner />}
      <MapProviderToggle />

      {!useLeaflet && mapboxAvailable ? (
        <MapboxMap
          ref={mapboxRef}
          initialViewState={{
            latitude: center.lat,
            longitude: center.lng,
            zoom: validDrones.length > 0 ? 15 : 3,
          }}
          mapboxAccessToken={mapboxToken}
          mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
          style={{ width: '100%', height: '100%' }}
        >
          {validDrones.map(drone => (
            <MapboxMarker
              key={drone[FIELD_NAMES.HW_ID]}
              latitude={drone.position[0]}
              longitude={drone.position[1]}
              anchor="center"
            >
              <div className="globe-drone-marker">
                {formatCompactDroneIdentity(drone.pos_id, drone[FIELD_NAMES.HW_ID], `H${drone[FIELD_NAMES.HW_ID]}`)}
              </div>
            </MapboxMarker>
          ))}
        </MapboxMap>
      ) : (
        <LeafletMapBase
          center={[center.lat || 0, center.lng || 0]}
          zoom={validDrones.length > 0 ? 15 : 3}
          defaultLayer="esriSatellite"
          showLayerControl={false}
          style={{ width: '100%', height: '100%' }}
        >
          <LeafletInvalidateSize />
          {validDrones.map(drone => (
            <LeafletMarker
              key={drone[FIELD_NAMES.HW_ID]}
              position={[drone.position[0], drone.position[1]]}
              icon={createDroneIcon(formatCompactDroneIdentity(drone.pos_id, drone[FIELD_NAMES.HW_ID], `H${drone[FIELD_NAMES.HW_ID]}`))}
            >
              <Popup>
                <div>
                  <strong>{formatCompactDroneIdentity(drone.pos_id, drone[FIELD_NAMES.HW_ID], `H${drone[FIELD_NAMES.HW_ID]}`)}</strong>
                  <br />
                  State: {drone.state}
                  <br />
                  Alt: {drone.altitude?.toFixed(1)}m
                </div>
              </Popup>
            </LeafletMarker>
          ))}
        </LeafletMapBase>
      )}
    </div>
  );
};

GlobeMapView.propTypes = {
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.string.isRequired,
    pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    position: PropTypes.arrayOf(PropTypes.number).isRequired,
    state: PropTypes.string,
    altitude: PropTypes.number,
  })).isRequired,
};

export default GlobeMapView;
