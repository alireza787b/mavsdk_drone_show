// src/components/GlobeMapView.js
// 2D map view for drone visualization — dual-provider (Mapbox + Leaflet fallback)

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { FaCrosshairs, FaSatelliteDish } from 'react-icons/fa';
import { useMapContext } from '../contexts/MapContext';
import LeafletMapBase from './map/LeafletMapBase';
import MapFallbackBanner from './map/MapFallbackBanner';
import MapProviderToggle from './map/MapProviderToggle';
import TacticalDroneCard from './TacticalDroneCard';
import { MAP_PROVIDERS } from '../config/mapConfig';
import { FIELD_NAMES } from '../constants/fieldMappings';
import { Marker as LeafletMarker, Popup, useMap } from 'react-leaflet';
import L from 'leaflet';
import { formatCompactDroneIdentity } from '../utilities/missionIdentityUtils';
import { getPlotThemeColors } from '../utilities/plotThemeColors';
import '../styles/GlobeView.css';

// Conditional Mapbox imports
let MapboxMap, MapboxMarker, MapboxNavigationControl, MapboxFullscreenControl, MapboxScaleControl;
let mapboxAvailable = false;
let mapboxToken = '';

try {
  const rgl = require('react-map-gl');
  MapboxMap = rgl.Map || rgl.default;
  MapboxMarker = rgl.Marker;
  MapboxNavigationControl = rgl.NavigationControl;
  MapboxFullscreenControl = rgl.FullscreenControl;
  MapboxScaleControl = rgl.ScaleControl;
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxToken = process.env.REACT_APP_MAPBOX_ACCESS_TOKEN || '';
  mapboxAvailable = !!mapboxToken;
} catch (e) {
  // Mapbox not available — Leaflet fallback will be used
}

// Note: divIcon HTML must use inline styles — Leaflet injects outside React's CSS scope
const DEFAULT_DRONE_MARKER_COLOR = 'dodgerblue';
const HEX_COLOR_PATTERN = /^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i;

const resolveMarkerColor = (candidate, fallback = DEFAULT_DRONE_MARKER_COLOR) => {
  const normalized = String(candidate || '').trim();
  return HEX_COLOR_PATTERN.test(normalized) ? normalized : fallback;
};

const createDroneIcon = (identityLabel, markerColor, selected = false, runtimeClass = '', themeColors = getPlotThemeColors()) => {
  const dimmed = runtimeClass === 'offline' || runtimeClass === 'never-seen';
  const borderStyle = runtimeClass === 'lost' || runtimeClass === 'never-seen' ? 'dashed' : 'solid';
  const fillColor = resolveMarkerColor(markerColor, themeColors.primary);
  const ringWidth = selected ? 5 : 0;
  return (
  L.divIcon({
    html: `<div style="min-width:${selected ? 32 : 24}px;height:${selected ? 32 : 24}px;padding:0 7px;background:${fillColor};border-radius:999px;border:${selected ? 3 : 2}px ${borderStyle} ${themeColors.paper};display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:800;color:${themeColors.textInverse};opacity:${dimmed ? 0.42 : 1};filter:${dimmed ? 'grayscale(0.7)' : 'none'};box-shadow:0 0 0 ${ringWidth}px ${themeColors.surface},0 10px 22px ${themeColors.grid}">${identityLabel}</div>`,
    className: '',
    iconSize: selected ? [58, 32] : [48, 24],
    iconAnchor: selected ? [29, 16] : [24, 12],
  })
  );
};

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

function fitLeafletMapToFleet(map, validDrones = []) {
  if (!map || validDrones.length === 0) {
    return;
  }

  if (validDrones.length === 1) {
    map.flyTo?.([validDrones[0].position[0], validDrones[0].position[1]], 17, { animate: true, duration: 0.6 });
    return;
  }

  const bounds = L.latLngBounds(validDrones.map((drone) => [drone.position[0], drone.position[1]]));
  if (bounds.isValid()) {
    map.fitBounds(bounds, { padding: [72, 72], maxZoom: 17, animate: true, duration: 0.6 });
  }
}

const LeafletFleetFitBridge = ({ validDrones, fitSignal }) => {
  const map = useMap();
  const validDronesRef = useRef(validDrones);

  useEffect(() => {
    validDronesRef.current = validDrones;
  }, [validDrones]);

  useEffect(() => {
    const timeoutId = window.setTimeout(() => fitLeafletMapToFleet(map, validDronesRef.current), 250);
    return () => window.clearTimeout(timeoutId);
  }, [fitSignal, map, validDrones.length]);

  return null;
};

