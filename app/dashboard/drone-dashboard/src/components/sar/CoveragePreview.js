// src/components/sar/CoveragePreview.js
/**
 * Renders computed coverage paths as Mapbox GL Source/Layer (GeoJSON lines).
 * Color per drone, solid for survey legs, dashed for transit.
 */

import React, { useMemo } from 'react';
import { getDronePaletteColors } from '../../utilities/plotThemeColors';

let Source, Layer;
let mapboxAvailable = false;

try {
  const rgl = require('react-map-gl');
  Source = rgl.Source;
  Layer = rgl.Layer;
  mapboxAvailable = true;
} catch (e) {
  mapboxAvailable = false;
}

const CoveragePreview = ({ plans, missionStatus }) => {
  const geojsonData = useMemo(() => {
    if (!plans || plans.length === 0) return null;
    const features = [];
    const droneColors = getDronePaletteColors();

    plans.forEach((plan, droneIdx) => {
      const color = droneColors[droneIdx % droneColors.length];
      const droneState = missionStatus?.drone_states?.[plan.hw_id];
      const completedWpIdx = droneState?.current_waypoint_index || 0;

      // Group consecutive waypoints by type (survey vs transit)
      let currentGroup = [];
      let currentIsSurvey = plan.waypoints[0]?.is_survey_leg ?? true;

      const flushGroup = (isSurvey, wpStartIdx) => {
        if (currentGroup.length < 2) {
          currentGroup = [];
          return;
        }
        const coords = currentGroup.map(wp => [wp.lng, wp.lat]);
        const isCompleted = wpStartIdx < completedWpIdx;

        features.push({
          type: 'Feature',
          properties: {
            drone_id: plan.hw_id,
            color,
            is_survey: isSurvey,
            opacity: isCompleted ? 1.0 : 0.5,
            dash: isSurvey ? [1] : [2, 2],
          },
          geometry: { type: 'LineString', coordinates: coords },
        });
        currentGroup = [];
      };

      plan.waypoints.forEach((wp, i) => {
        if (wp.is_survey_leg !== currentIsSurvey && currentGroup.length > 0) {
          flushGroup(currentIsSurvey, i - currentGroup.length);
          currentIsSurvey = wp.is_survey_leg;
        }
        currentGroup.push(wp);
      });
      if (currentGroup.length > 0) {
        flushGroup(currentIsSurvey, plan.waypoints.length - currentGroup.length);
      }
    });

    return { type: 'FeatureCollection', features };
  }, [plans, missionStatus]);

  if (!mapboxAvailable || !geojsonData) return null;

  return (
    <>
      <Source id="coverage-paths" type="geojson" data={geojsonData}>
        {/* Survey legs - solid lines */}
        <Layer
          id="coverage-survey-lines"
          type="line"
          filter={['==', ['get', 'is_survey'], true]}
          paint={{
            'line-color': ['get', 'color'],
            'line-width': 3,
            'line-opacity': ['get', 'opacity'],
          }}
        />
        {/* Transit legs - dashed lines */}
        <Layer
          id="coverage-transit-lines"
          type="line"
          filter={['==', ['get', 'is_survey'], false]}
          paint={{
            'line-color': ['get', 'color'],
            'line-width': 2,
            'line-opacity': ['coalesce', ['get', 'opacity'], 0.4],
            'line-dasharray': [2, 2],
          }}
        />
        {/* Waypoint circles at higher zoom */}
        <Layer
          id="coverage-waypoints"
          type="circle"
          minzoom={14}
          paint={{
            'circle-radius': 3,
            'circle-color': ['get', 'color'],
            'circle-opacity': 0.6,
          }}
        />
      </Source>
    </>
  );
};

export default CoveragePreview;
