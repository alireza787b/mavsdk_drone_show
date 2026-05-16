import React, { useMemo } from 'react';
import {
  CircleMarker,
  Polyline,
} from 'react-leaflet';

import { useMapContext } from '../../contexts/MapContext';
import LeafletMapBase from '../map/LeafletMapBase';
import MapFallbackBanner from '../map/MapFallbackBanner';
import MapProviderToggle from '../map/MapProviderToggle';
import '../../styles/SwarmRouteMapEditor.css';

let MapboxMap;
let MapboxMarker;
let MapboxSource;
let MapboxLayer;
let mapboxAvailable = false;

try {
  const mapboxComponents = require('react-map-gl');
  MapboxMap = mapboxComponents.Map || mapboxComponents.default;
  MapboxMarker = mapboxComponents.Marker;
  MapboxSource = mapboxComponents.Source;
  MapboxLayer = mapboxComponents.Layer;
  require('mapbox-gl/dist/mapbox-gl.css');
  mapboxAvailable = true;
} catch {
  mapboxAvailable = false;
}

const DEFAULT_CENTER = { latitude: 35.6892, longitude: 51.3890, zoom: 12 };

const getWaypointLat = (waypoint) => Number(waypoint.latitude ?? waypoint.lat);
const getWaypointLng = (waypoint) => Number(waypoint.longitude ?? waypoint.lng);

const buildRouteGeoJson = (waypoints = []) => ({
  type: 'Feature',
  geometry: {
    type: 'LineString',
    coordinates: waypoints
      .filter((waypoint) => Number.isFinite(getWaypointLat(waypoint)) && Number.isFinite(getWaypointLng(waypoint)))
      .map((waypoint) => [getWaypointLng(waypoint), getWaypointLat(waypoint)]),
  },
  properties: {},
});

const SwarmRouteMapEditor = ({
  waypoints = [],
  onAddWaypoint,
  onSelectWaypoint,
  selectedWaypointId = '',
  altitudeLabel = 'MSL',
}) => {
  const { provider, isMapboxAvailable, mapboxToken } = useMapContext();
  const useLeaflet = provider === 'leaflet' || !isMapboxAvailable || !mapboxAvailable;
  const firstWaypoint = waypoints.find((waypoint) => (
    Number.isFinite(getWaypointLat(waypoint)) && Number.isFinite(getWaypointLng(waypoint))
  ));
  const initialViewState = {
    latitude: firstWaypoint ? getWaypointLat(firstWaypoint) : DEFAULT_CENTER.latitude,
    longitude: firstWaypoint ? getWaypointLng(firstWaypoint) : DEFAULT_CENTER.longitude,
    zoom: firstWaypoint ? 14 : DEFAULT_CENTER.zoom,
  };
  const lineCoordinates = useMemo(
    () => waypoints
      .filter((waypoint) => Number.isFinite(getWaypointLat(waypoint)) && Number.isFinite(getWaypointLng(waypoint)))
      .map((waypoint) => [getWaypointLat(waypoint), getWaypointLng(waypoint)]),
    [waypoints],
  );
  const routeGeoJson = useMemo(() => buildRouteGeoJson(waypoints), [waypoints]);

  const handleMapboxClick = (event) => {
    const lat = Number(event?.lngLat?.lat);
    const lng = Number(event?.lngLat?.lng);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      onAddWaypoint?.({ latitude: lat, longitude: lng, source: 'map' });
    }
  };

  const handleLeafletClick = (event) => {
    const lat = Number(event?.latlng?.lat);
    const lng = Number(event?.latlng?.lng);
    if (Number.isFinite(lat) && Number.isFinite(lng)) {
      onAddWaypoint?.({ latitude: lat, longitude: lng, source: 'map' });
    }
  };

  return (
    <section className="swarm-route-map-editor" aria-label="Leader route map editor">
      <div className="swarm-route-map-editor__bar">
        <div>
          <strong>Leader route map</strong>
          <span>{waypoints.length} waypoint{waypoints.length === 1 ? '' : 's'} · {altitudeLabel}</span>
        </div>
        <MapProviderToggle />
      </div>
      <div className="swarm-route-map-editor__map">
        {useLeaflet ? (
          <>
            <MapFallbackBanner />
            <LeafletMapBase
              center={[initialViewState.latitude, initialViewState.longitude]}
              zoom={initialViewState.zoom}
              defaultLayer="esriSatellite"
              showLayerControl={false}
              onClick={handleLeafletClick}
            >
              {lineCoordinates.length > 1 ? (
                <Polyline positions={lineCoordinates} pathOptions={{ color: '#2563eb', weight: 4 }} />
              ) : null}
              {waypoints.map((waypoint, index) => {
                const lat = getWaypointLat(waypoint);
                const lng = getWaypointLng(waypoint);
                if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
                  return null;
                }
                return (
                  <CircleMarker
                    key={waypoint.id || index}
                    center={[lat, lng]}
                    radius={waypoint.id === selectedWaypointId ? 8 : 6}
                    pathOptions={{
                      color: waypoint.id === selectedWaypointId ? '#f59e0b' : '#2563eb',
                      fillColor: '#ffffff',
                      fillOpacity: 1,
                      weight: 3,
                    }}
                    eventHandlers={{
                      click: (event) => {
                        event.originalEvent?.stopPropagation?.();
                        onSelectWaypoint?.(waypoint);
                      },
                    }}
                  />
                );
              })}
            </LeafletMapBase>
          </>
        ) : (
          <MapboxMap
            initialViewState={initialViewState}
            mapboxAccessToken={mapboxToken}
            mapStyle="mapbox://styles/mapbox/satellite-streets-v12"
            onClick={handleMapboxClick}
            style={{ width: '100%', height: '100%' }}
          >
            {routeGeoJson.geometry.coordinates.length > 1 && MapboxSource && MapboxLayer ? (
              <MapboxSource id="swarm-leader-route" type="geojson" data={routeGeoJson}>
                <MapboxLayer
                  id="swarm-leader-route-line"
                  type="line"
                  paint={{
                    'line-color': '#2563eb',
                    'line-width': 4,
                    'line-opacity': 0.9,
                  }}
                />
              </MapboxSource>
            ) : null}
            {MapboxMarker && waypoints.map((waypoint, index) => {
              const lat = getWaypointLat(waypoint);
              const lng = getWaypointLng(waypoint);
              if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
                return null;
              }
              return (
                <MapboxMarker key={waypoint.id || index} latitude={lat} longitude={lng} anchor="center">
                  <button
                    type="button"
                    className={`swarm-route-map-editor__marker ${waypoint.id === selectedWaypointId ? 'is-active' : ''}`}
                    onClick={(event) => {
                      event.stopPropagation();
                      onSelectWaypoint?.(waypoint);
                    }}
                    aria-label={`Edit waypoint ${index + 1}`}
                  >
                    {index + 1}
                  </button>
                </MapboxMarker>
              );
            })}
          </MapboxMap>
        )}
        <div className="swarm-route-map-editor__hint" role="status">
          Click map to add waypoint
        </div>
      </div>
    </section>
  );
};

export default SwarmRouteMapEditor;