LeafletFleetFitBridge.propTypes = {
  validDrones: PropTypes.arrayOf(PropTypes.object).isRequired,
  fitSignal: PropTypes.number.isRequired,
};

const LeafletDroneMarker = ({ drone, selected, onSelect }) => {
  const markerRef = useRef(null);
  const droneId = String(drone[FIELD_NAMES.HW_ID]);
  const identityLabel = formatCompactDroneIdentity(drone.pos_id, drone[FIELD_NAMES.HW_ID], `H${drone[FIELD_NAMES.HW_ID]}`);
  const themeColors = getPlotThemeColors();

  useEffect(() => {
    if (selected) {
      markerRef.current?.openPopup?.();
    }
  }, [selected]);

  return (
    <LeafletMarker
      ref={markerRef}
      position={[drone.position[0], drone.position[1]]}
      icon={createDroneIcon(identityLabel, drone.marker_color, selected, drone.runtime_indicator_class, themeColors)}
      eventHandlers={{
        click: () => onSelect(droneId),
        popupclose: () => {
          if (selected) onSelect(null);
        },
      }}
    >
      <Popup className="tactical-drone-leaflet-popup" minWidth={250} maxWidth={320} closeButton={false}>
        <TacticalDroneCard drone={drone} onClose={() => onSelect(null)} />
      </Popup>
    </LeafletMarker>
  );
};

LeafletDroneMarker.propTypes = {
  drone: PropTypes.object.isRequired,
  selected: PropTypes.bool.isRequired,
  onSelect: PropTypes.func.isRequired,
};

