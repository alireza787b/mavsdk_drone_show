// app/dashboard/drone-dashboard/src/components/InitialLaunchPlot.js

import React, { useMemo } from 'react';
import Plot from 'react-plotly.js';
import PropTypes from 'prop-types';

// Constants for marker colors
const COLORS = {
  NORMAL_FILL: '#3498db',       // Blue for normal assignments
  SUBSTITUTE_FILL: '#f39c12',   // Orange for substitutions
  BORDER_GREEN: '#2ecc71',      // Green border for acceptable deviation
  BORDER_RED: '#e74c3c',        // Red border for excessive deviation
  UNASSIGNED_FILL: 'rgba(149, 165, 166, 0.3)', // Grey with transparency for unassigned
};

// Size constants
const MARKER_SIZE = 30;
const OFFSET_INCREMENT = 0.5; // Increment for offsetting multiple drones

function InitialLaunchPlot({ drones, onDroneClick, deviationData }) {
  // Prepare data using useMemo for performance optimization
  const plotData = useMemo(() => {
    // Map pos_id to assigned drones
    const posIdMap = {};
    drones.forEach((drone) => {
      if (posIdMap[drone.pos_id]) {
        posIdMap[drone.pos_id].push(drone);
      } else {
        posIdMap[drone.pos_id] = [drone];
      }
    });

    const plotPoints = [];

    // Process each position
    Object.entries(posIdMap).forEach(([posId, assignedDrones]) => {
      assignedDrones.forEach((drone, index) => {
        const deviation = deviationData[drone.hw_id];
        const isSubstitute = drone.hw_id !== drone.pos_id;
        const withinRange = deviation?.within_acceptable_range;

        // Determine fill color based on assignment type
        const fillColor = isSubstitute ? COLORS.SUBSTITUTE_FILL : COLORS.NORMAL_FILL;

        // Determine border color based on deviation
        const borderColor = withinRange ? COLORS.BORDER_GREEN : COLORS.BORDER_RED;

        // Offset positions if multiple drones are assigned to the same pos_id
        const offset = assignedDrones.length > 1 ? (index - (assignedDrones.length - 1) / 2) * OFFSET_INCREMENT : 0;

        plotPoints.push({
          hw_id: drone.hw_id,
          pos_id: drone.pos_id,
          x: parseFloat(drone.x) + offset, // North (X) with offset
          y: parseFloat(drone.y) + offset, // East (Y) with offset
          deviation_north: deviation?.deviation_north?.toFixed(2) || 'N/A',
          deviation_east: deviation?.deviation_east?.toFixed(2) || 'N/A',
          total_deviation: deviation?.total_deviation?.toFixed(2) || 'N/A',
          within_acceptable_range: withinRange,
          isSubstitute,
          fillColor,
          borderColor,
          label: drone.hw_id,
        });
      });
    });

    // Identify total positions based on pos_id range
    const posIds = drones.map((drone) => drone.pos_id);
    const totalPositions = Math.max(...posIds, 10); // At least 10 positions

    // Identify unassigned positions
    for (let pos = 1; pos <= totalPositions; pos++) {
      if (!posIdMap[pos]) {
        // Assuming each position has fixed coordinates
        // Replace the following with actual position coordinates if available
        const defaultX = 0;
        const defaultY = 0;
        plotPoints.push({
          hw_id: null,
          pos_id: pos,
          x: defaultX,
          y: defaultY,
          deviation_north: 'N/A',
          deviation_east: 'N/A',
          total_deviation: 'N/A',
          within_acceptable_range: null,
          isSubstitute: false,
          fillColor: COLORS.UNASSIGNED_FILL,
          borderColor: 'transparent',
          label: `Pos ${pos}`,
        });
      }
    }

    return plotPoints;
  }, [drones, deviationData]);

  // Separate assigned and unassigned drones for plotting
  const assignedPoints = plotData.filter((point) => point.hw_id !== null);
  const unassignedPoints = plotData.filter((point) => point.hw_id === null);

  return (
    <Plot
      data={[
        {
          // Assigned Drones
          x: assignedPoints.map((p) => p.y), // East (Y)
          y: assignedPoints.map((p) => p.x), // North (X)
          text: assignedPoints.map((p) => p.label),
          customdata: assignedPoints,
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: MARKER_SIZE,
            color: assignedPoints.map((p) => p.fillColor),
            line: {
              color: assignedPoints.map((p) => p.borderColor),
              width: 3,
            },
            opacity: 0.9,
          },
          text: assignedPoints.map((p) => p.hw_id),
          textfont: {
            color: 'white',
            size: 12,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Hardware ID:</b> %{customdata.hw_id}<br>' +
            '<b>Position ID:</b> %{customdata.pos_id}<br>' +
            '<b>North (X):</b> %{customdata.x}<br>' +
            '<b>East (Y):</b> %{customdata.y}<br>' +
            '<b>Deviation North:</b> %{customdata.deviation_north}<br>' +
            '<b>Deviation East:</b> %{customdata.deviation_east}<br>' +
            '<b>Total Deviation:</b> %{customdata.total_deviation}<br>' +
            '<b>Substitute:</b> %{customdata.isSubstitute}<br>' +
            '<b>Within Acceptable Range:</b> %{customdata.within_acceptable_range}<extra></extra>',
          name: 'Assigned Drones',
        },
        {
          // Unassigned Positions
          x: unassignedPoints.map((p) => p.y),
          y: unassignedPoints.map((p) => p.x),
          text: unassignedPoints.map((p) => p.label),
          type: 'scatter',
          mode: 'markers+text',
          marker: {
            size: MARKER_SIZE,
            color: unassignedPoints.map((p) => p.fillColor),
            line: {
              color: unassignedPoints.map((p) => p.borderColor),
              width: 2,
            },
            symbol: 'circle-open',
            opacity: 0.6,
          },
          text: unassignedPoints.map((p) => `Pos ${p.pos_id}`),
          textfont: {
            color: '#7f8c8d',
            size: 12,
            family: 'Arial',
          },
          textposition: 'middle center',
          hovertemplate:
            '<b>Position ID:</b> %{text}<br>' +
            '<b>Status:</b> Unassigned<extra></extra>',
          name: 'Unassigned Positions',
        },
      ]}
      layout={{
        title: 'Initial Launch Positions',
        xaxis: {
          title: 'East (Y)',
          showgrid: true,
          zeroline: true,
          range: [-100, 100], // Adjust based on your operational area
        },
        yaxis: {
          title: 'North (X)',
          showgrid: true,
          zeroline: true,
          range: [-100, 100], // Adjust based on your operational area
        },
        hovermode: 'closest',
        plot_bgcolor: '#f7f7f7',
        paper_bgcolor: '#f7f7f7',
        legend: {
          orientation: 'h',
          y: -0.2,
          x: 0.5,
          xanchor: 'center',
          traceorder: 'normal',
          font: {
            size: 12,
          },
        },
        margin: {
          l: 50,
          r: 50,
          t: 50,
          b: 100,
        },
      }}
      config={{
        responsive: true,
        displayModeBar: false, // Hide the mode bar for a cleaner UI
      }}
      onClick={(data) => {
        if (data.points.length === 0) return;
        const clickedPoint = data.points[0];
        if (!clickedPoint.customdata || !clickedPoint.customdata.hw_id) return;

        const clickedDroneHwId = clickedPoint.customdata.hw_id;
        onDroneClick(clickedDroneHwId);

        // Smooth scroll to the drone config card
        const droneConfigCard = document.querySelector(
          `.drone-config-card[data-hw-id="${clickedDroneHwId}"]`
        );
        if (droneConfigCard) {
          droneConfigCard.scrollIntoView({ behavior: 'smooth' });
        }
      }}
    />
  );
}

InitialLaunchPlot.propTypes = {
  drones: PropTypes.arrayOf(
    PropTypes.shape({
      hw_id: PropTypes.number.isRequired,
      pos_id: PropTypes.number.isRequired,
      x: PropTypes.string.isRequired,
      y: PropTypes.string.isRequired,
    })
  ).isRequired,
  onDroneClick: PropTypes.func.isRequired,
  deviationData: PropTypes.objectOf(
    PropTypes.shape({
      deviation_north: PropTypes.number,
      deviation_east: PropTypes.number,
      total_deviation: PropTypes.number,
      within_acceptable_range: PropTypes.bool,
    })
  ).isRequired,
};

export default InitialLaunchPlot;
