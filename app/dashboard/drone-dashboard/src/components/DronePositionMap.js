import React, { useEffect, useMemo } from 'react';
import PropTypes from 'prop-types';
import {
  CircleMarker,
  Marker,
  Polyline,
  Popup,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import LatLon from 'geodesy/latlon-spherical';

import LeafletMapBase from './map/LeafletMapBase';
import { normalizeComparableId } from '../utilities/missionIdentityUtils';
import '../styles/DronePositionMap.css';

const STATUS_COLORS = {
  ok: '#27ae60',
  warning: '#f39c12',
  error: '#e74c3c',
  no_telemetry: '#94a3b8',
};

const LaunchMapViewport = ({ points }) => {
  const map = useMap();

  useEffect(() => {
    const validPoints = (points || []).filter(
      (point) => Array.isArray(point) && Number.isFinite(point[0]) && Number.isFinite(point[1])
    );

    if (validPoints.length === 0) {
      return undefined;
    }

    const updateViewport = () => {
      map.invalidateSize(false);

      const bounds = L.latLngBounds(validPoints);
      if (validPoints.length === 1) {
        map.setView(validPoints[0], 18, { animate: false });
        return;
      }

      map.fitBounds(bounds.pad(0.22), {
        animate: false,
        maxZoom: 18,
      });
    };

    const animationFrame = requestAnimationFrame(updateViewport);
    const timeoutId = window.setTimeout(updateViewport, 180);

    return () => {
      cancelAnimationFrame(animationFrame);
      window.clearTimeout(timeoutId);
    };
  }, [map, points]);

  return null;
};

LaunchMapViewport.propTypes = {
  points: PropTypes.arrayOf(PropTypes.arrayOf(PropTypes.number)).isRequired,
};

const buildExpectedIcon = (label) =>
  L.divIcon({
    html: `<div class="drone-position-map__expected-marker">${label}</div>`,
    className: 'drone-position-map__expected-icon',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });

const buildOriginIcon = () =>
  L.divIcon({
    html: '<div class="drone-position-map__origin-marker">OR</div>',
    className: 'drone-position-map__origin-icon',
    iconSize: [28, 28],
    iconAnchor: [14, 14],
  });

const resolveExpectedCoordinate = (drone, trajectoryPositionsByPosId, deviationLookup, origin, forwardHeading) => {
  const hwId = String(drone.hw_id);
  const posId = normalizeComparableId(drone.pos_id, hwId) || hwId;
  const deviation = deviationLookup?.[hwId];
  const trajectoryPosition = trajectoryPositionsByPosId?.[posId];

  const expectedLat = Number(deviation?.expected?.lat);
  const expectedLon = Number(deviation?.expected?.lon);
  if (Number.isFinite(expectedLat) && Number.isFinite(expectedLon)) {
    return { posId, hwId, lat: expectedLat, lon: expectedLon };
  }

  const north = Number(
    trajectoryPosition?.x !== undefined ? trajectoryPosition.x : drone.x
  );
  const east = Number(
    trajectoryPosition?.y !== undefined ? trajectoryPosition.y : drone.y
  );

  if (!Number.isFinite(north) || !Number.isFinite(east)) {
    return null;
  }

  const distance = Math.sqrt((north ** 2) + (east ** 2));
  let rawBearingDeg = (Math.atan2(east, north) * 180) / Math.PI;
  if (rawBearingDeg < 0) {
    rawBearingDeg += 360;
  }

  const finalBearing = (rawBearingDeg + Number(forwardHeading || 0)) % 360;
  const destination = origin.destinationPoint(distance, finalBearing);

  return {
    posId,
    hwId,
    lat: destination.lat,
    lon: destination.lon,
  };
};

const DronePositionMap = ({
  originLat,
  originLon,
  drones,
  deviationData = null,
  trajectoryPositionsByPosId = {},
  forwardHeading = 0,
  onDroneClick = null,
}) => {
  const parsedOriginLat = Number(originLat);
  const parsedOriginLon = Number(originLon);
  const hasOrigin = Number.isFinite(parsedOriginLat) && Number.isFinite(parsedOriginLon);

  const mapState = useMemo(() => {
    if (!hasOrigin || !Array.isArray(drones) || drones.length === 0) {
      return {
        markers: [],
        viewportPoints: [],
        summary: {
          expected: 0,
          current: 0,
          warnings: 0,
          errors: 0,
        },
      };
    }

    const origin = new LatLon(parsedOriginLat, parsedOriginLon);
    const deviationLookup = deviationData?.deviations || {};
    const markers = [];
    const viewportPoints = [[parsedOriginLat, parsedOriginLon]];
    const summary = {
      expected: 0,
      current: 0,
      warnings: 0,
      errors: 0,
    };

    drones.forEach((drone) => {
      const expected = resolveExpectedCoordinate(
        drone,
        trajectoryPositionsByPosId,
        deviationLookup,
        origin,
        forwardHeading
      );

      if (!expected) {
        return;
      }

      const deviation = deviationLookup?.[String(drone.hw_id)] || null;
      const currentLat = Number(deviation?.current?.lat);
      const currentLon = Number(deviation?.current?.lon);
      const hasCurrent = Number.isFinite(currentLat) && Number.isFinite(currentLon);
      const status = deviation?.status || 'no_telemetry';

      summary.expected += 1;
      if (status === 'warning') {
        summary.warnings += 1;
      }
      if (status === 'error') {
        summary.errors += 1;
      }
      if (hasCurrent) {
        summary.current += 1;
      }

      viewportPoints.push([expected.lat, expected.lon]);
      if (hasCurrent) {
        viewportPoints.push([currentLat, currentLon]);
      }

      markers.push({
        ...expected,
        current: hasCurrent
          ? {
              lat: currentLat,
              lon: currentLon,
            }
          : null,
        status,
        deviationMeters: Number(deviation?.deviation?.horizontal) || 0,
        gpsQuality: deviation?.current?.gps_quality || 'unknown',
        satellites: Number(deviation?.current?.satellites) || 0,
      });
    });

    return { markers, viewportPoints, summary };
  }, [
    deviationData,
    drones,
    forwardHeading,
    hasOrigin,
    originLat,
    originLon,
    parsedOriginLat,
    parsedOriginLon,
    trajectoryPositionsByPosId,
  ]);

  if (!hasOrigin) {
    return (
      <p className="drone-position-map__empty-state">
        Set the origin first to review launch positions on the map.
      </p>
    );
  }

  if (mapState.markers.length === 0) {
    return (
      <p className="drone-position-map__empty-state">
        No launch-position coordinates are available for the current fleet.
      </p>
    );
  }

  return (
    <section className="drone-position-map" aria-label="Launch layout map">
      <div className="drone-position-map__header">
        <div>
          <h3>Launch Layout Map</h3>
          <p>Expected slots on satellite tiles, with live position overlays when telemetry is available.</p>
        </div>
        <div className="drone-position-map__summary" aria-label="Launch layout map summary">
          <span>{mapState.summary.expected} expected</span>
          <span>{mapState.summary.current} live</span>
          <span>{Number(forwardHeading || 0)}° heading</span>
          {mapState.summary.warnings > 0 && <span>{mapState.summary.warnings} warn</span>}
          {mapState.summary.errors > 0 && <span>{mapState.summary.errors} error</span>}
        </div>
      </div>

      <div className="drone-position-map__canvas">
        <LeafletMapBase
          center={[parsedOriginLat, parsedOriginLon]}
          zoom={17}
          defaultLayer="esriSatellite"
          showLayerControl={true}
          style={{ width: '100%', height: '100%' }}
        >
          <LaunchMapViewport points={mapState.viewportPoints} />

          <Marker
            position={[parsedOriginLat, parsedOriginLon]}
            icon={buildOriginIcon()}
          >
            <Popup>
              <strong>Origin</strong>
              <br />
              Latitude: {parsedOriginLat.toFixed(6)}
              <br />
              Longitude: {parsedOriginLon.toFixed(6)}
            </Popup>
          </Marker>

          {mapState.markers.map((marker) => {
            const statusColor = STATUS_COLORS[marker.status] || STATUS_COLORS.no_telemetry;
            const eventHandlers = onDroneClick
              ? { click: () => onDroneClick(marker.hwId) }
              : undefined;

            return (
              <React.Fragment key={`${marker.hwId}-${marker.posId}`}>
                <Marker
                  position={[marker.lat, marker.lon]}
                  icon={buildExpectedIcon(marker.posId)}
                  eventHandlers={eventHandlers}
                >
                  <Popup>
                    <strong>Expected slot {marker.posId}</strong>
                    <br />
                    Drone: {marker.hwId}
                    <br />
                    Latitude: {marker.lat.toFixed(6)}
                    <br />
                    Longitude: {marker.lon.toFixed(6)}
                    <br />
                    Tap the marker to open this drone card.
                  </Popup>
                </Marker>

                {marker.current && (
                  <>
                    <Polyline
                      positions={[
                        [marker.lat, marker.lon],
                        [marker.current.lat, marker.current.lon],
                      ]}
                      pathOptions={{ color: statusColor, weight: 2, opacity: 0.7 }}
                    />
                    <CircleMarker
                      center={[marker.current.lat, marker.current.lon]}
                      radius={9}
                      pathOptions={{
                        color: statusColor,
                        weight: 3,
                        fillColor: '#0f172a',
                        fillOpacity: 0.3,
                      }}
                    >
                      <Popup>
                        <strong>Live position</strong>
                        <br />
                        Drone: {marker.hwId}
                        <br />
                        Slot: {marker.posId}
                        <br />
                        Status: {marker.status}
                        <br />
                        Deviation: {marker.deviationMeters.toFixed(2)}m
                        <br />
                        GPS: {marker.gpsQuality} ({marker.satellites} sats)
                      </Popup>
                    </CircleMarker>
                  </>
                )}
              </React.Fragment>
            );
          })}
        </LeafletMapBase>
      </div>
    </section>
  );
};

DronePositionMap.propTypes = {
  originLat: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  originLon: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  drones: PropTypes.arrayOf(PropTypes.shape({
    hw_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
    pos_id: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    x: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    y: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  })).isRequired,
  deviationData: PropTypes.shape({
    deviations: PropTypes.object,
  }),
  trajectoryPositionsByPosId: PropTypes.object,
  forwardHeading: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  onDroneClick: PropTypes.func,
};

export default DronePositionMap;