const GlobeMapView = ({ drones, selectedDroneId, onSelectDrone }) => {
  const { provider, isMapboxAvailable: ctxMapboxAvailable } = useMapContext();
  const useLeaflet = provider === MAP_PROVIDERS.LEAFLET || !ctxMapboxAvailable || !mapboxAvailable;
  const mapboxRef = useRef(null);
  const [leafletFitSignal, setLeafletFitSignal] = useState(0);
  const themeColors = getPlotThemeColors();

  // Compute center and valid drones from average drone position
  const { center, validDrones } = useMemo(() => {
    const valid = drones.filter(d => d.position[0] !== 0 || d.position[1] !== 0);
    if (valid.length === 0) return { center: { lat: 0, lng: 0 }, validDrones: valid };
    const avgLat = valid.reduce((sum, d) => sum + d.position[0], 0) / valid.length;
    const avgLng = valid.reduce((sum, d) => sum + d.position[1], 0) / valid.length;
    return { center: { lat: avgLat, lng: avgLng }, validDrones: valid };
  }, [drones]);
  const selectedDrone = useMemo(
    () => drones.find((drone) => String(drone[FIELD_NAMES.HW_ID]) === String(selectedDroneId || '')) || null,
    [drones, selectedDroneId]
  );
  const selectedDroneHasMapFix = selectedDrone
    ? validDrones.some((drone) => String(drone[FIELD_NAMES.HW_ID]) === String(selectedDrone[FIELD_NAMES.HW_ID]))
    : false;

  const fitMapboxToFleet = useCallback(() => {
    if (useLeaflet || !mapboxRef.current || validDrones.length === 0) {
      return;
    }

    const map = mapboxRef.current?.getMap?.() || mapboxRef.current;
    if (validDrones.length === 1) {
      map.flyTo?.({
        center: [validDrones[0].position[1], validDrones[0].position[0]],
        zoom: 17,
        duration: 600,
      });
      return;
    }

    const lats = validDrones.map((drone) => drone.position[0]);
    const lngs = validDrones.map((drone) => drone.position[1]);
    map.fitBounds?.(
      [
        [Math.min(...lngs), Math.min(...lats)],
        [Math.max(...lngs), Math.max(...lats)],
      ],
      { padding: 72, maxZoom: 17, duration: 600 }
    );
  }, [useLeaflet, validDrones]);

  const fitLeafletToFleet = useCallback(() => {
    setLeafletFitSignal((current) => current + 1);
  }, []);

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

  useEffect(() => {
    if (!useLeaflet) {
      const timeoutId = window.setTimeout(fitMapboxToFleet, 250);
      return () => window.clearTimeout(timeoutId);
    }
    return undefined;
  }, [fitMapboxToFleet, useLeaflet]);

  const handleMapBackgroundPointerDown = useCallback((event) => {
    if (!selectedDroneId) {
      return;
    }

    const target = event.target;
    if (
      target?.closest?.(
        '.globe-map-drone-card-popover, .globe-map-selected-fallback, .globe-drone-marker, .leaflet-marker-icon, .leaflet-popup, .globe-map-ops-bar, .mapboxgl-ctrl, .leaflet-control'
      )
    ) {
      return;
    }

    onSelectDrone(null);
  }, [onSelectDrone, selectedDroneId]);

  return (
    <div
      className="globe-map-container"
      onPointerDown={handleMapBackgroundPointerDown}
      onPointerDownCapture={handleMapBackgroundPointerDown}
      onTouchStartCapture={handleMapBackgroundPointerDown}
    >
      {useLeaflet && <MapFallbackBanner />}
      <div className="globe-map-ops-bar">
        <div className="globe-map-ops-bar__badge" aria-label="Live telemetry map">
          <FaSatelliteDish aria-hidden="true" />
          <span>{validDrones.length}</span>
        </div>
        <MapProviderToggle />
        <button
          type="button"
          className="globe-map-ops-bar__button"
          onClick={useLeaflet ? fitLeafletToFleet : fitMapboxToFleet}
          disabled={validDrones.length === 0}
          aria-label="Fit map to live fleet"
          data-help="Fit map to live fleet"
        >
          <FaCrosshairs aria-hidden="true" />
          <span>Fit</span>
        </button>
      </div>
      {selectedDrone && !selectedDroneHasMapFix && (
        <div
          className="globe-map-selected-fallback"
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => event.stopPropagation()}
        >
          <div
            className="globe-map-selected-fallback__note"
            aria-label="This drone is selected but does not currently have a non-zero GPS coordinate for the map."
          >
            No map fix
          </div>
          <TacticalDroneCard drone={selectedDrone} onClose={() => onSelectDrone(null)} />
        </div>
      )}

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
          cooperativeGestures={true}
        >
          {MapboxNavigationControl && <MapboxNavigationControl position="bottom-right" visualizePitch />}
          {MapboxFullscreenControl && <MapboxFullscreenControl position="bottom-right" />}
          {MapboxScaleControl && <MapboxScaleControl position="bottom-left" />}
          {validDrones.map(drone => {
            const droneId = String(drone[FIELD_NAMES.HW_ID]);
            const selected = String(selectedDroneId || '') === droneId;
            const identityLabel = formatCompactDroneIdentity(drone.pos_id, drone[FIELD_NAMES.HW_ID], `H${drone[FIELD_NAMES.HW_ID]}`);
            return (
              <MapboxMarker
                key={droneId}
                latitude={drone.position[0]}
                longitude={drone.position[1]}
                anchor="center"
              >
                <div className="globe-map-marker-wrapper">
                  <button
                    type="button"
                    className={[
                      'globe-drone-marker',
                      selected ? 'selected' : '',
                      drone.runtime_indicator_class ? `runtime-${drone.runtime_indicator_class}` : '',
                    ].filter(Boolean).join(' ')}
                    style={{ '--mds-drone-marker-color': resolveMarkerColor(drone.marker_color, themeColors.primary) }}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectDrone(droneId);
                    }}
                    aria-label={`Open ${identityLabel} tactical card`}
                  >
                    {identityLabel}
                  </button>
                  {selected && (
                    <div
                      className="globe-map-drone-card-popover"
                      onPointerDown={(event) => event.stopPropagation()}
                      onClick={(event) => event.stopPropagation()}
                    >
                      <TacticalDroneCard drone={drone} onClose={() => onSelectDrone(null)} />
                    </div>
                  )}
                </div>
              </MapboxMarker>
            );
          })}
        </MapboxMap>
      ) : (
        <LeafletMapBase
          center={[center.lat || 0, center.lng || 0]}
          zoom={validDrones.length > 0 ? 15 : 3}
          defaultLayer="esriSatellite"
          showLayerControl={true}
          style={{ width: '100%', height: '100%' }}
        >
          <LeafletInvalidateSize />
          <LeafletFleetFitBridge validDrones={validDrones} fitSignal={leafletFitSignal} />
          {validDrones.map(drone => (
            <LeafletDroneMarker
              key={drone[FIELD_NAMES.HW_ID]}
              drone={drone}
              selected={String(selectedDroneId || '') === String(drone[FIELD_NAMES.HW_ID])}
              onSelect={onSelectDrone}
            />
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
    state: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    stateLabel: PropTypes.string,
    altitude: PropTypes.number,
    marker_color: PropTypes.string,
  })).isRequired,
  selectedDroneId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  onSelectDrone: PropTypes.func,
};

GlobeMapView.defaultProps = {
  selectedDroneId: null,
  onSelectDrone: () => {},
};

export default GlobeMapView;
