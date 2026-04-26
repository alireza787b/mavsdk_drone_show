// src/components/map/LeafletCoveragePreview.js
// Renders coverage paths as Leaflet Polylines — same data as CoveragePreview.js

import React, { useMemo } from 'react';
import { Polyline } from 'react-leaflet';
import { getDronePaletteColors } from '../../utilities/plotThemeColors';

const LeafletCoveragePreview = ({ plans, missionStatus }) => {
  const segments = useMemo(() => {
    if (!plans || plans.length === 0) return [];
    const result = [];
    const droneColors = getDronePaletteColors();

    plans.forEach((plan, droneIdx) => {
      const color = droneColors[droneIdx % droneColors.length];
      const droneState = missionStatus?.drone_states?.[plan.hw_id];
      const completedWpIdx = droneState?.current_waypoint_index || 0;

      let currentGroup = [];
      let currentIsSurvey = plan.waypoints[0]?.is_survey_leg ?? true;

      const flushGroup = (isSurvey, wpStartIdx) => {
        if (currentGroup.length < 2) {
          currentGroup = [];
          return;
        }
        const positions = currentGroup.map((wp) => [wp.lat, wp.lng]);
        const isCompleted = wpStartIdx < completedWpIdx;

        result.push({
          key: `${plan.hw_id}-${wpStartIdx}-${isSurvey}`,
          positions,
          color,
          isSurvey,
          opacity: isCompleted ? 1.0 : 0.5,
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

    return result;
  }, [plans, missionStatus]);

  if (segments.length === 0) return null;

  return (
    <>
      {segments.map((seg) => (
        <Polyline
          key={seg.key}
          positions={seg.positions}
          pathOptions={{
            color: seg.color,
            weight: seg.isSurvey ? 3 : 2,
            opacity: seg.opacity,
            dashArray: seg.isSurvey ? undefined : '6 4',
          }}
        />
      ))}
    </>
  );
};

export default LeafletCoveragePreview;
